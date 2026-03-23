import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteScan, getScan } from "../services/api";
import type { ScanDetail, ViolationDetail } from "../types/api";
import { getRuleDescription } from "../data/ruleDescriptions";

function groupByFile(violations: ViolationDetail[]): Map<string, ViolationDetail[]> {
  const map = new Map<string, ViolationDetail[]>();
  for (const v of violations) {
    const key = v.file || "(unknown)";
    const arr = map.get(key) ?? [];
    arr.push(v);
    map.set(key, arr);
  }
  return map;
}

function severityClass(level: string, ruleId?: string): string {
  if (ruleId?.startsWith("SEC")) return "critical";
  const l = level.toLowerCase();
  if (l === "fatal") return "critical";
  if (l === "error") return "error";
  if (l === "very_high") return "very-high";
  if (l === "high") return "high";
  if (l === "medium") return "medium";
  if (["warning", "warn"].includes(l)) return "warning";
  if (l === "low") return "low";
  if (["very_low", "info"].includes(l)) return "very-low";
  return "hint";
}

function severityLabel(level: string, ruleId?: string): string {
  if (ruleId?.startsWith("SEC")) return "CRITICAL";
  const l = level.toLowerCase();
  if (l === "fatal") return "FATAL";
  if (l === "error") return "ERROR";
  if (l === "very_high") return "VERY HIGH";
  if (l === "high") return "HIGH";
  if (l === "medium") return "MEDIUM";
  if (["warning", "warn"].includes(l)) return "WARN";
  if (l === "low") return "LOW";
  if (["very_low", "info"].includes(l)) return "VERY LOW";
  return "HINT";
}

function classToLabel(cls: string): string {
  const map: Record<string, string> = {
    critical: "Critical", error: "Error", "very-high": "Very High",
    high: "High", medium: "Medium", warning: "Warning",
    low: "Low", "very-low": "Very Low", hint: "Hint",
  };
  return map[cls] ?? cls;
}

function severityOrder(cls: string): number {
  const order: Record<string, number> = {
    critical: 0, error: 1, "very-high": 2, high: 3,
    medium: 4, warning: 5, low: 6, "very-low": 7, hint: 8,
  };
  return order[cls] ?? 9;
}

function tierLabel(rc: number): string {
  if (rc === 1) return "Auto-Fix";
  if (rc === 2) return "AI";
  if (rc === 3) return "Manual";
  return "";
}

const SEVERITY_ORDER = ["critical", "error", "very-high", "high", "medium", "warning", "low", "very-low", "hint"];

const SEV_CSS_VAR: Record<string, string> = {
  critical: "var(--apme-sev-critical)", error: "var(--apme-sev-error)",
  "very-high": "var(--apme-sev-very-high)", high: "var(--apme-sev-high)",
  medium: "var(--apme-sev-medium)", warning: "var(--apme-sev-warning)",
  low: "var(--apme-sev-low)", "very-low": "var(--apme-sev-very-low)",
  hint: "var(--apme-sev-hint)",
};

function FilterIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M1.5 2h13l-5 6v5l-3 1.5V8z" />
    </svg>
  );
}

interface FilterPopoverProps {
  sevFilters: Set<string>;
  ruleFilters: Set<string>;
  sevCounts: Map<string, number>;
  uniqueRules: string[];
  onSevChange: (next: Set<string>) => void;
  onRuleChange: (next: Set<string>) => void;
}

