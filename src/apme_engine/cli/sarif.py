"""SARIF 2.1.0 output for APME violations.

Converts violation dicts (from the FixSession result) to a SARIF JSON document
suitable for upload to GitHub Code Scanning via ``codeql-action/upload-sarif``.
"""

from __future__ import annotations

from urllib.parse import quote as _url_quote

from apme_engine.cli._models import ViolationDict

_SarifNode = dict[str, object]

_SARIF_VERSION = "2.1.0"
_SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cos02/schemas/sarif-schema-2.1.0.json"

_SEVERITY_TO_SARIF_LEVEL: dict[str, str] = {
    "critical": "error",
    "error": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
    "unspecified": "warning",
}

_RULE_PREFIX_TO_HELP: dict[str, str] = {
    "L": "Lint rule — structural or style issue",
    "M": "Modernization rule — deprecated or outdated pattern",
    "R": "Risk rule — behavioral risk or anti-pattern",
    "P": "Policy rule — organizational policy violation",
    "SEC": "Security rule — secret or credential detected",
}


def _sarif_level(severity: str) -> str:
    """Map an APME severity label to a SARIF result level.

    Args:
        severity: APME severity string (e.g. "high", "medium").

    Returns:
        One of "error", "warning", "note".
    """
    return _SEVERITY_TO_SARIF_LEVEL.get(severity.lower(), "warning")


def _rule_help_text(rule_id: str) -> str:
    """Return a short help string based on the rule ID prefix.

    Args:
        rule_id: APME rule ID (e.g. "L003", "M005", "SEC:generic-api-key").

    Returns:
        Human-readable help text.
    """
    for prefix, text in _RULE_PREFIX_TO_HELP.items():
        if rule_id.startswith(prefix):
            return text
    return "APME rule"


def _make_location(v: ViolationDict) -> _SarifNode:
    """Build a SARIF physicalLocation from a violation dict.

    Args:
        v: Violation dict with ``file`` and optional ``line``.

    Returns:
        SARIF location object.
    """
    uri = str(v.get("file", ""))
    if uri.startswith("./"):
        uri = uri[2:]
    if not uri:
        return {"physicalLocation": {}}

    phys: _SarifNode = {
        "artifactLocation": {"uri": uri, "uriBaseId": "%SRCROOT%"},
    }

    line = v.get("line")
    if isinstance(line, int) and line > 0:
        phys["region"] = {"startLine": line}
    elif isinstance(line, list) and len(line) >= 2:
        start = max(1, int(line[0]))
        end = max(start, int(line[1]))
        phys["region"] = {"startLine": start, "endLine": end}

    return {"physicalLocation": phys}


def violations_to_sarif(
    violations: list[ViolationDict],
    *,
    tool_name: str = "apme",
    tool_version: str | None = None,
) -> _SarifNode:
    """Convert a list of APME violation dicts to a SARIF 2.1.0 document.

    Args:
        violations: List of violation dicts from ``violation_proto_to_dict``.
        tool_name: Name for the SARIF tool driver.
        tool_version: Optional version string (e.g. from ``importlib.metadata``).

    Returns:
        A JSON-serializable dict conforming to the SARIF 2.1.0 schema.
    """
    seen_rules: dict[str, _SarifNode] = {}
    results: list[_SarifNode] = []

    for v in violations:
        rule_id = str(v.get("rule_id", "unknown"))
        severity = str(v.get("severity", "medium"))
        message = str(v.get("message", "")) or rule_id

        if rule_id not in seen_rules:
            seen_rules[rule_id] = {
                "id": rule_id,
                "shortDescription": {"text": rule_id},
                "helpUri": f"https://apme.readthedocs.io/rules/{_url_quote(rule_id, safe='')}",
                "help": {"text": _rule_help_text(rule_id)},
                "defaultConfiguration": {"level": _sarif_level(severity)},
            }

        result: _SarifNode = {
            "ruleId": rule_id,
            "level": _sarif_level(severity),
            "message": {"text": message},
            "locations": [_make_location(v)],
        }
        results.append(result)

    driver: _SarifNode = {
        "name": tool_name,
        "informationUri": "https://github.com/ansible/apme",
        "rules": list(seen_rules.values()),
    }
    if tool_version:
        driver["version"] = tool_version
        driver["semanticVersion"] = tool_version

    return {
        "$schema": _SARIF_SCHEMA,
        "version": _SARIF_VERSION,
        "runs": [
            {
                "tool": {"driver": driver},
                "results": results,
            },
        ],
    }
