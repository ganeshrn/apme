import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { PageLayout, PageHeader } from '@ansible/ansible-ui-framework';
import { severityClass, severityLabel, severityOrder, SEVERITY_LABELS, bareRuleId, healthColor } from '../components/severity';
import {
  Badge,
  Button,
  Card,
  CardBody,
  Flex,
  FlexItem,
  Label,
  Split,
  SplitItem,
  Tab,
  Tabs,
  TabTitleText,
  TextInput,
} from '@patternfly/react-core';
import {
  ExclamationCircleIcon,
  ExclamationTriangleIcon,
  ShieldAltIcon,
} from '@patternfly/react-icons';
import { createPullRequest, deleteProject, getProject, getProjectDependencies, getProjectDepHealth, getProjectGraph, getProjectSbom, getProjectTrend, listProjectActivity, listProjectViolations, updateProject } from '../services/api';
import type { GraphData } from '../services/api';
import type { ActivitySummary, DepHealthSummary, ProjectDependencies, ProjectDetail, TrendPoint, ViolationDetail } from '../types/api';
import { GraphVisualization } from '../components/GraphVisualization';
import type { OperationStatus, OperationProgress, OperationProposal, OperationResult } from '../types/operation';
import { StatusBadge } from '../components/StatusBadge';
import { CheckOptionsForm } from '../components/CheckOptionsForm';
import { OperationProgressPanel } from '../components/OperationProgressPanel';
import { ProposalReviewPanel } from '../components/ProposalReviewPanel';
import { OperationResultCard } from '../components/OperationResultCard';
import { TrendChart } from '../components/TrendChart';
import { timeAgo } from '../services/format';
import { useFeedbackEnabled } from '../hooks/useFeedbackEnabled';
import { useProjectOperation, type ProjectOperationOptions } from '../hooks/useProjectOperation';
import { AI_MODEL_STORAGE_KEY } from './SettingsPage';

