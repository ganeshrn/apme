import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageLayout, PageHeader } from '@ansible/ansible-ui-framework';
import { ViolationStatusBar } from '../components/ViolationStatusBar';
import { severityClass } from '../components/severity';
import { SeverityStatusBar } from '../components/SeverityStatusBar';
import { ViolationOutputToolbar } from '../components/ViolationOutputToolbar';
import { ViolationOutput } from '../components/ViolationOutput';
import { PipelineLogOutput } from '../components/PipelineLogOutput';
import { DependencyHealthOutput, isDepHealthViolation } from '../components/DependencyHealthOutput';
import {
  Alert,
  AlertActionCloseButton,
  Button,
  ExpandableSection,
  Flex,
  FlexItem,
  Label,
} from '@patternfly/react-core';
import { ExternalLinkAltIcon } from '@patternfly/react-icons';
import { createPullRequest, deleteActivity, getActivity } from '../services/api';
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

  const [sevFilters, setSevFilters] = useState<Set<string>>(new Set());
  const [ruleFilters, setRuleFilters] = useState<Set<string>>(new Set());
  const [searchText, setSearchText] = useState('');
  const [resultsOpen, setResultsOpen] = useState(true);
  const [prCreating, setPrCreating] = useState(false);
  const [prError, setPrError] = useState<string | null>(null);

  useEffect(() => {
    if (!activityId) return;
    setLoading(true);
    getActivity(activityId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [activityId]);

  const projectViolations = useMemo(() => {
    if (!detail) return [];
    return detail.violations.filter((v) => !isDepHealthViolation(v));
  }, [detail]);

  const depHealthCount = useMemo(() => {
    if (!detail) return 0;
    return detail.violations.filter(isDepHealthViolation).length;
  }, [detail]);

  const sevCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const v of projectViolations) {
      const cls = severityClass(v.level, v.rule_id);
      counts.set(cls, (counts.get(cls) ?? 0) + 1);
    }
    return counts;
  }, [projectViolations]);

  const uniqueRules = useMemo(() => {
    const set = new Set<string>();
    for (const v of projectViolations) set.add(v.rule_id);
    return Array.from(set).sort();
  }, [projectViolations]);

  const filtered = useMemo(() => {
    let violations = projectViolations;
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
  }, [projectViolations, sevFilters, ruleFilters, searchText]);

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

  const handleCreatePR = async () => {
    if (!activityId) return;
    setPrCreating(true);
    setPrError(null);
    try {
      const result = await createPullRequest(activityId);
      setDetail((prev) => prev ? { ...prev, pr_url: result.pr_url } : prev);
    } catch (err) {
      setPrError(err instanceof Error ? err.message : 'Failed to create pull request');
    } finally {
      setPrCreating(false);
    }
  };

  const isRemediate = detail.scan_type === 'fix' || detail.scan_type === 'remediate';
  const canCreatePR = isRemediate && detail.patches.length > 0 && !detail.pr_url;

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
          <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }}>
            {detail.pr_url && (
              <FlexItem>
                <Button
                  variant="link"
                  component="a"
                  href={detail.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  icon={<ExternalLinkAltIcon />}
                  iconPosition="end"
                  size="sm"
                >
                  View PR
                </Button>
              </FlexItem>
            )}
            {canCreatePR && (
              <FlexItem>
                <Button
                  variant="secondary"
                  onClick={handleCreatePR}
                  isLoading={prCreating}
                  isDisabled={prCreating}
                  size="sm"
                >
                  {prCreating ? 'Creating PR...' : 'Create PR'}
                </Button>
              </FlexItem>
            )}
            <FlexItem>
              <Button variant="danger" onClick={handleDelete} size="sm">
                Delete
              </Button>
            </FlexItem>
          </Flex>
        }
      />

      {prError && (
        <div style={{ padding: '16px 24px 0' }}>
          <Alert
            variant="danger"
            isInline
            title="Pull request creation failed"
            actionClose={<AlertActionCloseButton onClose={() => setPrError(null)} />}
          >
            {prError}
          </Alert>
        </div>
      )}

      {/* Unified layout — all panels share viewport height */}
      <div className="apme-activity-layout">
        {/* Status bar + severity bar (fixed height, always visible) */}
        <ViolationStatusBar
          detail={detail}
          depHealthCount={depHealthCount}
        />
        <SeverityStatusBar sevCounts={sevCounts} />
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
          totalCount={projectViolations.length}
        />

        {/* Results panel */}
        <div className={`apme-output-panel ${resultsOpen ? 'apme-panel-open' : 'apme-panel-closed'}`}>
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

        {/* Dependencies panel */}
        <DependencyHealthOutput violations={detail.violations} />

        {/* Pipeline log panel */}
        <PipelineLogOutput logs={detail.logs} />
      </div>

      <div style={{ padding: '16px 24px 24px' }}>
        {detail.proposals.length > 0 && (
          <div style={{ marginTop: 8 }}>
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

        {detail.diagnostics_json && (
          <ExpandableSection toggleText="Diagnostics (raw)" style={{ marginTop: 16 }}>
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
