import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageLayout, PageHeader } from '@ansible/ansible-ui-framework';
import { ViolationStatusBar } from '../components/ViolationStatusBar';
import { severityClass } from '../components/severity';
import { SeverityStatusBar } from '../components/SeverityStatusBar';
import { ViolationOutputToolbar } from '../components/ViolationOutputToolbar';
import { ViolationOutput } from '../components/ViolationOutput';
import { PipelineLogOutput } from '../components/PipelineLogOutput';
import {
  Button,
  ExpandableSection,
  Label,
} from '@patternfly/react-core';
import { deleteActivity, getActivity } from '../services/api';
import { useFeedbackEnabled } from '../hooks/useFeedbackEnabled';
import type { ActivityDetail } from '../types/api';
import { getRuleDescription } from '../data/ruleDescriptions';

function displayType(scanType: string): string {
  if (scanType === 'scan') return 'check';
  if (scanType === 'fix') return 'remediate';
  return scanType;
}

export function ActivityDetailPage() {
  const { activityId } = useParams<{ activityId: string }>();
  const navigate = useNavigate();
  const feedbackEnabled = useFeedbackEnabled();
  const [detail, setDetail] = useState<ActivityDetail | null>(null);
  const [loading, setLoading] = useState(true);

  // Filter state
  const [sevFilters, setSevFilters] = useState<Set<string>>(new Set());
  const [ruleFilters, setRuleFilters] = useState<Set<string>>(new Set());
  const [searchText, setSearchText] = useState('');
  const [resultsOpen, setResultsOpen] = useState(true);

  useEffect(() => {
    if (!activityId) return;
    setLoading(true);
    getActivity(activityId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [activityId]);

  const sevCounts = useMemo(() => {
    if (!detail) return new Map<string, number>();
    const counts = new Map<string, number>();
    for (const v of detail.violations) {
      const cls = severityClass(v.level, v.rule_id);
      counts.set(cls, (counts.get(cls) ?? 0) + 1);
    }
    return counts;
  }, [detail]);

  const uniqueRules = useMemo(() => {
    if (!detail) return [] as string[];
    const set = new Set<string>();
    for (const v of detail.violations) set.add(v.rule_id);
    return Array.from(set).sort();
  }, [detail]);

  const filtered = useMemo(() => {
    if (!detail) return [];
    let violations = detail.violations;
    if (sevFilters.size > 0) {
      violations = violations.filter((v) => sevFilters.has(severityClass(v.level, v.rule_id)));
    }
    if (ruleFilters.size > 0) {
      violations = violations.filter((v) => ruleFilters.has(v.rule_id));
    }
    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      violations = violations.filter((v) =>
        v.message.toLowerCase().includes(q) ||
        v.rule_id.toLowerCase().includes(q) ||
        v.file.toLowerCase().includes(q) ||
        (v.path && v.path.toLowerCase().includes(q))
      );
    }
    return violations;
  }, [detail, sevFilters, ruleFilters, searchText]);

  const patchByFile = useMemo(() => {
    if (!detail) return new Map<string, string>();
    const map = new Map<string, string>();
    for (const p of detail.patches) {
      map.set(p.file, p.diff);
    }
    return map;
  }, [detail]);

  if (loading) return <PageLayout><div style={{ padding: 48, textAlign: 'center', opacity: 0.6 }}>Loading...</div></PageLayout>;
  if (!detail) return <PageLayout><div style={{ padding: 48, textAlign: 'center', opacity: 0.6 }}>Activity not found.</div></PageLayout>;

  const hasFilters = sevFilters.size > 0 || ruleFilters.size > 0 || searchText.length > 0;

  const handleDelete = async () => {
    if (!activityId || !confirm('Delete this activity record? This cannot be undone.')) return;
    try {
      await deleteActivity(activityId);
      navigate('/activity');
    } catch {
      alert('Failed to delete activity record.');
    }
  };

  return (
    <PageLayout>
      <PageHeader
        title={detail.project_path}
        breadcrumbs={[
          { label: 'Activity', to: '/activity' },
          { label: detail.project_path },
        ]}
        description={`${displayType(detail.scan_type)} via ${detail.source} — ${new Date(detail.created_at).toLocaleString()}`}
        headerActions={
          <Button variant="danger" onClick={handleDelete} size="sm">
            Delete
          </Button>
        }
      />

      {/*
        Layout mirrors AAP job output:
        1. Status bar (like JobStatusBar — name + counts)
        2. Severity bar (like HostStatusBar — proportional colored segments)
        3. Toolbar (like JobOutputToolbar — search + filters)
        4. Controls + Output (like PageControls + JobOutputEvents)
        5. Pipeline log (moved below violations)
      */}
      <div className="apme-job-output-section">
        {/* 1. Status bar */}
        <ViolationStatusBar detail={detail} />

        {/* 2. Severity proportional bar */}
        <SeverityStatusBar sevCounts={sevCounts} />

        {/* 3. Toolbar with search + filters */}
        <ViolationOutputToolbar
          searchText={searchText}
          onSearchChange={setSearchText}
          sevFilters={sevFilters}
          ruleFilters={ruleFilters}
          sevCounts={sevCounts}
          uniqueRules={uniqueRules}
          onSevChange={setSevFilters}
          onRuleChange={setRuleFilters}
          filteredCount={filtered.length}
          totalCount={detail.violations.length}
        />

        {/* 4. Violation output (controls + scrollable list) */}
        <ViolationOutput
          violations={filtered}
          patchByFile={patchByFile}
          hasFilters={hasFilters}
          scanType={detail.scan_type}
          getRuleDescription={getRuleDescription}
          onSectionToggle={setResultsOpen}
          scanId={activityId}
          feedbackEnabled={feedbackEnabled}
        />
      </div>

      {/* 5. Pipeline log — same output style, grouped by phase */}
      <PipelineLogOutput logs={detail.logs} expanded={!resultsOpen} />

      <div style={{ padding: '0 24px 24px' }}>
        {/* AI proposals */}
        {detail.proposals.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <h3 style={{ marginBottom: 12 }}>AI Proposals ({detail.proposals.length})</h3>
            <table className="pf-v6-c-table pf-m-compact" role="grid">
              <thead>
                <tr role="row">
                  <th role="columnheader" style={{ width: 90 }}>Rule</th>
                  <th role="columnheader">File</th>
                  <th role="columnheader" style={{ width: 50 }}>Tier</th>
                  <th role="columnheader" style={{ width: 80 }}>Confidence</th>
                  <th role="columnheader" style={{ width: 80 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {detail.proposals.map((p) => (
                  <tr key={p.id} role="row">
                    <td role="cell"><span className="apme-rule-id">{p.rule_id}</span></td>
                    <td role="cell" style={{ fontSize: 13 }}>{p.file}</td>
                    <td role="cell">{p.tier}</td>
                    <td role="cell">{Math.round(p.confidence * 100)}%</td>
                    <td role="cell">
                      <Label color={p.status === 'approved' ? 'green' : p.status === 'rejected' ? 'red' : 'blue'} isCompact>
                        {p.status}
                      </Label>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Diagnostics */}
        {detail.diagnostics_json && (
          <ExpandableSection toggleText="Diagnostics (raw)" style={{ marginTop: 24 }}>
            <pre style={{ padding: 16, fontSize: 12, overflow: 'auto', maxHeight: 400, background: 'var(--pf-t--global--background--color--secondary--default)' }}>
              {(() => {
                try { return JSON.stringify(JSON.parse(detail.diagnostics_json), null, 2); }
                catch { return detail.diagnostics_json; }
              })()}
            </pre>
          </ExpandableSection>
        )}
      </div>
    </PageLayout>
  );
}
