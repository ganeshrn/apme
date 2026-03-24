"""Remediation engine — convergence loop that applies Tier 1 transforms.

Uses ``StructuredFile`` to parse each YAML file once, apply all transforms
on the in-memory ``CommentedMap``/``CommentedSeq``, and serialize only when
needed (once per convergence pass, for re-scanning).
"""

from __future__ import annotations

import asyncio
import difflib
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from apme_engine.engine.models import RemediationClass, RemediationResolution, ViolationDict
from apme_engine.engine.node_index import NodeIndex
from apme_engine.remediation.ai_provider import (
    AIPatch,
    AIProposal,
    AIProvider,
    AISkipped,
    apply_patches,
    generate_patch_hunks,
)
from apme_engine.remediation.enrich import enrich_violations
from apme_engine.remediation.partition import (
    add_classification_to_violations,
    normalize_rule_id,
    partition_violations,
)
from apme_engine.remediation.registry import TransformRegistry
from apme_engine.remediation.structured import StructuredFile
from apme_engine.remediation.transforms._helpers import violation_line_to_int
from apme_engine.remediation.unit_segmenter import (
    FixableUnit,
    assign_violations_to_units,
    extract_units,
)

logger = logging.getLogger("apme.remediation")


@dataclass
class FilePatch:
    """A single file patch with diff and applied rule IDs.

    Attributes:
        path: File path that was patched.
        original: Original file content before patching.
        patched: Content after applying transforms.
        diff: Unified diff string (original -> patched).
        rule_ids: List of rule IDs applied to this file.
    """

    path: str
    original: str
    patched: str
    diff: str
    rule_ids: list[str] = field(default_factory=list)


@dataclass
class FixReport:
    """Summary of remediation run with patches and remaining violations.

    Attributes:
        passes: Number of convergence passes executed.
        fixed: Count of violations fixed.
        applied_patches: List of file patches applied.
        remaining_ai: Violations with no transform but ai_proposable.
        remaining_manual: Violations requiring manual fix.
        ai_proposed: AI proposals that passed validation.
        oscillation_detected: True if oscillation was detected and loop bailed.
    """

    passes: int
    fixed: int
    applied_patches: list[FilePatch]
    remaining_ai: list[ViolationDict]
    remaining_manual: list[ViolationDict]
    ai_proposed: list[AIProposal]
    oscillation_detected: bool


ScanFn = Callable[[list[str]], list[ViolationDict]]