function mapProjectStatus(s: string): OperationStatus {
  return s as OperationStatus;
}

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [scans, setScans] = useState<ActivitySummary[]>([]);
  const [violations, setViolations] = useState<ViolationDetail[]>([]);
  const [dependencies, setDependencies] = useState<ProjectDependencies | null>(null);
  const [depHealth, setDepHealth] = useState<DepHealthSummary | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const tabParam = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState(
    tabParam === 'settings' ? 5 : tabParam === 'visualize' ? 4 : tabParam === 'dependencies' ? 3 : 0
  );

  const [ansibleVersion, setAnsibleVersion] = useState('');
  const [collections, setCollections] = useState('');
  const [enableAi, setEnableAi] = useState(true);

  const feedbackEnabled = useFeedbackEnabled();
  const {
    status: rawStatus,
    progress: rawProgress,
    scanId: opScanId,
    proposals: rawProposals,
    result: rawResult,
    error: opError,
    isRemediate: opIsRemediate,
    startOperation,
    approve: opApprove,
    cancel: opCancel,
    reset: opReset,
  } = useProjectOperation(projectId || '');

  const opStatus = mapProjectStatus(rawStatus);
  const opProgress: OperationProgress[] = rawProgress.map((p) => ({
    phase: p.phase,
    message: p.message,
    timestamp: p.timestamp,
    progress: p.progress,
    level: p.level,
  }));
  const opProposals: OperationProposal[] = rawProposals.map((p) => ({
    id: p.id,
    rule_id: p.rule_id,
    file: p.file,
    tier: p.tier,
    confidence: p.confidence,
    explanation: p.explanation,
    diff_hunk: p.diff_hunk,
    status: p.status,
    suggestion: p.suggestion,
    line_start: p.line_start,
  }));
  const opResult: OperationResult | null = rawResult ? {
    total_violations: rawResult.total_violations,
    fixable: rawResult.fixable,
    ai_candidate: rawResult.ai_candidate,
    ai_proposed: rawResult.ai_proposed ?? 0,
    ai_declined: rawResult.ai_declined ?? 0,
    ai_accepted: rawResult.ai_accepted ?? 0,
    manual_review: rawResult.manual_review,
    remediated_count: rawResult.remediated_count,
  } : null;

  const fetchData = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setScans([]);
    setViolations([]);
    setDependencies(null);
    setDepHealth(null);
    setTrend([]);
    try {
      const proj = await getProject(projectId);
      setProject(proj);
      const [scanResult, violResult, depsResult, trendResult, healthResult] = await Promise.allSettled([
        listProjectActivity(projectId, 20, 0),
        listProjectViolations(projectId, 100, 0),
        getProjectDependencies(projectId),
        getProjectTrend(projectId),
        getProjectDepHealth(projectId),
      ]);
      if (scanResult.status === 'fulfilled') setScans(scanResult.value.items);
      if (violResult.status === 'fulfilled') setViolations(violResult.value);
      if (depsResult.status === 'fulfilled') setDependencies(depsResult.value);
      if (trendResult.status === 'fulfilled') setTrend(trendResult.value);
      if (healthResult.status === 'fulfilled') setDepHealth(healthResult.value);
    } catch {
      setProject(null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useEffect(() => {
    if (opStatus === 'complete') fetchData();
  }, [opStatus, fetchData]);

  useEffect(() => {
    if (activeTab === 4 && projectId && !graphData && !graphLoading) {
      setGraphLoading(true);
      getProjectGraph(projectId).then(setGraphData).catch(() => setGraphData(null)).finally(() => setGraphLoading(false));
    }
  }, [activeTab, projectId, graphData, graphLoading]);

  const handleScan = useCallback((remediate: boolean) => {
    const colls = collections.split(',').map((c) => c.trim()).filter(Boolean);
    const opts: ProjectOperationOptions = {
      remediate,
      ansible_version: ansibleVersion || undefined,
      collection_specs: colls.length ? colls : undefined,
      enable_ai: enableAi,
      ai_model: enableAi ? (localStorage.getItem(AI_MODEL_STORAGE_KEY) ?? undefined) : undefined,
    };
    setActiveTab(0);
    startOperation(opts);
  }, [ansibleVersion, collections, enableAi, startOperation]);

  useEffect(() => {
    if ((searchParams.get('action') === 'check' || searchParams.get('action') === 'scan') && project && rawStatus === 'idle') {
      setSearchParams({}, { replace: true });
      handleScan(false);
    }
  }, [searchParams, project, rawStatus, setSearchParams, handleScan]);

  const handleDelete = useCallback(async () => {
    if (!projectId) return;
    if (!window.confirm('Delete this project and all its activity history?')) return;
    await deleteProject(projectId);
    navigate('/projects');
  }, [projectId, navigate]);

  const [editName, setEditName] = useState('');
  const [editUrl, setEditUrl] = useState('');
  const [editBranch, setEditBranch] = useState('');
  const [editScmToken, setEditScmToken] = useState('');
  const [scmTokenDirty, setScmTokenDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [prCreating, setPrCreating] = useState(false);
  const [prUrl, setPrUrl] = useState<string | null>(null);
  const [prError, setPrError] = useState<string | null>(null);

  useEffect(() => {
    if (project) {
      setEditName(project.name);
      setEditUrl(project.repo_url);
      setEditBranch(project.branch);
      setEditScmToken('');
      setScmTokenDirty(false);
    }
  }, [project]);

  const handleSave = useCallback(async () => {
    if (!projectId || !project) return;
    setSaving(true);
    try {
      const updates: Record<string, string> = {};
      if (editName !== project.name) updates.name = editName;
      if (editUrl !== project.repo_url) updates.repo_url = editUrl;
      if (editBranch !== project.branch) updates.branch = editBranch;
      if (scmTokenDirty) updates.scm_token = editScmToken.trim();
      if (Object.keys(updates).length > 0) {
        await updateProject(projectId, updates);
        fetchData();
      }
    } finally {
      setSaving(false);
    }
  }, [projectId, project, editName, editUrl, editBranch, editScmToken, scmTokenDirty, fetchData]);

  const handleCreatePR = useCallback(async () => {
    if (!opScanId) return;
    setPrCreating(true);
    setPrError(null);
    try {
      const result = await createPullRequest(opScanId);
      setPrUrl(result.pr_url);
    } catch (err) {
      setPrError(err instanceof Error ? err.message : 'Failed to create pull request');
    } finally {
      setPrCreating(false);
    }
  }, [opScanId]);

  if (loading && !project) {
    return (
      <PageLayout>
        <PageHeader title="Project" />
        <div style={{ padding: 48, textAlign: 'center', opacity: 0.6 }}>Loading...</div>
      </PageLayout>
    );
  }

  if (!project) {
    return (
      <PageLayout>
        <PageHeader title="Project Not Found" />
        <div style={{ padding: 48, textAlign: 'center' }}>
          <p>This project does not exist.</p>
          <Button variant="primary" component={(props: object) => <Link {...props} to="/projects" />}>
            Back to Projects
          </Button>
        </div>
      </PageLayout>
    );
  }

  const isRunning = opStatus === 'connecting' || opStatus === 'preparing' || opStatus === 'checking' || opStatus === 'applying';
  const operationActive = isRunning || opStatus === 'awaiting_approval' || (opStatus === 'complete' && opResult != null) || opStatus === 'error';

  return (
    <PageLayout>
      <PageHeader
        title={project.name}
        description={`${project.repo_url} (${project.branch})`}
      />

      <div style={{ padding: '0 24px 24px' }}>
        <Tabs activeKey={activeTab} onSelect={(_e, k) => {
          setActiveTab(k as number);
          if (k === 1 || k === 2) fetchData();
          if (k === 4 && projectId && !graphData && !graphLoading) {
            setGraphLoading(true);
            getProjectGraph(projectId).then(setGraphData).catch(() => setGraphData(null)).finally(() => setGraphLoading(false));
          }
        }}>
          <Tab eventKey={0} title={<TabTitleText>Overview</TabTitleText>}>
            <div style={{ marginTop: 16 }}>
              {operationActive ? (
                <>
                  {isRunning && (
                    <OperationProgressPanel status={opStatus} progress={opProgress} onCancel={opCancel} />
                  )}

                  {opStatus === 'awaiting_approval' && opProposals.length > 0 && (
                    <ProposalReviewPanel proposals={opProposals} onApprove={opApprove} feedbackEnabled={feedbackEnabled} scanId={opScanId ?? undefined} />
                  )}

                  {opStatus === 'complete' && opResult && (
                    <OperationResultCard
                      result={opResult}
                      isRemediate={opIsRemediate}
                      onDismiss={() => { opReset(); setPrUrl(null); setPrError(null); }}
                      onCreatePR={opIsRemediate && opScanId ? handleCreatePR : undefined}
                      prCreating={prCreating}
                      prUrl={prUrl}
                      prError={prError}
                    />
                  )}

                  {opStatus === 'error' && (
                    <Card style={{ marginBottom: 16, borderLeft: '4px solid var(--pf-t--global--color--status--danger--default)' }}>
                      <CardBody>
                        <h3 style={{ color: 'var(--pf-t--global--color--status--danger--default)' }}>Error</h3>
                        <p>{opError}</p>
                        <Button variant="link" onClick={opReset}>Dismiss</Button>
                      </CardBody>
                    </Card>
                  )}
                </>
              ) : project.scan_count === 0 ? (
                <Card style={{ marginBottom: 16 }}>
                  <CardBody style={{ textAlign: 'center', padding: '48px 24px' }}>
                    <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>No checks yet</div>
                    <div style={{ opacity: 0.7 }}>
                      Go to the <Button variant="link" isInline onClick={() => setActiveTab(1)}>Activity</Button> tab to run the first check.
                    </div>
                  </CardBody>
                </Card>
              ) : (
                <>
                  <Split hasGutter style={{ marginBottom: 16 }}>
                    <SplitItem>
                      <Card>
                        <CardBody>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontSize: 36, fontWeight: 700, color: healthColor(project.health_score) }}>{project.health_score}</div>
                            <div style={{ opacity: 0.7 }}>Health Score</div>
                          </div>
                        </CardBody>
                      </Card>
                    </SplitItem>
                    <SplitItem>
                      <Card>
                        <CardBody>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontSize: 36, fontWeight: 700 }}>{project.total_violations}</div>
                            <div style={{ opacity: 0.7 }}>Violations</div>
                          </div>
                        </CardBody>
                      </Card>
                    </SplitItem>
                    <SplitItem>
                      <Card>
                        <CardBody>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontSize: 36, fontWeight: 700 }}>{project.scan_count}</div>
                            <div style={{ opacity: 0.7 }}>Activity</div>
                          </div>
                        </CardBody>
                      </Card>
                    </SplitItem>
                    <SplitItem>
                      <Card>
                        <CardBody>
                          <div style={{ textAlign: 'center' }}>
                            <div style={{ fontSize: 36, fontWeight: 700 }}>
                              {project.last_scanned_at ? timeAgo(project.last_scanned_at) : 'Never'}
                            </div>
                            <div style={{ opacity: 0.7 }}>Last Checked</div>
                          </div>
                        </CardBody>
                      </Card>
                    </SplitItem>
                  </Split>

                  {Object.keys(project.severity_breakdown).length > 0 && (
                    <Card style={{ marginBottom: 16 }}>
                      <CardBody>
                        <h3>Severity Breakdown</h3>
                        <Flex gap={{ default: 'gapLg' }} style={{ marginTop: 8 }}>
                          {(() => {
                            const merged = new Map<string, number>();
                            for (const [level, count] of Object.entries(project.severity_breakdown)) {
                              const cls = severityClass(level);
                              merged.set(cls, (merged.get(cls) ?? 0) + count);
                            }
                            return Array.from(merged.entries())
                              .sort((a, b) => severityOrder(a[0]) - severityOrder(b[0]))
                              .map(([cls, count]) => (
                                <FlexItem key={cls}>
                                  <span className={`apme-severity ${cls}`}>
                                    {SEVERITY_LABELS[cls] ?? cls}: {count}
                                  </span>
                                </FlexItem>
                              ));
                          })()}
                        </Flex>
                      </CardBody>
                    </Card>
                  )}

                  {trend.length > 1 && <TrendChart data={trend} />}
                </>
              )}
            </div>
          </Tab>

          <Tab eventKey={1} title={<TabTitleText>Activity</TabTitleText>}>
            <div style={{ marginTop: 16 }}>
              <Card style={{ marginBottom: 16 }}>
                <CardBody>
                  <h3>Options</h3>
                  <CheckOptionsForm
                    ansibleVersion={ansibleVersion}
                    onAnsibleVersionChange={setAnsibleVersion}
                    collections={collections}
                    onCollectionsChange={setCollections}
                    enableAi={enableAi}
                    onEnableAiChange={setEnableAi}
                    idPrefix="proj"
                  />
                  <Flex gap={{ default: 'gapSm' }} style={{ marginTop: 12 }}>
                    <Button variant="primary" isDisabled={isRunning} onClick={() => handleScan(false)}>Check</Button>
                    <Button variant="secondary" isDisabled={isRunning} onClick={() => handleScan(true)}>Remediate</Button>
                    {isRunning && <Button variant="link" onClick={opCancel}>Cancel</Button>}
                  </Flex>
                </CardBody>
              </Card>

              <h3 style={{ marginBottom: 8 }}>History</h3>
              {scans.length === 0 ? (
                <div style={{ padding: 24, textAlign: 'center', opacity: 0.6 }}>No activity recorded yet.</div>
              ) : (
                <table className="pf-v6-c-table pf-m-compact pf-m-grid-md" role="grid">
                  <thead>
                    <tr role="row">
                      <th role="columnheader">Type</th>
                      <th role="columnheader">Status</th>
                      <th role="columnheader">Violations</th>
                      <th role="columnheader">Fixable</th>
                      <th role="columnheader">Remediated</th>
                      <th role="columnheader">AI Proposed</th>
                      <th role="columnheader">AI Declined</th>
                      <th role="columnheader">AI Accepted</th>
                      <th role="columnheader">Manual</th>
                      <th role="columnheader">Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scans.map((scan) => {
                      const isFix = scan.scan_type === 'fix' || scan.scan_type === 'remediate';
                      return (
                      <tr
                        key={scan.scan_id}
                        role="row"
                        tabIndex={0}
                        onClick={() => navigate(`/activity/${scan.scan_id}`)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/activity/${scan.scan_id}`); } }}
                        style={{ cursor: 'pointer' }}
                      >
                        <td role="cell">
                          <span className={`apme-badge ${isFix ? 'passed' : 'running'}`}>
                            {scan.scan_type === 'scan' ? 'check' : scan.scan_type === 'fix' ? 'remediate' : scan.scan_type}
                          </span>
                        </td>
                        <td role="cell"><StatusBadge violations={scan.total_violations} scanType={scan.scan_type} /></td>
                        <td role="cell">{scan.total_violations}</td>
                        <td role="cell">
                          {isFix
                            ? <span style={{ opacity: 0.3 }}>&mdash;</span>
                            : <span className="apme-count-success">{scan.fixable}</span>
                          }
                        </td>
                        <td role="cell">
                          {isFix
                            ? <span className="apme-count-success">{scan.remediated_count}</span>
                            : <span style={{ opacity: 0.3 }}>&mdash;</span>
                          }
                        </td>
                        <td role="cell">{scan.ai_proposed ?? 0}</td>
                        <td role="cell">{scan.ai_declined ?? 0}</td>
                        <td role="cell"><span className="apme-count-success">{scan.ai_accepted ?? 0}</span></td>
                        <td role="cell"><span className="apme-count-warning">{scan.manual_review}</span></td>
                        <td role="cell" style={{ opacity: 0.7 }}>{timeAgo(scan.created_at)}</td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </Tab>

          <Tab eventKey={2} title={<TabTitleText>Violations</TabTitleText>}>
            <ViolationsTab violations={violations} />
          </Tab>

          <Tab eventKey={3} title={<TabTitleText>Dependencies</TabTitleText>}>
            <DependenciesTab dependencies={dependencies} depHealth={depHealth} loading={loading} projectId={projectId} />
          </Tab>

          <Tab eventKey={4} title={<TabTitleText>Visualize</TabTitleText>}>
            <div style={{ marginTop: 16 }}>
              {graphLoading ? (
                <div style={{ padding: 48, textAlign: 'center', opacity: 0.6 }}>Loading graph...</div>
              ) : graphData ? (
                <GraphVisualization data={graphData} />
              ) : (
                <div style={{ padding: 48, textAlign: 'center', opacity: 0.6 }}>
                  No graph data available. Run a check to generate the content graph.
                </div>
              )}
            </div>
          </Tab>

          <Tab eventKey={5} title={<TabTitleText>Settings</TabTitleText>}>
            <div style={{ marginTop: 16, maxWidth: 600 }}>
              <Card>
                <CardBody>
                  <Flex direction={{ default: 'column' }} gap={{ default: 'gapMd' }}>
                    <FlexItem>
                      <label htmlFor="edit-name" style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>Name</label>
                      <TextInput id="edit-name" value={editName} onChange={(_e, v) => setEditName(v)} />
                    </FlexItem>
                    <FlexItem>
                      <label htmlFor="edit-url" style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>Repository URL</label>
                      <TextInput id="edit-url" value={editUrl} onChange={(_e, v) => setEditUrl(v)} />
                    </FlexItem>
                    <FlexItem>
                      <label htmlFor="edit-branch" style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>Branch</label>
                      <TextInput id="edit-branch" value={editBranch} onChange={(_e, v) => setEditBranch(v)} />
                    </FlexItem>
                    <FlexItem>
                      <label htmlFor="edit-scm-token" style={{ display: 'block', fontWeight: 600, marginBottom: 4 }}>
                        SCM Token
                        {project?.has_scm_token && (
                          <span style={{ fontWeight: 400, marginLeft: 8, fontSize: 12, opacity: 0.7 }}>(configured)</span>
                        )}
                      </label>
                      <TextInput
                        id="edit-scm-token"
                        type="password"
                        value={editScmToken}
                        onChange={(_e, v) => { setEditScmToken(v); setScmTokenDirty(true); }}
                        placeholder={project?.has_scm_token ? '••••••••' : 'GitHub PAT or App token'}
                      />
                      <div style={{ fontSize: 12, marginTop: 4, opacity: 0.6 }}>
                        Used for creating pull requests from remediation results. Leave blank to keep current value.
                      </div>
                    </FlexItem>
                    <FlexItem>
                      <Flex gap={{ default: 'gapSm' }}>
                        <Button variant="primary" onClick={handleSave} isDisabled={saving}>
                          {saving ? 'Saving...' : 'Save'}
                        </Button>
                        <Button variant="danger" onClick={handleDelete}>Delete Project</Button>
                      </Flex>
                    </FlexItem>
                  </Flex>
                </CardBody>
              </Card>
            </div>
          </Tab>
        </Tabs>
      </div>
    </PageLayout>
  );
}

function ViolationsTab({ violations }: { violations: ViolationDetail[] }) {
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const sorted = useMemo(
    () =>
      [...violations].sort(
        (a, b) =>
          severityOrder(severityClass(a.level, a.rule_id)) -
          severityOrder(severityClass(b.level, b.rule_id)),
      ),
    [violations],
  );

  const toggleRow = (id: number) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div style={{ marginTop: 16 }}>
      {sorted.length === 0 ? (
        <div style={{ padding: 24, textAlign: 'center', opacity: 0.6 }}>
          No violations in the latest check.
        </div>
      ) : (
        <table
          className="pf-v6-c-table pf-m-compact pf-m-grid-md apme-violations-table"
          role="grid"
        >
          <thead>
            <tr role="row">
              <th role="columnheader" className="apme-vt-col-rule">Rule</th>
              <th role="columnheader" className="apme-vt-col-severity">Severity</th>
              <th role="columnheader" className="apme-vt-col-file">File</th>
              <th role="columnheader" className="apme-vt-col-line">Line</th>
              <th role="columnheader" className="apme-vt-col-message">Message</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((v) => {
              const isExpanded = expandedRows.has(v.id);
              return (
                <tr key={v.id} role="row">
                  <td role="cell">
                    <span className="apme-rule-id">{bareRuleId(v.rule_id)}</span>
                  </td>
                  <td role="cell">
                    <span
                      className={`apme-severity ${severityClass(v.level, v.rule_id)}`}
                      style={{ whiteSpace: 'nowrap' }}
                    >
                      {severityLabel(v.level, v.rule_id)}
                    </span>
                  </td>
                  <td role="cell" style={{ fontFamily: 'var(--pf-t--global--font--family--mono)' }}>
                    {v.file}
                  </td>
                  <td role="cell">{v.line ?? ''}</td>
                  <td
                    role="cell"
                    className={`apme-vt-message${isExpanded ? ' expanded' : ''}`}
                    onClick={() => toggleRow(v.id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleRow(v.id); }}
                    tabIndex={0}
                  >
                    {v.message}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DependenciesTab({ dependencies, depHealth, loading, projectId }: { dependencies: ProjectDependencies | null; depHealth: DepHealthSummary | null; loading: boolean; projectId?: string }) {
  const navigate = useNavigate();
  const [downloading, setDownloading] = useState(false);

  const collHealthMap = useMemo(() => {
    const map = new Map<string, { finding_count: number; critical: number; error: number; high: number; medium: number; low: number; info: number }>();
    if (!depHealth) return map;
    for (const f of depHealth.collection_findings) {
      map.set(f.fqcn, f);
    }
    return map;
  }, [depHealth]);

  const pkgCveMap = useMemo(() => {
    const map = new Map<string, { count: number; hasCritical: boolean }>();
    if (!depHealth) return map;
    for (const cve of depHealth.python_cves) {
      const match = cve.message.match(/^([a-zA-Z0-9_.-]+)==/);
      if (!match?.[1]) continue;
      const pkg = match[1].toLowerCase();
      const existing = map.get(pkg) ?? { count: 0, hasCritical: false };
      existing.count += cve.occurrence_count;
      const cls = severityClass(cve.level);
      if (cls === 'critical' || cls === 'error' || cls === 'high') existing.hasCritical = true;
      map.set(pkg, existing);
    }
    return map;
  }, [depHealth]);

  const handleSbomDownload = useCallback(async () => {
    if (!projectId) return;
    setDownloading(true);
    try {
      const blob = await getProjectSbom(projectId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const safeId = projectId.replace(/[^a-zA-Z0-9_-]/g, '_');
      a.download = `sbom-${safeId}.cdx.json`;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      alert('Failed to download SBOM. Make sure a scan has been run.');
    } finally {
      setDownloading(false);
    }
  }, [projectId]);

  if (loading && !dependencies) {
    return (
      <div style={{ marginTop: 16, padding: 24, textAlign: 'center', opacity: 0.6 }}>
        Loading dependencies...
      </div>
    );
  }

  if (!dependencies) {
    return (
      <div style={{ marginTop: 16, padding: 24, textAlign: 'center', opacity: 0.6 }}>
        No dependency information available. Run a check to collect dependencies.
      </div>
    );
  }

  const hasCollections = dependencies.collections.length > 0;
  const hasPackages = dependencies.python_packages.length > 0;
  const hasAnsibleCore = !!dependencies.ansible_core_version;

  if (!hasCollections && !hasPackages && !hasAnsibleCore) {
    return (
      <div style={{ marginTop: 16, padding: 24, textAlign: 'center', opacity: 0.6 }}>
        No dependency information available. Run a check to collect dependencies.
      </div>
    );
  }

  return (
    <div style={{ marginTop: 16 }}>
      <Flex justifyContent={{ default: 'justifyContentFlexEnd' }} style={{ marginBottom: 12 }}>
        <Button
          variant="secondary"
          size="sm"
          isDisabled={downloading}
          onClick={handleSbomDownload}
        >
          {downloading ? 'Downloading...' : 'Download SBOM (CycloneDX)'}
        </Button>
      </Flex>

      {depHealth && (depHealth.collection_findings.length > 0 || depHealth.python_cves.length > 0) && (
        <Card style={{ marginBottom: 16, borderLeft: '4px solid var(--pf-t--global--color--status--warning--default)' }}>
          <CardBody>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <ShieldAltIcon />
              Dependency Health Summary
            </h3>
            <Flex gap={{ default: 'gapLg' }}>
              {depHealth.collection_findings.length > 0 && (
                <FlexItem>
                  <span style={{ fontWeight: 600 }}>
                    {depHealth.collection_findings.reduce((s, c) => s + c.finding_count, 0)}
                  </span>{' '}
                  collection findings in{' '}
                  <span style={{ fontWeight: 600 }}>
                    {depHealth.collection_findings.length}
                  </span>{' '}
                  collection{depHealth.collection_findings.length !== 1 ? 's' : ''}
                </FlexItem>
              )}
              {depHealth.python_cves.length > 0 && (
                <FlexItem>
                  <ExclamationCircleIcon style={{ color: 'var(--pf-t--global--color--status--danger--default)', marginRight: 4 }} />
                  <span style={{ fontWeight: 600 }}>
                    {depHealth.python_cves.length}
                  </span>{' '}
                  Python CVE{depHealth.python_cves.length !== 1 ? 's' : ''} detected
                </FlexItem>
              )}
            </Flex>
          </CardBody>
        </Card>
      )}

      {hasAnsibleCore && (
        <Card style={{ marginBottom: 16 }}>
          <CardBody>
            <h3 style={{ marginBottom: 8 }}>Ansible Core</h3>
            <div style={{ fontFamily: 'var(--pf-t--global--font--family--mono)' }}>
              ansible-core=={dependencies.ansible_core_version}
            </div>
          </CardBody>
        </Card>
      )}

      {hasCollections && (
        <Card style={{ marginBottom: 16 }}>
          <CardBody>
            <h3 style={{ marginBottom: 8 }}>Collections ({dependencies.collections.length})</h3>
            <table className="pf-v6-c-table pf-m-compact pf-m-grid-md" role="grid">
              <thead>
                <tr role="row">
                  <th role="columnheader">FQCN</th>
                  <th role="columnheader">Version</th>
                  <th role="columnheader">Source</th>
                  <th role="columnheader">Findings</th>
                </tr>
              </thead>
              <tbody>
                {dependencies.collections.map((c) => {
                  const h = collHealthMap.get(c.fqcn);
                  const hasCritical = h && (h.critical > 0 || h.error > 0);
                  return (
                  <tr
                    key={`${c.fqcn}-${c.version}`}
                    role="row"
                    tabIndex={0}
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/collections/${encodeURIComponent(c.fqcn)}`)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/collections/${encodeURIComponent(c.fqcn)}`); } }}
                  >
                    <td role="cell" style={{ fontFamily: 'var(--pf-t--global--font--family--mono)', fontWeight: 600 }}>
                      {c.fqcn}
                    </td>
                    <td role="cell">{c.version}</td>
                    <td role="cell" style={{ opacity: 0.7 }}>{c.source}</td>
                    <td role="cell">
                      {h ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          {hasCritical && <ExclamationCircleIcon style={{ color: 'var(--pf-t--global--color--status--danger--default)' }} />}
                          {h.high > 0 && <ExclamationTriangleIcon style={{ color: 'var(--pf-t--global--color--status--warning--default)' }} />}
                          <Badge isRead={!hasCritical}>{h.finding_count}</Badge>
                        </span>
                      ) : (
                        <span style={{ opacity: 0.4 }}>&mdash;</span>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </CardBody>
        </Card>
      )}

      {hasPackages && (
        <Card style={{ marginBottom: 16 }}>
          <CardBody>
            <h3 style={{ marginBottom: 8 }}>Python Packages ({dependencies.python_packages.length})</h3>
            <table className="pf-v6-c-table pf-m-compact pf-m-grid-md" role="grid">
              <thead>
                <tr role="row">
                  <th role="columnheader">Package</th>
                  <th role="columnheader">Version</th>
                  <th role="columnheader">CVEs</th>
                </tr>
              </thead>
              <tbody>
                {dependencies.python_packages.map((p) => {
                  const cveInfo = pkgCveMap.get(p.name.toLowerCase());
                  return (
                  <tr
                    key={`${p.name}-${p.version}`}
                    role="row"
                    tabIndex={0}
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/python-packages/${encodeURIComponent(p.name)}`)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/python-packages/${encodeURIComponent(p.name)}`); } }}
                  >
                    <td role="cell" style={{ fontFamily: 'var(--pf-t--global--font--family--mono)', fontWeight: 600 }}>
                      {p.name}
                    </td>
                    <td role="cell">{p.version}</td>
                    <td role="cell">
                      {cveInfo ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          {cveInfo.hasCritical && <ExclamationCircleIcon style={{ color: 'var(--pf-t--global--color--status--danger--default)' }} />}
                          <Badge isRead={!cveInfo.hasCritical}>{cveInfo.count}</Badge>
                        </span>
                      ) : (
                        <span style={{ opacity: 0.4 }}>&mdash;</span>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </CardBody>
        </Card>
      )}

      {depHealth && depHealth.python_cves.length > 0 && (
        <Card style={{ marginBottom: 16, borderLeft: '4px solid var(--pf-t--global--color--status--danger--default)' }}>
          <CardBody>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <ExclamationCircleIcon style={{ color: 'var(--pf-t--global--color--status--danger--default)' }} />
              Python CVEs ({depHealth.python_cves.length})
            </h3>
            <table className="pf-v6-c-table pf-m-compact" role="grid">
              <thead>
                <tr role="row">
                  <th role="columnheader" style={{ width: 90 }}>Severity</th>
                  <th role="columnheader" style={{ width: 160 }}>CVE / Rule</th>
                  <th role="columnheader">Details</th>
                  <th role="columnheader" style={{ width: 100 }}>Occurrences</th>
                </tr>
              </thead>
              <tbody>
                {depHealth.python_cves.map((cve, i) => {
                  const cls = severityClass(cve.level);
                  const cveId = cve.message.match(/CVE-\d{4}-\d+/)?.[0] ?? cve.rule_id;
                  return (
                    <tr key={`${cve.rule_id}-${i}`} role="row">
                      <td role="cell">
                        <Label
                          color={cls === 'critical' || cls === 'error' ? 'red' : cls === 'high' ? 'orange' : cls === 'medium' ? 'yellow' : 'blue'}
                          isCompact
                        >
                          {cls.toUpperCase()}
                        </Label>
                      </td>
                      <td role="cell">
                        <span style={{ fontFamily: 'var(--pf-t--global--font--family--mono)', fontWeight: 600 }}>
                          {cveId}
                        </span>
                      </td>
                      <td role="cell" style={{ fontSize: 13 }}>{cve.message}</td>
                      <td role="cell"><Badge isRead>{cve.occurrence_count}</Badge></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardBody>
        </Card>
      )}

      {dependencies.requirements_files.length > 0 && (
        <Card>
          <CardBody>
            <h3 style={{ marginBottom: 8 }}>Requirements Files</h3>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {dependencies.requirements_files.map((f) => (
                <li key={f} style={{ fontFamily: 'var(--pf-t--global--font--family--mono)' }}>{f}</li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
