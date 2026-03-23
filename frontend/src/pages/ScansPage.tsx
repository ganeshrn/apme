import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PageLayout, PageHeader } from '@ansible/ansible-ui-framework';
import { Pagination } from '@patternfly/react-core';
import { listScans } from '../services/api';
import type { ScanSummary } from '../types/api';
import { StatusBadge } from '../components/StatusBadge';
import { timeAgo } from '../services/format';

const PAGE_SIZE = 20;

export function ScansPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sessionFilter = searchParams.get('session_id') ?? undefined;
  const [scans, setScans] = useState<ScanSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setPage(1);
  }, [sessionFilter]);

  useEffect(() => {
    setLoading(true);
    const offset = (page - 1) * PAGE_SIZE;
    listScans(PAGE_SIZE, offset, sessionFilter)
      .then((data) => {
        setScans(data.items);
        setTotal(data.total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page, sessionFilter]);

  return (
    <PageLayout>
      <PageHeader title="All Scans" />

      {loading ? (
        <div style={{ padding: 48, textAlign: 'center', opacity: 0.6 }}>Loading...</div>
      ) : scans.length === 0 ? (
        <div style={{ padding: 48, textAlign: 'center', opacity: 0.6 }}>No scans recorded.</div>
      ) : (
        <div style={{ padding: '0 24px 24px' }}>
          <table className="pf-v6-c-table pf-m-compact pf-m-grid-md" role="grid">
            <thead>
              <tr role="row">
                <th role="columnheader">Project</th>
                <th role="columnheader">Source</th>
                <th role="columnheader">Type</th>
                <th role="columnheader">Status</th>
                <th role="columnheader">Violations</th>
                <th role="columnheader">Auto-Fix</th>
                <th role="columnheader">AI</th>
                <th role="columnheader">Manual</th>
                <th role="columnheader">Time</th>
              </tr>
            </thead>
            <tbody>
              {scans.map((scan) => (
                <tr
                  key={scan.scan_id}
                  role="row"
                  tabIndex={0}
                  onClick={() => navigate(`/scans/${scan.scan_id}`)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/scans/${scan.scan_id}`); } }}
                  style={{ cursor: 'pointer' }}
                >
                  <td role="cell" style={{ fontFamily: 'var(--pf-t--global--font--family--mono)' }}>
                    {scan.project_path}
                  </td>
                  <td role="cell">
                    <span className="apme-badge running">{scan.source}</span>
                  </td>
                  <td role="cell">
                    <span className={`apme-badge ${scan.scan_type === 'fix' ? 'passed' : 'running'}`}>
                      {scan.scan_type}
                    </span>
                  </td>
                  <td role="cell">
                    <StatusBadge violations={scan.total_violations} scanType={scan.scan_type} />
                  </td>
                  <td role="cell">{scan.total_violations}</td>
                  <td role="cell"><span className="apme-count-success">{scan.auto_fixable ?? ''}</span></td>
                  <td role="cell">{scan.ai_candidate ?? ''}</td>
                  <td role="cell"><span className="apme-count-error">{scan.manual_review ?? ''}</span></td>
                  <td role="cell" style={{ opacity: 0.7 }}>{timeAgo(scan.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {total > PAGE_SIZE && (
            <Pagination
              itemCount={total}
              perPage={PAGE_SIZE}
              page={page}
              onSetPage={(_e, p) => setPage(p)}
              style={{ marginTop: 16 }}
            />
          )}
        </div>
      )}
    </PageLayout>
  );
}