class RemediationEngine:
    """Scan -> transform -> re-scan convergence loop.

    The engine does NOT own scanning — it receives a callable ``scan_fn``
    that accepts a list of file paths and returns violations.  The scan_fn
    reads file contents from disk, so when ``apply=False`` the engine
    writes temp content before each scan pass and restores afterwards.
    """

    def __init__(
        self,
        registry: TransformRegistry,
        scan_fn: ScanFn,
        *,
        max_passes: int = 5,
        max_ai_attempts: int = 2,
        verbose: bool = False,
        node_index: NodeIndex | None = None,
        ai_provider: AIProvider | None = None,
    ) -> None:
        """Initialize the remediation engine.

        Args:
            registry: Transform registry mapping rule IDs to fix functions.
            scan_fn: Callable that scans file paths and returns violations.
            max_passes: Maximum convergence passes (default 5).
            max_ai_attempts: Max LLM calls per file batch (default 2).
            verbose: Deprecated — logging is controlled by log level (ADR-033).
            node_index: Optional hierarchy node index for enrichment.
            ai_provider: Optional AI provider for Tier 2 escalation.
        """
        self._registry = registry
        self._scan_fn = scan_fn
        self._max_passes = max_passes
        self._max_ai_attempts = max_ai_attempts
        self._node_index = node_index
        self._ai_provider = ai_provider

    def set_node_index(self, node_index: NodeIndex) -> None:
        """Set or replace the hierarchy node index.

        Useful for lazy construction after the first scan has produced
        hierarchy payloads, avoiding a redundant pre-scan.

        Args:
            node_index: NodeIndex built from hierarchy payloads.
        """
        self._node_index = node_index

    def _write_files(self, file_contents: dict[str, str]) -> None:
        """Write file contents to disk.

        Args:
            file_contents: Map of file path to content string.
        """
        for fp, content in file_contents.items():
            Path(fp).write_text(content, encoding="utf-8")

    def _enrich(self, violations: list[ViolationDict]) -> None:
        """Enrich violations with tree node paths if a NodeIndex is available.

        The NodeIndex is built once before remediation starts.  After
        transforms shift line numbers the ``(file, line)`` secondary
        index may go stale, but ``enrich_violations`` only falls back to
        that index when a violation has no ``path`` (or an unknown one).
        Validators that already set ``path`` to the node key are
        unaffected by line-number drift.

        Args:
            violations: List of violation dicts to enrich in place.
        """
        if self._node_index is not None:
            enrich_violations(violations, self._node_index)

    def remediate(
        self,
        file_paths: list[str],
        *,
        apply: bool = False,
        initial_violations: list[ViolationDict] | None = None,
    ) -> FixReport:
        """Run the convergence loop on the given files.

        If ``apply`` is True, fixed files are written in place.
        If ``apply`` is False, content is written temporarily for each
        scan pass and originals are restored at the end; the returned
        ``FixReport`` carries diffs for review.

        Args:
            file_paths: List of file paths to remediate.
            apply: If True, write fixes in place; if False, restore originals.
            initial_violations: Pre-computed violations from a prior scan.
                When supplied the engine skips its first ``scan_fn`` call,
                avoiding a redundant scan pass.

        Returns:
            FixReport with passes, patches, and remaining violations.
        """
        file_contents: dict[str, str] = {}
        for fp in file_paths:
            file_contents[fp] = Path(fp).read_text(encoding="utf-8")

        # Build StructuredFile wrappers — parse each file once.
        # Files that fail to parse are left in file_contents as raw strings
        # and handled via the legacy string path in the registry.
        structured: dict[str, StructuredFile] = {}
        for fp, content in file_contents.items():
            sf = StructuredFile.from_content(fp, content)
            if sf is not None:
                structured[fp] = sf

        # Violations may report relative filenames (e.g. "site.yml" or
        # "tasks/main.yml") while file_contents keys are absolute paths.
        # Build a reverse lookup so we can resolve either form to the
        # canonical key.  When multiple files share a basename the entry
        # is set to None so we skip rather than resolving to the wrong file.
        _basename_to_key: dict[str, str | None] = {}
        for fp in file_paths:
            bn = Path(fp).name
            if bn in _basename_to_key and _basename_to_key[bn] != fp:
                _basename_to_key[bn] = None
            else:
                _basename_to_key[bn] = fp
            _basename_to_key[fp] = fp

        def _resolve_file(vf: str) -> str | None:
            if vf in file_contents:
                return vf
            candidate = _basename_to_key.get(vf) or _basename_to_key.get(Path(vf).name)
            if candidate is not None:
                return candidate
            # Try suffix matching for relative paths (e.g. "tasks/main.yml"
            # matching "/workspace/role/tasks/main.yml").
            if vf and "/" in vf:
                suffix = "/" + vf
                matches = [fp for fp in file_paths if fp.endswith(suffix)]
                if len(matches) == 1:
                    return matches[0]
            if vf:
                logger.debug("Skipping violation: ambiguous or unknown file '%s'", vf)
            return None

        originals = dict(file_contents)
        all_applied_rules: dict[str, list[str]] = {fp: [] for fp in file_paths}
        prev_count = float("inf")
        oscillation = False
        passes = 0

        for pass_num in range(1, self._max_passes + 1):
            passes = pass_num

            if initial_violations is not None and pass_num == 1:
                violations = initial_violations
                self._enrich(violations)
            else:
                self._write_files(file_contents)
                violations = self._scan_fn(file_paths)
                self._enrich(violations)
            tier1, _, _ = partition_violations(violations, self._registry)

            logger.debug("Remediation: pass %d — %d fixable (Tier 1)", pass_num, len(tier1))

            if not tier1:
                logger.info("Remediation: converged at pass %d (0 fixable)", pass_num)
                break

            tier1.sort(key=violation_line_to_int, reverse=True)

            applied_this_pass = 0
            for v in tier1:
                rule_id = normalize_rule_id(str(v.get("rule_id", "")))
                vf_raw = str(v.get("file", ""))
                vf = _resolve_file(vf_raw)

                if vf is None:
                    continue

                sf = structured.get(vf)
                if sf is not None:
                    applied = self._registry.apply_structured(rule_id, sf, v)
                    if applied:
                        all_applied_rules[vf].append(rule_id)
                        applied_this_pass += 1
                    else:
                        v["remediation_class"] = RemediationClass.AI_CANDIDATE
                        v["remediation_resolution"] = RemediationResolution.TRANSFORM_FAILED
                else:
                    result = self._registry.apply(rule_id, file_contents[vf], v)
                    if result.applied:
                        file_contents[vf] = result.content
                        all_applied_rules[vf].append(rule_id)
                        applied_this_pass += 1
                    else:
                        v["remediation_class"] = RemediationClass.AI_CANDIDATE
                        v["remediation_resolution"] = RemediationResolution.TRANSFORM_FAILED

            # Serialize dirty structured files once per pass
            for fp, sf in structured.items():
                if sf.dirty:
                    file_contents[fp] = sf.serialize()
                    sf.reset_dirty()

            logger.debug("Remediation: pass %d applied %d transforms", pass_num, applied_this_pass)

            if applied_this_pass == 0:
                logger.debug("Remediation: pass %d transforms produced no changes, bail", pass_num)
                break

            self._write_files(file_contents)
            new_violations = self._scan_fn(file_paths)
            self._enrich(new_violations)
            new_tier1, _, _ = partition_violations(new_violations, self._registry)
            new_fixable = len(new_tier1)

            if new_fixable >= prev_count:
                logger.warning("Remediation: pass %d oscillation (%d fixable >= %d)", pass_num, new_fixable, prev_count)
                oscillation = True
                for v in new_tier1:
                    v["remediation_class"] = RemediationClass.AI_CANDIDATE
                    v["remediation_resolution"] = RemediationResolution.OSCILLATION
                break

            prev_count = new_fixable

            if new_fixable == 0:
                logger.info("Remediation: fully converged at pass %d (0 fixable)", pass_num)
                break

            # Re-parse structured files from the serialized content
            # so line numbers match the on-disk state for the next pass
            for fp in list(structured):
                sf = StructuredFile.from_content(fp, file_contents[fp])
                if sf is not None:
                    structured[fp] = sf

        # Final partition of remaining violations
        self._write_files(file_contents)
        final_violations = self._scan_fn(file_paths)
        self._enrich(final_violations)
        add_classification_to_violations(final_violations, self._registry)
        _, tier2, tier3 = partition_violations(final_violations, self._registry)

        # Build patches
        patches: list[FilePatch] = []
        for fp in file_paths:
            if file_contents[fp] != originals[fp]:
                diff = "".join(
                    difflib.unified_diff(
                        originals[fp].splitlines(keepends=True),
                        file_contents[fp].splitlines(keepends=True),
                        fromfile=f"a/{fp}",
                        tofile=f"b/{fp}",
                    )
                )
                patches.append(
                    FilePatch(
                        path=fp,
                        original=originals[fp],
                        patched=file_contents[fp],
                        diff=diff,
                        rule_ids=all_applied_rules.get(fp, []),
                    )
                )

        # If not applying, restore originals
        if not apply:
            self._write_files(originals)

        fixed_count = sum(len(p.rule_ids) for p in patches)

        # Tier 2 AI escalation (only if provider is set and violations exist)
        ai_proposals: list[AIProposal] = []
        if self._ai_provider is not None and tier2:
            logger.info("Remediation: AI escalation — %d Tier 2 candidate(s)", len(tier2))
            ai_proposals = self._escalate_tier2(tier2, file_contents, _resolve_file)

        return FixReport(
            passes=passes,
            fixed=fixed_count,
            applied_patches=patches,
            remaining_ai=tier2,
            remaining_manual=tier3,
            ai_proposed=ai_proposals,
            oscillation_detected=oscillation,
        )

    def _escalate_tier2(
        self,
        violations: list[ViolationDict],
        file_contents: dict[str, str],
        resolve_file: Callable[[str], str | None],
    ) -> list[AIProposal]:
        """Run AI escalation for Tier 2 violations with hybrid validation.

        Groups violations by file, sends one batch LLM call per file
        (chunked if >MAX_VIOLATIONS_PER_CHUNK), validates patches.

        Args:
            violations: Tier 2 violations to escalate.
            file_contents: Current file contents (post Tier 1 fixes).
            resolve_file: Resolves relative violation paths to absolute keys.

        Returns:
            list[AIProposal]: Validated proposals (one per file).
        """
        if self._ai_provider is None:
            return []

        return asyncio.run(self._escalate_tier2_async(violations, file_contents, resolve_file))

    async def _escalate_tier2_async(
        self,
        violations: list[ViolationDict],
        file_contents: dict[str, str],
        resolve_file: Callable[[str], str | None],
    ) -> list[AIProposal]:
        """Async inner loop: segment by unit, call LLM per unit, reassemble.

        When a NodeIndex is available, violations are mapped to
        individual FixableUnits (tasks) and the LLM receives only the
        unit snippet — drastically reducing token usage and improving
        fix quality.  Orphan violations that cannot be mapped to a unit
        fall back to a full-file batch call.

        Args:
            violations: Tier 2 violations to escalate.
            file_contents: Current file contents (post Tier 1 fixes).
            resolve_file: Resolves relative violation paths to absolute keys.

        Returns:
            list[AIProposal]: Validated proposals.
        """
        if hasattr(self._ai_provider, "reconnect"):
            await self._ai_provider.reconnect()  # type: ignore[union-attr]

        by_file: dict[str, list[ViolationDict]] = defaultdict(list)
        for v in violations:
            vf_raw = str(v.get("file", ""))
            vf = resolve_file(vf_raw)
            if vf is None:
                continue
            by_file[vf].append(v)

        results: list[AIProposal] = []

        for file_path in sorted(by_file):
            file_violations = by_file[file_path]
            content = file_contents.get(file_path, "")
            if not content:
                continue

            logger.debug("AI file: %s (%d violations)", Path(file_path).name, len(file_violations))

            if self._node_index is not None and hasattr(self._ai_provider, "propose_unit_fixes"):
                proposal = await self._escalate_by_units(file_path, file_violations, content)
            else:
                proposal = await self._try_batch_proposal(file_path, file_violations, content)

            if proposal is not None:
                results.append(proposal)

        return results

    async def _escalate_by_units(
        self,
        file_path: str,
        violations: list[ViolationDict],
        file_content: str,
    ) -> AIProposal | None:
        """Segment a file into units, call LLM per unit, reassemble.

        Args:
            file_path: Absolute file path.
            violations: All Tier 2 violations for this file.
            file_content: Current file content.

        Returns:
            AIProposal combining all unit-level patches, or None.
        """
        if self._ai_provider is None or self._node_index is None:
            return None

        units = extract_units(file_path, file_content, self._node_index)
        if not units:
            logger.debug("No units found, falling back to full-file")
            return await self._try_batch_proposal(file_path, violations, file_content)

        orphans = assign_violations_to_units(units, violations)
        units_with_violations = [u for u in units if u.violations]

        logger.debug("%d unit(s) with violations, %d orphan(s)", len(units_with_violations), len(orphans))

        # Limit concurrency to avoid overwhelming the LLM backend
        max_concurrent = 8
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _process_unit(
            unit: FixableUnit,
        ) -> tuple[list[AIPatch], list[AISkipped]]:
            async with semaphore:
                patches, skipped = await self._ai_provider.propose_unit_fixes(  # type: ignore[union-attr]
                    unit.violations,
                    unit.snippet,
                    file_path,
                    unit.line_start,
                    unit.line_end,
                )
                valid = [p for p in patches if p.confidence >= 0.01] if patches else []
                return valid, skipped or []

        # Process all units in parallel (bounded by semaphore)
        unit_results: list[tuple[list[AIPatch], list[AISkipped]] | BaseException] = await asyncio.gather(
            *[_process_unit(u) for u in units_with_violations],
            return_exceptions=True,
        )

        all_patches: list[AIPatch] = []
        all_skipped: list[AISkipped] = []

        for i, result in enumerate(unit_results):
            unit = units_with_violations[i]
            if isinstance(result, BaseException):
                logger.error("Unit L%d-%d: %s", unit.line_start, unit.line_end, result)
                continue
            patches, skipped = result
            if patches:
                all_patches.extend(patches)
            if skipped:
                all_skipped.extend(skipped)

        if orphans:
            logger.debug("Fallback: %d orphan violation(s)", len(orphans))
            fallback_patches, fallback_skipped = await self._ai_provider.propose_fixes(orphans, file_content)
            if fallback_patches:
                all_patches.extend(p for p in fallback_patches if p.confidence >= 0.01)
            all_skipped.extend(fallback_skipped)

        if not all_patches and not all_skipped:
            return None

        # Re-validate unit patches the same way as batch patches
        is_valid, transforms_applied, feedback = self._validate_batch_patches(all_patches, file_path, file_content)

        if not is_valid and feedback:
            logger.debug("Unit patches failed validation: %s", feedback.split(chr(10))[0])
            # Mark as AI_FAILED instead of returning a broken proposal
            for v in violations:
                v["remediation_resolution"] = RemediationResolution.AI_FAILED
            return None

        for v in violations:
            rid = str(v.get("rule_id", ""))
            patched_rules = {p.rule_id for p in all_patches}
            if rid in patched_rules:
                conf = min(p.confidence for p in all_patches if p.rule_id == rid)
                v["remediation_resolution"] = (
                    RemediationResolution.AI_LOW_CONFIDENCE if conf < 0.7 else RemediationResolution.AI_PROPOSED
                )

        generate_patch_hunks(file_content, all_patches, file_path)
        patched_content = apply_patches(file_content, all_patches)
        full_diff = "".join(
            difflib.unified_diff(
                file_content.splitlines(keepends=True),
                patched_content.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path} (AI proposed)",
            )
        )

        return AIProposal(
            file=file_path,
            original_yaml=file_content,
            fixed_yaml=patched_content,
            patches=all_patches,
            diff=full_diff,
            skipped=all_skipped,
            hybrid_transforms_applied=transforms_applied,
        )

    async def _try_batch_proposal(
        self,
        file_path: str,
        violations: list[ViolationDict],
        file_content: str,
    ) -> AIProposal | None:
        """Send all violations for a file in a single LLM call with retry.

        Assumes a frontier model with large context/output window.

        Args:
            file_path: Absolute path to the file.
            violations: All violations for this file.
            file_content: Current file content.

        Returns:
            Validated AIProposal, or None if all attempts fail.
        """
        if self._ai_provider is None:
            return None

        all_patches: list[AIPatch] = []
        all_skipped: list[AISkipped] = []
        total_t1_applied = 0
        feedback: str | None = None

        for attempt in range(self._max_ai_attempts):
            patches, skipped = await self._ai_provider.propose_fixes(
                violations,
                file_content,
                feedback=feedback,
            )

            all_skipped = skipped
            is_last = attempt >= self._max_ai_attempts - 1

            if patches is None:
                logger.warning(
                    "AI attempt %d/%d: provider returned no patches (error or unparseable response), %s",
                    attempt + 1,
                    self._max_ai_attempts,
                    "giving up" if is_last else "retrying",
                )
                if is_last:
                    break
                feedback = (
                    "Your previous response could not be used. "
                    "Respond with ONLY a valid JSON object — no markdown fences, "
                    "no extra text. Keep the response concise to avoid truncation."
                )
                continue

            patches = [p for p in patches if p.confidence >= 0.01]

            if not patches:
                logger.debug("AI attempt %d: all patches below confidence threshold", attempt + 1)
                break

            validated, t1_applied, new_feedback = self._validate_batch_patches(patches, file_path, file_content)

            if validated:
                total_t1_applied += t1_applied
                logger.debug(
                    "AI attempt %d: validated (%d patches, %d hybrid transforms)",
                    attempt + 1,
                    len(patches),
                    t1_applied,
                )
                all_patches = patches
                break

            feedback = new_feedback
            logger.debug(
                "AI attempt %d: validation failed, %s\n%s",
                attempt + 1,
                "retrying" if not is_last else "giving up",
                feedback or "(no feedback)",
            )
        else:
            pass

        if not all_patches:
            for v in violations:
                v["remediation_resolution"] = RemediationResolution.AI_FAILED
            return None

        # Generate diff hunks and build proposal
        generate_patch_hunks(
            file_content,
            all_patches,
            file_path,
        )
        patched_content = apply_patches(file_content, all_patches)
        full_diff = "".join(
            difflib.unified_diff(
                file_content.splitlines(keepends=True),
                patched_content.splitlines(keepends=True),
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path} (AI proposed)",
            )
        )

        # Set resolution on violations that have matching patches
        patched_rules = {p.rule_id for p in all_patches}
        for v in violations:
            rid = str(v.get("rule_id", ""))
            if rid in patched_rules:
                conf = min(p.confidence for p in all_patches if p.rule_id == rid)
                if conf < 0.7:
                    v["remediation_resolution"] = RemediationResolution.AI_LOW_CONFIDENCE
                else:
                    v["remediation_resolution"] = RemediationResolution.AI_PROPOSED

        return AIProposal(
            file=file_path,
            original_yaml=file_content,
            fixed_yaml=patched_content,
            patches=all_patches,
            diff=full_diff,
            skipped=all_skipped,
            hybrid_transforms_applied=total_t1_applied,
        )

    def _validate_batch_patches(
        self,
        patches: list[AIPatch],
        file_path: str,
        original_content: str,
    ) -> tuple[bool, int, str | None]:
        """Re-validate AI patches through APME validators.

        Applies all patches, scans, checks that no new violations were
        introduced (pre-existing ones are expected and ignored).

        Args:
            patches: AI patches to validate.
            file_path: Path to the file.
            original_content: Original file content (for restoration).

        Returns:
            Tuple of (is_valid, transforms_applied, feedback_for_retry).
        """
        from collections import Counter  # noqa: PLC0415

        baseline_violations = self._scan_fn([file_path])
        baseline_counts: Counter[str] = Counter(str(v.get("rule_id", "")) for v in baseline_violations)

        patched = apply_patches(original_content, patches)

        try:
            import yaml  # noqa: PLC0415
            from yaml import SafeLoader  # noqa: PLC0415

            class _StrictLoader(SafeLoader):
                """SafeLoader that rejects duplicate keys."""

            def _no_dup_keys(loader: _StrictLoader, node: yaml.MappingNode) -> dict:  # type: ignore[type-arg]
                seen: set[str] = set()
                for key_node, _ in node.value:
                    key = loader.construct_object(key_node)  # type: ignore[no-untyped-call]
                    if key in seen:
                        msg = f"duplicate key: {key}"
                        raise yaml.constructor.ConstructorError(
                            "while constructing a mapping",
                            node.start_mark,
                            msg,
                            key_node.start_mark,
                        )
                    seen.add(key)
                return loader.construct_mapping(node)

            _StrictLoader.add_constructor(
                yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                _no_dup_keys,
            )
            yaml.load(patched, Loader=_StrictLoader)  # noqa: S506
        except yaml.YAMLError as exc:
            short = str(exc).split("\n")[0]
            logger.debug("AI output is invalid YAML: %s", short)
            return (
                False,
                0,
                f"Your patches produced invalid YAML:\n{exc}\n"
                "Do NOT include structural keys (tasks:, vars:, handlers:) "
                "in your patch unless they fall within your line_start:line_end. "
                "Including them creates duplicates.",
            )

        try:
            Path(file_path).write_text(patched, encoding="utf-8")
            post_violations = self._scan_fn([file_path])

            new_violations = _find_truly_new_violations(post_violations, baseline_counts)

            if not new_violations:
                return True, 0, None

            # Hybrid cleanup: apply Tier 1 transforms to fix new issues
            tier1, _, _ = partition_violations(new_violations, self._registry)
            transforms_applied = 0

            if tier1:
                content = patched
                tier1.sort(key=violation_line_to_int, reverse=True)

                for v in tier1:
                    rule_id = normalize_rule_id(str(v.get("rule_id", "")))
                    result = self._registry.apply(rule_id, content, v)
                    if result.applied:
                        content = result.content
                        transforms_applied += 1

                Path(file_path).write_text(content, encoding="utf-8")
                remaining_all = self._scan_fn([file_path])
                remaining_new = _find_truly_new_violations(remaining_all, baseline_counts)

                if not remaining_new:
                    return True, transforms_applied, None

                new_violations = remaining_new

            feedback_lines = ["Your patches introduced new violations:"]
            for v in new_violations[:5]:
                feedback_lines.append(f"- {v.get('rule_id')}: {v.get('message')} (line {v.get('line')})")
            if len(new_violations) > 5:
                feedback_lines.append(f"  ... and {len(new_violations) - 5} more")
            return False, transforms_applied, "\n".join(feedback_lines)
        finally:
            Path(file_path).write_text(original_content, encoding="utf-8")


