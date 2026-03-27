import { useCallback, useMemo, useState } from 'react';
import {
  Button,
  Card,
  CardBody,
  Flex,
  Label,
  Split,
  SplitItem,
} from '@patternfly/react-core';
import type { OperationProposal } from '../types/operation';
import { DiffView } from './DiffView';
import { FeedbackModal, type FeedbackPayload } from './FeedbackModal';

export interface ProposalReviewPanelProps {
  proposals: OperationProposal[];
  onApprove: (ids: string[]) => void;
  feedbackEnabled?: boolean;
  scanId?: string;
}

export function ProposalReviewPanel({
  proposals,
  onApprove,
  feedbackEnabled,
  scanId,
}: ProposalReviewPanelProps) {
  const proposed = useMemo(() => proposals.filter((p) => p.status !== 'declined'), [proposals]);
  const declined = useMemo(() => proposals.filter((p) => p.status === 'declined'), [proposals]);

  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [showDeclined, setShowDeclined] = useState(false);
  const [feedbackTarget, setFeedbackTarget] = useState<OperationProposal | null>(null);

  const toggleAll = useCallback(() => {
    setSelected((prev) =>
      prev.size === proposed.length
        ? new Set()
        : new Set(proposed.map((p) => p.id)),
    );
  }, [proposed]);

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleExpand = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const allSelected = proposed.length > 0 && selected.size === proposed.length;

  return (
    <Card style={{ marginBottom: 16 }}>
      <CardBody>
        <Split hasGutter style={{ marginBottom: 16 }}>
          <SplitItem isFilled>
            <Label color="yellow" isCompact>AI Review</Label>
            <h3 style={{ marginTop: 4 }}>
              {proposed.length} AI Proposal{proposed.length !== 1 ? 's' : ''}
            </h3>
            <span style={{ fontSize: 13, opacity: 0.7 }}>
              Review each proposed change and select which to apply.
            </span>
          </SplitItem>
          <SplitItem>
            <Flex gap={{ default: 'gapSm' }}>
              <Button variant="secondary" onClick={toggleAll} size="sm">
                {allSelected ? 'Deselect All' : 'Select All'}
              </Button>
              <Button variant="link" onClick={() => onApprove([])} size="sm">Skip All</Button>
              <Button variant="primary" onClick={() => onApprove(Array.from(selected))} size="sm">
                Apply {selected.size} Selected
              </Button>
            </Flex>
          </SplitItem>
        </Split>

        {/* Proposed (actionable) */}
        <div className="apme-proposals-list" role="group" aria-label="AI fix proposals">
          {proposed.map((p) => {
            const isExpanded = expanded.has(p.id);
            const hasDetail = !!(p.explanation || p.diff_hunk);
            return (
              <div
                key={p.id}
                className={`apme-proposal-card ${selected.has(p.id) ? 'selected' : ''}`}
              >
                <div
                  className="apme-proposal-header"
                  role="checkbox"
                  aria-checked={selected.has(p.id)}
                  tabIndex={0}
                  onClick={() => toggleSelect(p.id)}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault();
                      toggleSelect(p.id);
                    }
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    readOnly
                    tabIndex={-1}
                    aria-hidden="true"
                    className="apme-proposal-checkbox"
                  />
                  <div className="apme-proposal-meta">
                    <span className="apme-rule-id">{p.rule_id}</span>
                    <span className="apme-proposal-file">{p.file}</span>
                    <Label isCompact variant="outline">Tier {p.tier}</Label>
                  </div>
                  <div className="apme-proposal-confidence">
                    <div className="apme-confidence-bar">
                      <div
                        className="apme-confidence-fill"
                        style={{ width: `${Math.round(p.confidence * 100)}%` }}
                      />
                    </div>
                    <span className="apme-confidence-label">
                      {Math.round(p.confidence * 100)}%
                    </span>
                  </div>
                  {hasDetail && (
                    <Button
                      variant="link"
                      size="sm"
                      onClick={(e) => { e.stopPropagation(); toggleExpand(p.id); }}
                      style={{ flexShrink: 0 }}
                    >
                      {isExpanded ? 'Hide' : 'Show'}
                    </Button>
                  )}
                </div>

                {isExpanded && p.explanation && (
                  <div className="apme-proposal-explanation">
                    {p.explanation}
                  </div>
                )}

                {isExpanded && p.diff_hunk && (
                  <div className="apme-proposal-diff">
                    <DiffView diff={p.diff_hunk} />
                  </div>
                )}
                {isExpanded && feedbackEnabled && (
                  <div style={{ padding: '4px 12px 8px' }}>
                    <Button
                      variant="link"
                      size="sm"
                      onClick={(e) => { e.stopPropagation(); setFeedbackTarget(p); }}
                    >
                      Report Issue
                    </Button>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Declined by AI */}
        {declined.length > 0 && (
          <div style={{ marginTop: 20 }}>
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginBottom: 8 }}
              onClick={() => setShowDeclined((v) => !v)}
            >
              <span style={{ opacity: 0.5, fontSize: 12 }}>{showDeclined ? '\u25BC' : '\u25B6'}</span>
              <Label color="orange" isCompact>Declined by AI</Label>
              <span style={{ fontSize: 13, opacity: 0.7 }}>
                {declined.length} violation{declined.length !== 1 ? 's' : ''} the AI could not fix
              </span>
            </div>
            {showDeclined && (
              <div className="apme-proposals-list">
                {declined.map((p) => {
                  const isExpanded = expanded.has(p.id);
                  return (
                    <div key={p.id} className="apme-proposal-card apme-proposal-declined">
                      <div
                        className="apme-proposal-header"
                        style={{ cursor: 'pointer' }}
                        onClick={() => toggleExpand(p.id)}
                      >
                        <div className="apme-proposal-meta">
                          <span className="apme-rule-id">{p.rule_id}</span>
                          <span className="apme-proposal-file">{p.file}</span>
                          {p.line_start != null && p.line_start > 0 && (
                            <span style={{ fontSize: 12, opacity: 0.6 }}>Line {p.line_start}</span>
                          )}
                        </div>
                        <Button
                          variant="link"
                          size="sm"
                          onClick={(e) => { e.stopPropagation(); toggleExpand(p.id); }}
                          style={{ flexShrink: 0 }}
                        >
                          {isExpanded ? 'Hide' : 'Why?'}
                        </Button>
                      </div>

                      {isExpanded && (
                        <div className="apme-proposal-explanation">
                          {p.explanation && (
                            <div style={{ marginBottom: p.suggestion ? 8 : 0 }}>
                              <strong>Reason:</strong> {p.explanation}
                            </div>
                          )}
                          {p.suggestion && (
                            <div>
                              <strong>Suggestion:</strong> {p.suggestion}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </CardBody>
      {feedbackTarget && (
        <FeedbackModal
          isOpen={!!feedbackTarget}
          onClose={() => setFeedbackTarget(null)}
          prefill={{
            type: 'bad_ai_suggestion',
            rule_id: feedbackTarget.rule_id,
            file: feedbackTarget.file,
            scan_id: scanId ?? '',
            context: {
              violation_message: '',
              ai_proposal_diff: feedbackTarget.diff_hunk ?? '',
              ai_explanation: feedbackTarget.explanation ?? '',
              source_snippet: '',
            },
          } satisfies Partial<FeedbackPayload>}
        />
      )}
    </Card>
  );
}