function FilterPopover({ sevFilters, ruleFilters, sevCounts, uniqueRules, onSevChange, onRuleChange }: FilterPopoverProps) {
  const [draftSev, setDraftSev] = useState(new Set(sevFilters));
  const [draftRule, setDraftRule] = useState(new Set(ruleFilters));

  const toggleDraftSev = (cls: string) => {
    setDraftSev((prev) => {
      const n = new Set(prev);
      if (n.has(cls)) n.delete(cls); else n.add(cls);
      return n;
    });
  };

  const toggleDraftRule = (rule: string) => {
    setDraftRule((prev) => {
      const n = new Set(prev);
      if (n.has(rule)) n.delete(rule); else n.add(rule);
      return n;
    });
  };

  const apply = () => {
    onSevChange(draftSev);
    onRuleChange(draftRule);
  };

  const clearAll = () => {
    setDraftSev(new Set());
    setDraftRule(new Set());
    onSevChange(new Set());
    onRuleChange(new Set());
  };

  return (
    <div className="apme-filter-popover" onClick={(e) => e.stopPropagation()}>
      <div className="apme-filter-scroll">
        <h4>Severity</h4>
        {SEVERITY_ORDER.map((cls) => {
          const count = sevCounts.get(cls) ?? 0;
          if (count === 0) return null;
          return (
            <label key={cls} className="apme-filter-option">
              <input type="checkbox" checked={draftSev.has(cls)} onChange={() => toggleDraftSev(cls)} />
              <span className="apme-sev-dot" style={{ background: SEV_CSS_VAR[cls] }} />
              <span style={{ flex: 1 }}>{classToLabel(cls)}</span>
              <span style={{ color: "var(--apme-text-muted)", fontSize: 12 }}>{count}</span>
            </label>
          );
        })}

        {uniqueRules.length > 0 && (
          <>
            <h4 style={{ marginTop: 12 }}>Rule</h4>
            {uniqueRules.map((r) => (
              <label key={r} className="apme-filter-option" title={getRuleDescription(r) || r}>
                <input type="checkbox" checked={draftRule.has(r)} onChange={() => toggleDraftRule(r)} />
                <span style={{ fontFamily: "var(--pf-v5-global--FontFamily--monospace, monospace)", fontSize: 12 }}>{r}</span>
              </label>
            ))}
          </>
        )}
      </div>

      <div className="apme-filter-actions">
        <button className="apme-btn apme-btn-secondary" onClick={clearAll} style={{ fontSize: 12, padding: "4px 10px" }}>
          Clear
        </button>
        <button className="apme-btn apme-btn-primary" onClick={apply} style={{ fontSize: 12, padding: "4px 14px", marginTop: 0 }}>
          Apply
        </button>
      </div>
    </div>
  );
}