def _find_truly_new_violations(
    post_violations: list[ViolationDict],
    baseline_counts: dict[str, int],
) -> list[ViolationDict]:
    """Identify violations that are genuinely new, not just line-shifted.

    AI patches change line counts, so pre-existing violations appear at
    different line numbers.  Instead of exact (rule_id, line) matching,
    compare per-rule counts: only violations whose rule_id count *exceeds*
    the baseline are considered new.

    Args:
        post_violations: Violations from the post-patch scan.
        baseline_counts: Per-rule violation counts from the pre-patch baseline.

    Returns:
        Violations whose rule count increased after patching.
    """
    from collections import Counter  # noqa: PLC0415

    post_counts: Counter[str] = Counter(str(v.get("rule_id", "")) for v in post_violations)

    increased_rules = {rid for rid, cnt in post_counts.items() if cnt > baseline_counts.get(rid, 0)}
    if not increased_rules:
        return []

    budget: dict[str, int] = {rid: post_counts[rid] - baseline_counts.get(rid, 0) for rid in increased_rules}
    new_violations: list[ViolationDict] = []
    for v in post_violations:
        rid = str(v.get("rule_id", ""))
        if rid in budget and budget[rid] > 0:
            new_violations.append(v)
            budget[rid] -= 1
    return new_violations


def _chunk_violations(
    violations: list[ViolationDict],
    max_per_chunk: int,
) -> list[list[ViolationDict]]:
    """Split violations into chunks of at most max_per_chunk.

    Args:
        violations: Full list of violations.
        max_per_chunk: Maximum violations per chunk.

    Returns:
        List of violation sub-lists.
    """
    if len(violations) <= max_per_chunk:
        return [violations]
    return [violations[i : i + max_per_chunk] for i in range(0, len(violations), max_per_chunk)]
