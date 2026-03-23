import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listScans, listSessions } from "../services/api";
import type { ScanSummary } from "../types/api";
import { StatusBadge } from "../components/StatusBadge";
import { timeAgo } from "../services/format";

function deduplicateBySession(scans: ScanSummary[]): ScanSummary[] {
  const seen = new Map<string, ScanSummary>();
  for (const scan of scans) {
    if (!seen.has(scan.session_id)) {
      seen.set(scan.session_id, scan);
    }
  }
  return Array.from(seen.values());
}

export function DashboardPage() {
  const navigate = useNavigate();
  const [scans, setScans] = useState<ScanSummary[]>([]);
  const [totalScansCount, setTotalScansCount] = useState(0);
  const [totalSessionsCount, setTotalSessionsCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([listScans(50, 0), listSessions(50, 0)])
      .then(([scanData, sessionData]) => {
        setScans(scanData.items);
        setTotalScansCount(scanData.total);
        setTotalSessionsCount(sessionData.total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const latestPerProject = deduplicateBySession(scans);
  const totalViolations = latestPerProject.reduce((s, sc) => s + sc.total_violations, 0);
  const totalAutoFix = latestPerProject.reduce((s, sc) => s + sc.auto_fixable, 0);
  const totalAi = latestPerProject.reduce((s, sc) => s + sc.ai_candidate, 0);
  const totalManual = latestPerProject.reduce((s, sc) => s + sc.manual_review, 0);

  const recentScans = scans.slice(0, 10);

  return (
    <>
      <header className="apme-page-header">
        <h1 className="apme-page-title">Dashboard</h1>
      </header>

      <div className="apme-cards-grid">
        <div className="apme-metric-card">
          <div className="apme-metric-value">{totalSessionsCount}</div>
          <div className="apme-metric-label">Projects</div>
        </div>
        <div className="apme-metric-card">
          <div className="apme-metric-value warning">{totalViolations}</div>
          <div className="apme-metric-label">Total Violations</div>
        </div>
        <div className="apme-metric-card">
          <div className="apme-metric-value success">{totalAutoFix}</div>
          <div className="apme-metric-label">Auto-Fixable</div>
        </div>
        <div className="apme-metric-card">
          <div className="apme-metric-value">{totalAi}</div>
          <div className="apme-metric-label">AI Candidates</div>
        </div>
        <div className="apme-metric-card">
          <div className="apme-metric-value error">{totalManual}</div>
          <div className="apme-metric-label">Manual Review</div>
        </div>
        <div className="apme-metric-card">
          <div className="apme-metric-value">{totalScansCount}</div>
          <div className="apme-metric-label">Total Scans</div>
        </div>
      </div>

      <div className="apme-section-header">
        <h2 className="apme-section-title">Recent Scans</h2>
        <Link to="/scans" className="apme-link">View all</Link>
      </div>

      {loading ? (
        <div className="apme-empty">Loading...</div>
      ) : recentScans.length === 0 ? (
        <div className="apme-empty">No scans recorded yet.</div>
      ) : (
        <div className="apme-table-container">
          <table className="apme-data-table">
            <thead>
              <tr>
                <th>Project</th>
                <th>Type</th>
                <th>Status</th>
                <th>Violations</th>
                <th>Auto-Fix</th>
                <th>AI</th>
                <th>Manual</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {recentScans.map((scan) => (
                <tr key={scan.scan_id} onClick={() => navigate(`/scans/${scan.scan_id}`)} style={{ cursor: "pointer" }}>
                  <td className="apme-target-path">{scan.project_path}</td>
                  <td>
                    <span className={`apme-badge ${scan.scan_type === "fix" ? "passed" : "running"}`}>
                      {scan.scan_type}
                    </span>
                  </td>
                  <td><StatusBadge violations={scan.total_violations} scanType={scan.scan_type} /></td>
                  <td>{scan.total_violations}</td>
                  <td><span className="apme-count-success">{scan.auto_fixable || ""}</span></td>
                  <td>{scan.ai_candidate || ""}</td>
                  <td><span className="apme-count-error">{scan.manual_review || ""}</span></td>
                  <td className="apme-time-ago">{timeAgo(scan.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