export function ScanDetailPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const navigate = useNavigate();
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sevFilters, setSevFilters] = useState<Set<string>>(new Set());
  const [ruleFilters, setRuleFilters] = useState<Set<string>>(new Set());
  const [logsCollapsed, setLogsCollapsed] = useState(true);
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!scanId) return;
    setLoading(true);
    getScan(scanId)
      .then(setScan)
      .catch(() => setScan(null))
      .finally(() => setLoading(false));
  }, [scanId]);

  useEffect(() => {
    if (!filterOpen) return;
    const handler = (e: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) setFilterOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [filterOpen]);

  const sevCounts = useMemo(() => {
    if (!scan) return new Map<string, number>();
    const counts = new Map<string, number>();
    for (const v of scan.violations) {
      const cls = severityClass(v.level, v.rule_id);
      counts.set(cls, (counts.get(cls) ?? 0) + 1);
    }
    return counts;
  }, [scan]);

  const uniqueRules = useMemo(() => {
    if (!scan) return [] as string[];
    const set = new Set<string>();
    for (const v of scan.violations) set.add(v.rule_id);
    return Array.from(set).sort();
  }, [scan]);

  const filtered = useMemo(() => {
    if (!scan) return [];
    let violations = scan.violations;
    if (sevFilters.size > 0) {
      violations = violations.filter((v) => sevFilters.has(severityClass(v.level, v.rule_id)));
    }
    if (ruleFilters.size > 0) {
      violations = violations.filter((v) => ruleFilters.has(v.rule_id));
    }
    return violations;
  }, [scan, sevFilters, ruleFilters]);

  const groups = useMemo(() => groupByFile(filtered), [filtered]);

  if (loading) return <div className="apme-empty">Loading...</div>;
  if (!scan) return <div className="apme-empty">Scan not found.</div>;

  const expandAll = () => setExpanded(new Set(groups.keys()));
  const collapseAll = () => setExpanded(new Set());
  const hasFilters = sevFilters.size > 0 || ruleFilters.size > 0;
  const clearFilters = () => { setSevFilters(new Set()); setRuleFilters(new Set()); };
  const activeFilterCount = sevFilters.size + ruleFilters.size;

  const handleDelete = async () => {
    if (!scanId || !confirm("Delete this scan? This cannot be undone.")) return;
    try {
      await deleteScan(scanId);
      navigate("/scans");
    } catch {
      alert("Failed to delete scan.");
    }
  };

  return (
    <>
      <nav className="apme-breadcrumb">
        <Link to="/scans">All Scans</Link>
        <span className="apme-breadcrumb-sep">/</span>
        <span>{scan.project_path}</span>
      </nav>

      <header className="apme-page-header">
        <div>
          <h1 className="apme-page-title" style={{ fontFamily: "var(--pf-v5-global--FontFamily--monospace, monospace)" }}>
            {scan.project_path}
          </h1>
          <p style={{ color: "var(--apme-text-muted)", fontSize: 14, margin: 0 }}>
            <span className={`apme-badge ${scan.scan_type === "fix" ? "passed" : "running"}`} style={{ marginRight: 8 }}>
              {scan.scan_type}
            </span>
            <span className="apme-badge" style={{ marginRight: 8, background: "var(--apme-bg-tertiary)", color: "var(--apme-text-secondary)" }}>
              {scan.source}
            </span>
            {new Date(scan.created_at).toLocaleString()}
          </p>
        </div>
        <button className="apme-btn apme-btn-secondary" onClick={handleDelete} style={{ fontSize: 12, color: "var(--apme-sev-critical)" }}>
          Delete Scan
        </button>
      </header>

      {/* Summary card — violations total + severity breakdown + remediation counts */}
      <div className="apme-summary-card" style={{ flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className={`apme-status-icon ${scan.total_violations > 0 ? "failed" : "passed"}`}>
            {scan.total_violations > 0 ? "\u2717" : "\u2713"}
          </div>
          <span style={{ fontSize: 20, fontWeight: 600, color: scan.total_violations > 0 ? "var(--apme-sev-critical)" : "var(--apme-green)" }}>
            {scan.total_violations > 0 ? `${scan.total_violations} VIOLATIONS` : "CLEAN"}
          </span>
        </div>

        {/* Severity breakdown inside the card */}
        {scan.violations.length > 0 && (
          <>
            <div className="apme-summary-divider" />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              {SEVERITY_ORDER.map((cls) => {
                const count = sevCounts.get(cls) ?? 0;
                if (count === 0) return null;
                return (
                  <span key={cls} style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 13 }}>
                    <span className="apme-sev-dot" style={{ background: SEV_CSS_VAR[cls] }} />
                    <strong>{count}</strong>
                    <span style={{ color: "var(--apme-text-muted)" }}>{classToLabel(cls)}</span>
                  </span>
                );
              })}
            </div>
          </>
        )}

        <div className="apme-summary-divider" />
        <div className="apme-summary-counts">
          {scan.scan_type === "fix" && scan.fixed_count > 0 && (
            <div className="apme-count-box">
              <div className="apme-count-box-value" style={{ color: "var(--apme-green)" }}>{scan.fixed_count}</div>
              <div className="apme-count-box-label">Fixed</div>
            </div>
          )}
          <div className="apme-count-box">
            <div className="apme-count-box-value" style={{ color: "var(--apme-green)" }}>{scan.auto_fixable}</div>
            <div className="apme-count-box-label">Auto-Fix</div>
          </div>
          <div className="apme-count-box">
            <div className="apme-count-box-value" style={{ color: "var(--apme-sev-medium)" }}>{scan.ai_candidate}</div>
            <div className="apme-count-box-label">AI</div>
          </div>
          <div className="apme-count-box">
            <div className="apme-count-box-value" style={{ color: "var(--apme-sev-error)" }}>{scan.manual_review}</div>
            <div className="apme-count-box-label">Manual</div>
          </div>
        </div>
      </div>

      {/* Filter button + active filter tags */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <div className="apme-filter-anchor" ref={filterRef}>
          <button
            className="apme-btn apme-btn-secondary"
            onClick={() => setFilterOpen((p) => !p)}
            style={{ fontSize: 13, padding: "6px 14px", display: "flex", alignItems: "center", gap: 6 }}
          >
            <FilterIcon />
            Filter
            {activeFilterCount > 0 && (
              <span style={{
                background: "var(--apme-accent)", color: "#fff", borderRadius: 10,
                padding: "1px 7px", fontSize: 11, fontWeight: 600, marginLeft: 2,
              }}>
                {activeFilterCount}
              </span>
            )}
          </button>
          {filterOpen && (
            <FilterPopover
              sevFilters={sevFilters}
              ruleFilters={ruleFilters}
              sevCounts={sevCounts}
              uniqueRules={uniqueRules}
              onSevChange={(s) => { setSevFilters(s); setFilterOpen(false); }}
              onRuleChange={(r) => { setRuleFilters(r); setFilterOpen(false); }}
            />
          )}
        </div>

        {hasFilters && (
          <>
            {Array.from(sevFilters).map((cls) => (
              <span key={cls} className={`apme-severity ${cls}`} style={{ fontSize: 11, padding: "2px 8px", cursor: "pointer" }}
                onClick={() => setSevFilters((p) => { const n = new Set(p); n.delete(cls); return n; })}
                title="Click to remove"
              >
                {classToLabel(cls)} &times;
              </span>
            ))}
            {Array.from(ruleFilters).map((r) => (
              <span key={r} style={{
                fontSize: 11, padding: "2px 8px", borderRadius: 4, cursor: "pointer",
                background: "var(--apme-bg-tertiary)", border: "1px solid var(--apme-border)",
                fontFamily: "var(--pf-v5-global--FontFamily--monospace, monospace)",
              }}
                onClick={() => setRuleFilters((p) => { const n = new Set(p); n.delete(r); return n; })}
                title="Click to remove"
              >
                {r} &times;
              </span>
            ))}
            <button className="apme-btn apme-btn-secondary" onClick={clearFilters} style={{ fontSize: 11, padding: "3px 8px" }}>
              Clear All
            </button>
            <span style={{ color: "var(--apme-text-muted)", fontSize: 13 }}>
              {filtered.length} of {scan.violations.length}
            </span>
          </>
        )}
      </div>

      {/* Pipeline logs — collapsible */}
      {scan.logs.length > 0 && (
        <div className="apme-table-container" style={{ marginBottom: 24 }}>
          <button
            type="button"
            style={{ width: "100%", background: "none", border: "none", color: "inherit", padding: "12px 20px", cursor: "pointer", display: "flex", alignItems: "center", gap: 8, borderBottom: logsCollapsed ? "none" : "1px solid var(--apme-border)" }}
            onClick={() => setLogsCollapsed((p) => !p)}
            aria-expanded={!logsCollapsed}
          >
            <span style={{ color: "var(--apme-text-dimmed)" }}>{logsCollapsed ? "\u25B6" : "\u25BC"}</span>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Pipeline Log ({scan.logs.length})</span>
          </button>
          {!logsCollapsed && (
            <table className="apme-data-table">
              <thead>
                <tr><th>Phase</th><th>Message</th></tr>
              </thead>
              <tbody>
                {scan.logs.map((lg) => (
                  <tr key={lg.id}>
                    <td><span className="apme-badge running">{lg.phase}</span></td>
                    <td>{lg.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Violations by file */}
      <div className="apme-violations-section">
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--apme-border)", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 16, fontWeight: 600, marginRight: "auto" }}>
            Violations by File ({filtered.length})
          </span>
          <button className="apme-btn apme-btn-secondary" onClick={expandAll} style={{ fontSize: 12, padding: "4px 10px" }}>
            Expand All
          </button>
          <button className="apme-btn apme-btn-secondary" onClick={collapseAll} style={{ fontSize: 12, padding: "4px 10px" }}>
            Collapse All
          </button>
        </div>

        {groups.size === 0 ? (
          <div className="apme-empty">No violations{hasFilters ? " matching filters" : " found"}.</div>
        ) : (
          Array.from(groups.entries()).map(([file, violations]) => (
            <div className="apme-file-group" key={file}>
              <div className="apme-file-header" onClick={() => {
                setExpanded((prev) => {
                  const next = new Set(prev);
                  if (next.has(file)) next.delete(file);
                  else next.add(file);
                  return next;
                });
              }}>
                <span style={{ color: "var(--apme-text-dimmed)" }}>{expanded.has(file) ? "\u25BC" : "\u25B6"}</span>
                <span className="apme-file-name">{file}</span>
                <span className="apme-file-count">{violations.length} issues</span>
              </div>
              {expanded.has(file) &&
                violations
                  .sort((a: ViolationDetail, b: ViolationDetail) =>
                    severityOrder(severityClass(a.level, a.rule_id)) - severityOrder(severityClass(b.level, b.rule_id)),
                  )
                  .map((v: ViolationDetail) => (
                  <div className="apme-violation-item" key={v.id}>
                    <span className={`apme-severity ${severityClass(v.level, v.rule_id)}`}>
                      {severityLabel(v.level, v.rule_id)}
                    </span>
                    <span className="apme-rule-id" title={getRuleDescription(v.rule_id) || v.rule_id}>{v.rule_id}</span>
                    <span className="apme-badge running" style={{ fontSize: 10, visibility: v.remediation_class > 0 ? "visible" : "hidden" }}>
                      {tierLabel(v.remediation_class) || "\u00A0"}
                    </span>
                    <span className="apme-line-number" style={{ visibility: v.line != null ? "visible" : "hidden" }}>
                      {v.line != null ? `Line ${v.line}` : "\u00A0"}
                    </span>
                    <div className="apme-violation-message">
                      {v.message}
                      {v.path && <span style={{ display: "block", fontSize: 11, color: "var(--apme-text-dimmed)", fontFamily: "var(--pf-v5-global--FontFamily--monospace, monospace)" }}>{v.path}</span>}
                    </div>
                  </div>
                ))}
            </div>
          ))
        )}
      </div>

      {/* AI proposals — if any exist */}
      {scan.proposals.length > 0 && (
        <div className="apme-table-container" style={{ marginTop: 24 }}>
          <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--apme-border)" }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>AI Proposals ({scan.proposals.length})</span>
          </div>
          <table className="apme-data-table">
            <thead>
              <tr>
                <th style={{ width: 90 }}>Rule</th>
                <th>File</th>
                <th style={{ width: 50 }}>Tier</th>
                <th style={{ width: 80 }}>Confidence</th>
                <th style={{ width: 80 }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {scan.proposals.map((p) => (
                <tr key={p.id}>
                  <td><span className="apme-rule-id">{p.rule_id}</span></td>
                  <td style={{ fontSize: 13 }}>{p.file}</td>
                  <td>{p.tier}</td>
                  <td>{Math.round(p.confidence * 100)}%</td>
                  <td>
                    <span className={`apme-badge ${p.status === "approved" ? "passed" : p.status === "rejected" ? "failed" : "running"}`}>
                      {p.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Diagnostics JSON — collapsible raw data */}
      {scan.diagnostics_json && (
        <details className="apme-table-container" style={{ marginTop: 24 }}>
          <summary style={{ padding: "12px 20px", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
            Diagnostics (raw)
          </summary>
          <pre style={{ padding: "12px 20px", fontSize: 12, overflow: "auto", maxHeight: 400, margin: 0, color: "var(--apme-text-secondary)" }}>
            {(() => {
              try { return JSON.stringify(JSON.parse(scan.diagnostics_json), null, 2); }
              catch { return scan.diagnostics_json; }
            })()}
          </pre>
        </details>
      )}
    </>
  );
}
