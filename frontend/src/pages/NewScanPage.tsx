import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  useSessionStream,
  type Proposal,
  type SessionStatus,
  type ProgressEntry,
  type Tier1Result,
  type SessionResult,
} from "../hooks/useSessionStream";

type TabId = "upload" | "project";

export function NewScanPage() {
  const [activeTab, setActiveTab] = useState<TabId>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [ansibleVersion, setAnsibleVersion] = useState("");
  const [collections, setCollections] = useState("");
  const [enableAi, setEnableAi] = useState(true);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);

  const {
    status,
    progress,
    scanId,
    tier1,
    proposals,
    result,
    error,
    startSession,
    approve,
    cancel,
    reset,
  } = useSessionStream();

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      if (status !== "idle") return;
      const dropped = Array.from(e.dataTransfer.files);
      setFiles((prev) => [...prev, ...dropped]);
    },
    [status],
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!e.target.files) return;
      setFiles((prev) => [...prev, ...Array.from(e.target.files!)]);
      e.target.value = "";
    },
    [],
  );

  const removeFile = useCallback((idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleSubmit = useCallback(() => {
    if (files.length === 0) return;
    const colls = collections
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean);
    startSession(files, {
      ansibleVersion,
      collections: colls.length ? colls : undefined,
      enableAi,
    });
  }, [files, ansibleVersion, collections, enableAi, startSession]);

  const handleReset = useCallback(() => {
    reset();
    setFiles([]);
  }, [reset]);

  const isRunning =
    status === "connecting" ||
    status === "uploading" ||
    status === "scanning" ||
    status === "applying";

  return (
    <>
      <header className="apme-page-header">
        <h1 className="apme-page-title">New Scan</h1>
      </header>

      <div className="apme-tabs">
        <button
          className={`apme-tab ${activeTab === "upload" ? "active" : ""}`}
          onClick={() => setActiveTab("upload")}
          disabled={status !== "idle"}
        >
          Upload Files
        </button>
        <button
          className="apme-tab disabled"
          title="Coming soon — SCM/project mode"
          disabled
        >
          Project (SCM)
        </button>
      </div>

      {/* ── File upload form ────────────────────────────────────── */}
      {activeTab === "upload" && status === "idle" && (
        <div className="apme-scan-form">
          <div
            className={`apme-drop-zone ${isDragOver ? "drag-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="apme-drop-icon">+</div>
            <div className="apme-drop-text">
              Drop Ansible files here or click to browse
            </div>
            <div className="apme-drop-hint">
              Supports individual files or entire directories
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".yml,.yaml,.json,.j2,.jinja2,.cfg,.ini,.toml,.py,.sh"
              style={{ display: "none" }}
              onChange={handleFileSelect}
            />
          </div>

          <div style={{ marginTop: 8 }}>
            <button
              className="apme-btn-secondary"
              onClick={() => dirInputRef.current?.click()}
            >
              Select Directory
            </button>
            <input
              ref={dirInputRef}
              type="file"
              /* @ts-expect-error webkitdirectory is non-standard */
              webkitdirectory=""
              style={{ display: "none" }}
              onChange={handleFileSelect}
            />
          </div>

          {files.length > 0 && (
            <div className="apme-file-list">
              <h3>
                {files.length} file{files.length !== 1 ? "s" : ""} selected
              </h3>
              <ul>
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`} className="apme-file-item">
                    <span className="apme-file-name">
                      {(f as File & { webkitRelativePath?: string })
                        .webkitRelativePath || f.name}
                    </span>
                    <span className="apme-file-size">
                      {(f.size / 1024).toFixed(1)} KB
                    </span>
                    <button
                      className="apme-file-remove"
                      onClick={() => removeFile(i)}
                      aria-label={`Remove ${f.name}`}
                    >
                      x
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <details className="apme-options-panel">
            <summary>Advanced Options</summary>
            <div className="apme-form-group">
              <label htmlFor="ansible-version">Ansible Core Version</label>
              <input
                id="ansible-version"
                type="text"
                placeholder="e.g. 2.16"
                value={ansibleVersion}
                onChange={(e) => setAnsibleVersion(e.target.value)}
              />
            </div>
            <div className="apme-form-group">
              <label htmlFor="collections">Collections (comma-separated)</label>
              <input
                id="collections"
                type="text"
                placeholder="e.g. ansible.posix, community.general"
                value={collections}
                onChange={(e) => setCollections(e.target.value)}
              />
            </div>
            <div className="apme-form-group">
              <label className="apme-checkbox-label">
                <input
                  type="checkbox"
                  checked={enableAi}
                  onChange={(e) => setEnableAi(e.target.checked)}
                />
                Enable AI-assisted remediation (Tier 2)
              </label>
            </div>
          </details>

          <button
            className="apme-btn-primary"
            disabled={files.length === 0}
            onClick={handleSubmit}
          >
            Start Scan
          </button>
        </div>
      )}

      {/* ── Progress ────────────────────────────────────────────── */}
      {isRunning && (
        <ScanProgress status={status} progress={progress} onCancel={cancel} />
      )}

      {/* ── Tier 1 results ──────────────────────────────────────── */}
      {status === "tier1_done" && tier1 && (
        <Tier1Results tier1={tier1} />
      )}

      {/* ── AI proposals for approval ──────────────────────────── */}
      {status === "awaiting_approval" && proposals.length > 0 && (
        <>
          {tier1 && <Tier1Results tier1={tier1} />}
          <ProposalApproval proposals={proposals} onApprove={approve} />
        </>
      )}

      {/* ── Final result ────────────────────────────────────────── */}
      {status === "complete" && result && (
        <SessionComplete result={result} scanId={scanId} tier1={tier1} />
      )}
      {status === "complete" && !result && (
        <div className="apme-scan-complete">
          <div className="apme-complete-icon">&#10003;</div>
          <h2>Session Complete</h2>
          {scanId && (
            <Link to={`/scans/${scanId}`} className="apme-link">
              View scan details
            </Link>
          )}
        </div>
      )}

      {/* ── Error ───────────────────────────────────────────────── */}
      {status === "error" && (
        <div className="apme-scan-error">
          <h2>Session Failed</h2>
          <p className="apme-error-message">{error}</p>
          <button className="apme-btn-primary" onClick={handleReset}>
            Try Again
          </button>
        </div>
      )}
    </>
  );
}

