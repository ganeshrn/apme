import { useMemo, useState } from 'react';
import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Tab,
  Tabs,
  TabTitleText,
} from '@patternfly/react-core';
import { PageDetails, PageDetail } from '@ansible/ansible-ui-framework';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { DiffView } from './DiffView';
import { FeedbackModal, type FeedbackPayload } from './FeedbackModal';
import { severityClass, severityLabel, bareRuleId, ruleSource } from './severity';

function parseSnippet(raw: string): { code: string; startLine: number } {
  const lines = raw.split('\n');
  let startLine = 1;
  const cleaned: string[] = [];
  for (const line of lines) {
    const m = /^\s*(\d+): (.*)$/.exec(line);
    if (m) {
      if (cleaned.length === 0) startLine = parseInt(m[1]!, 10);
      cleaned.push(m[2]!);
    } else {
      cleaned.push(line);
    }
  }
  return { code: cleaned.join('\n'), startLine };
}

function tierLabel(rc: number): string {
  if (rc === 1) return 'Fixable';
  if (rc === 2) return 'AI';
  if (rc === 3) return 'Manual';
  return 'Unknown';
}

export interface ViolationRecord {
  id: number;
  rule_id: string;
  level: string;
  message: string;
  file: string;
  line: number | null;
  path: string;
  remediation_class: number;
  validator_source?: string;
  snippet?: string;
}

interface ViolationDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  violation: ViolationRecord;
  diff?: string;
  getRuleDescription?: (ruleId: string) => string | undefined;
  mergedViolations?: ViolationRecord[];
  scanId?: string;
  feedbackEnabled?: boolean;
}

export function ViolationDetailModal({ isOpen, onClose, violation, diff, getRuleDescription, mergedViolations, scanId, feedbackEnabled }: ViolationDetailModalProps) {
  const [activeTab, setActiveTab] = useState(0);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const ruleDesc = getRuleDescription?.(violation.rule_id);
  const cls = severityClass(violation.level, violation.rule_id);
  const source = ruleSource(violation.rule_id);
  const isCombinedFixed = !!mergedViolations;
  const parsed = useMemo(
    () => (violation.snippet ? parseSnippet(violation.snippet) : null),
    [violation.snippet],
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      aria-label="Violation details"
      width="75%"
    >
      <ModalHeader title={isCombinedFixed ? 'Fixed Violations' : 'Violation Details'} />
      <ModalBody>
        <Tabs
          aria-label="Violation detail tabs"
          activeKey={activeTab}
          onSelect={(_e, key) => setActiveTab(key as number)}
        >
          <Tab eventKey={0} title={<TabTitleText>Details</TabTitleText>} aria-label="Details tab">
            {isCombinedFixed ? (
              <div style={{ paddingTop: 12 }}>
                <p style={{ marginBottom: 12, opacity: 0.8 }}>
                  {mergedViolations.length} violation{mergedViolations.length !== 1 ? 's' : ''} fixed in <strong>{violation.file}</strong>
                </p>
                <table className="pf-v6-c-table pf-m-compact" role="grid">
                  <thead>
                    <tr role="row">
                      <th role="columnheader">Rule</th>
                      <th role="columnheader">Severity</th>
                      <th role="columnheader">Line</th>
                      <th role="columnheader">Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mergedViolations.map((v) => (
                      <tr key={v.id} role="row">
                        <td role="cell"><span className="apme-rule-id">{bareRuleId(v.rule_id)}</span></td>
                        <td role="cell">
                          <span className={`apme-severity ${severityClass(v.level, v.rule_id)}`}>
                            {severityLabel(v.level, v.rule_id)}
                          </span>
                        </td>
                        <td role="cell">{v.line ?? ''}</td>
                        <td role="cell">{v.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <PageDetails>
                <PageDetail label="Rule">
                  <span className="apme-rule-id">{bareRuleId(violation.rule_id)}</span>
                </PageDetail>
                {source && (
                  <PageDetail label="Source">
                    {source}
                  </PageDetail>
                )}
                <PageDetail label="Severity">
                  <span className={`apme-severity ${cls}`}>
                    {severityLabel(violation.level, violation.rule_id)}
                  </span>
                </PageDetail>
                <PageDetail label="File">
                  {violation.file || '(unknown)'}
                </PageDetail>
                <PageDetail isEmpty={violation.line == null} label="Line">
                  {violation.line}
                </PageDetail>
                <PageDetail label="Remediation">
                  {tierLabel(violation.remediation_class)}
                </PageDetail>
                <PageDetail label="Message">
                  {violation.message}
                </PageDetail>
                {violation.path && (
                  <PageDetail label="YAML Path">
                    <code style={{ fontSize: 12 }}>{violation.path}</code>
                  </PageDetail>
                )}
                {ruleDesc && (
                  <PageDetail label="Rule Description">
                    {ruleDesc}
                  </PageDetail>
                )}
              </PageDetails>
            )}
          </Tab>
          {parsed ? (
            <Tab eventKey={1} title={<TabTitleText>Source</TabTitleText>} aria-label="Source tab">
              <div className="apme-modal-diff">
                <SyntaxHighlighter
                  language="yaml"
                  style={oneDark}
                  showLineNumbers
                  startingLineNumber={parsed.startLine}
                  wrapLines
                  lineProps={(lineNo: number) => {
                    const style: React.CSSProperties = { display: 'block' };
                    if (violation.line != null && lineNo === violation.line) {
                      style.backgroundColor = 'rgba(255, 215, 0, 0.18)';
                    }
                    return { style };
                  }}
                  customStyle={{ margin: 0, fontSize: '0.85em', borderRadius: 4 }}
                >
                  {parsed.code}
                </SyntaxHighlighter>
              </div>
            </Tab>
          ) : null}
          {diff ? (
            <Tab eventKey={parsed ? 2 : 1} title={<TabTitleText>Diff</TabTitleText>} aria-label="Diff tab">
              <div className="apme-modal-diff">
                <DiffView diff={diff} />
              </div>
            </Tab>
          ) : null}
          <Tab eventKey={(parsed ? 1 : 0) + (diff ? 1 : 0) + 1} title={<TabTitleText>Data</TabTitleText>} aria-label="Data tab">
            <div className="apme-modal-diff">
              <pre>{JSON.stringify(isCombinedFixed ? mergedViolations : violation, null, 2)}</pre>
            </div>
          </Tab>
        </Tabs>
      </ModalBody>
      {feedbackEnabled && (
        <ModalFooter>
          <Button variant="link" onClick={() => setFeedbackOpen(true)}>Report Issue</Button>
        </ModalFooter>
      )}
      <FeedbackModal
        isOpen={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        prefill={{
          type: 'false_positive',
          rule_id: violation.rule_id,
          source: violation.validator_source || ruleSource(violation.rule_id) || '',
          file: violation.file,
          scan_id: scanId ?? '',
          context: {
            violation_message: violation.message,
            ai_proposal_diff: diff ?? '',
            ai_explanation: '',
            source_snippet: violation.snippet ?? '',
          },
        } satisfies Partial<FeedbackPayload>}
      />
    </Modal>
  );
}