// ── Sub-components ─────────────────────────────────────────────────

function ScanProgress({
  status,
  progress,
  onCancel,
}: {
  status: SessionStatus;
  progress: ProgressEntry[];
  onCancel: () => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [progress.length]);

  const label =
    status === "connecting"
      ? "Connecting..."
      : status === "uploading"
        ? "Uploading files..."
        : status === "applying"
          ? "Applying approved fixes..."
          : "Scanning...";

  return (
    <div className="apme-scan-progress">
      <div className="apme-progress-header">
        <h2>{label}</h2>
        <button className="apme-btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>

      <div className="apme-spinner" />

      <div className="apme-timeline">
        {progress.map((entry, i) => (
          <div key={i} className="apme-timeline-entry">
            <span className="apme-timeline-phase">{entry.phase}</span>
            <span className="apme-timeline-message">{entry.message}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function Tier1Results({ tier1 }: { tier1: Tier1Result }) {
  const patchCount = tier1.patches.length;
  const formatCount = tier1.format_diffs.length;
  const [expanded, setExpanded] = useState(false);

  if (patchCount === 0 && formatCount === 0) return null;

  return (
    <div className="apme-tier1-results">
      <div className="apme-tier1-header">
        <span className="apme-badge passed">Auto-Fix</span>
        <h3>
          Tier 1 — {patchCount} fix{patchCount !== 1 ? "es" : ""} applied
          {formatCount > 0 && `, ${formatCount} formatted`}
        </h3>
        <button
          className="apme-btn-secondary"
          onClick={() => setExpanded(!expanded)}
          style={{ marginLeft: "auto", fontSize: 12, padding: "4px 10px" }}
        >
          {expanded ? "Collapse" : "Show Diffs"}
        </button>
      </div>

      {expanded && (
        <div className="apme-tier1-diffs">
          {tier1.patches.map((p, i) => (
            <div key={i} className="apme-diff-block">
              <div className="apme-diff-file">
                <span className="apme-file-name">{p.file}</span>
                {p.applied_rules.length > 0 && (
                  <span className="apme-diff-rules">
                    {p.applied_rules.join(", ")}
                  </span>
                )}
              </div>
              {p.diff && <pre className="apme-diff-content">{p.diff}</pre>}
            </div>
          ))}
          {tier1.format_diffs.map((d, i) => (
            <div key={`fmt-${i}`} className="apme-diff-block">
              <div className="apme-diff-file">
                <span className="apme-file-name">{d.file}</span>
                <span className="apme-badge running" style={{ fontSize: 10 }}>
                  format
                </span>
              </div>
              {d.diff && <pre className="apme-diff-content">{d.diff}</pre>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalApproval({
  proposals,
  onApprove,
}: {
  proposals: Proposal[];
  onApprove: (ids: string[]) => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const toggleAll = useCallback(() => {
    setSelected((prev) =>
      prev.size === proposals.length
        ? new Set()
        : new Set(proposals.map((p) => p.id)),
    );
  }, [proposals]);

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleSubmit = useCallback(() => {
    onApprove(Array.from(selected));
  }, [selected, onApprove]);

  const allSelected = selected.size === proposals.length;

  return (
    <div className="apme-proposals-section">
      <div className="apme-proposals-header">
        <div>
          <span className="apme-badge" style={{ background: "rgba(212, 168, 67, 0.2)", color: "var(--apme-sev-medium)" }}>
            AI Review
          </span>
          <h3>
            {proposals.length} AI Proposal{proposals.length !== 1 ? "s" : ""}
          </h3>
          <p className="apme-proposals-hint">
            Review each proposed change and select which to apply.
          </p>
        </div>
        <div className="apme-proposals-actions">
          <button className="apme-btn-secondary" onClick={toggleAll}>
            {allSelected ? "Deselect All" : "Select All"}
          </button>
          <button className="apme-btn-primary" onClick={handleSubmit}>
            Apply {selected.size} Selected
          </button>
        </div>
      </div>

      <div className="apme-proposals-list">
        {proposals.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            selected={selected.has(p.id)}
            onToggle={() => toggle(p.id)}
          />
        ))}
      </div>
    </div>
  );
}

function ProposalCard({
  proposal,
  selected,
  onToggle,
}: {
  proposal: Proposal;
  selected: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasDiff = Boolean(proposal.before_text || proposal.diff_hunk);
  const confidencePct = Math.round(proposal.confidence * 100);

  return (
    <div className={`apme-proposal-card ${selected ? "selected" : ""}`}>
      <div className="apme-proposal-header" onClick={onToggle}>
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          onClick={(e) => e.stopPropagation()}
          className="apme-proposal-checkbox"
        />
        <div className="apme-proposal-meta">
          <span className="apme-rule-id">{proposal.rule_id}</span>
          <span className="apme-proposal-file">
            {proposal.file}
            {proposal.line_start > 0 && (
              <span className="apme-line-number">
                :{proposal.line_start}
                {proposal.line_end > proposal.line_start &&
                  `-${proposal.line_end}`}
              </span>
            )}
          </span>
          <span className="apme-badge running" style={{ fontSize: 10 }}>
            Tier {proposal.tier}
          </span>
        </div>
        <div className="apme-proposal-confidence">
          <div className="apme-confidence-bar">
            <div
              className="apme-confidence-fill"
              style={{
                width: `${confidencePct}%`,
                backgroundColor:
                  confidencePct >= 80
                    ? "var(--apme-green)"
                    : confidencePct >= 50
                      ? "var(--apme-sev-medium)"
                      : "var(--apme-sev-error)",
              }}
            />
          </div>
          <span className="apme-confidence-label">{confidencePct}%</span>
        </div>
        {hasDiff && (
          <button
            className="apme-btn-secondary apme-proposal-expand"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
          >
            {expanded ? "Hide" : "Diff"}
          </button>
        )}
      </div>

      {proposal.explanation && (
        <div className="apme-proposal-explanation">{proposal.explanation}</div>
      )}

      {expanded && hasDiff && (
        <div className="apme-proposal-diff">
          {proposal.diff_hunk ? (
            <pre className="apme-diff-content">{proposal.diff_hunk}</pre>
          ) : (
            <DiffView
              before={proposal.before_text}
              after={proposal.after_text}
            />
          )}
        </div>
      )}
    </div>
  );
}

function DiffView({ before, after }: { before: string; after: string }) {
  const beforeLines = useMemo(() => before.split("\n"), [before]);
  const afterLines = useMemo(() => after.split("\n"), [after]);

  return (
    <div className="apme-side-by-side">
      <div className="apme-diff-pane">
        <div className="apme-diff-pane-header">Before</div>
        <pre className="apme-diff-content apme-diff-remove">
          {beforeLines.map((line, i) => (
            <span key={i} className="apme-diff-line">
              <span className="apme-diff-linenum">{i + 1}</span>
              {line}
              {"\n"}
            </span>
          ))}
        </pre>
      </div>
      <div className="apme-diff-pane">
        <div className="apme-diff-pane-header">After</div>
        <pre className="apme-diff-content apme-diff-add">
          {afterLines.map((line, i) => (
            <span key={i} className="apme-diff-line">
              <span className="apme-diff-linenum">{i + 1}</span>
              {line}
              {"\n"}
            </span>
          ))}
        </pre>
      </div>
    </div>
  );
}

function SessionComplete({
  result,
  scanId,
  tier1,
}: {
  result: SessionResult;
  scanId: string | null;
  tier1: Tier1Result | null;
}) {
  const totalPatches =
    result.patches.length + (tier1?.patches.length ?? 0);
  const remaining = result.remaining_violations.length;

  return (
    <div className="apme-session-complete">
      <div className="apme-complete-icon">&#10003;</div>
      <h2>Session Complete</h2>

      <div className="apme-summary-card" style={{ maxWidth: 600, margin: "16px auto" }}>
        <div className="apme-summary-counts" style={{ justifyContent: "center", width: "100%" }}>
          <div className="apme-count-box">
            <div
              className="apme-count-box-value"
              style={{ color: "var(--apme-green)" }}
            >
              {totalPatches}
            </div>
            <div className="apme-count-box-label">Fixed</div>
          </div>
          <div className="apme-count-box">
            <div
              className="apme-count-box-value"
              style={{
                color:
                  remaining > 0
                    ? "var(--apme-sev-medium)"
                    : "var(--apme-green)",
              }}
            >
              {remaining}
            </div>
            <div className="apme-count-box-label">Remaining</div>
          </div>
        </div>
      </div>

      {result.patches.length > 0 && (
        <details className="apme-options-panel" style={{ maxWidth: 700, margin: "0 auto" }}>
          <summary>Applied Patches ({result.patches.length})</summary>
          {result.patches.map((p, i) => (
            <div key={i} className="apme-diff-block">
              <div className="apme-diff-file">
                <span className="apme-file-name">{p.file}</span>
              </div>
              {p.diff && <pre className="apme-diff-content">{p.diff}</pre>}
            </div>
          ))}
        </details>
      )}

      {remaining > 0 && (
        <details className="apme-options-panel" style={{ maxWidth: 700, margin: "8px auto 0" }}>
          <summary>Remaining Violations ({remaining})</summary>
          <div className="apme-remaining-list">
            {result.remaining_violations.map((v, i) => (
              <div key={i} className="apme-remaining-item">
                <span className="apme-rule-id">{v.rule_id}</span>
                <span className="apme-file-name">{v.file}</span>
                <span>{v.message}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {scanId && (
        <div style={{ marginTop: 16, textAlign: "center" }}>
          <Link to={`/scans/${scanId}`} className="apme-btn-primary" style={{ textDecoration: "none", display: "inline-block" }}>
            View Full Report
          </Link>
        </div>
      )}
    </div>
  );
}
