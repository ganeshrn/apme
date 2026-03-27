import { useMemo, useRef, useState } from 'react';
import { Button } from '@patternfly/react-core';
import {
  AngleDownIcon,
  AngleRightIcon,
  AngleDoubleUpIcon,
  AngleDoubleDownIcon,
} from '@patternfly/react-icons';
import { ViolationDetailModal, type ViolationRecord } from './ViolationDetailModal';
import { severityClass, severityLabel, severityOrder, bareRuleId } from './severity';

function tierLabel(rc: number, isRemediate: boolean): string {
  if (rc === 1) return isRemediate ? 'Fixed' : 'Fixable';
  if (rc === 2) return 'AI';
  if (rc === 3) return 'Manual';
  return '';
}

function tierBadgeClass(rc: number, isRemediate: boolean): string {
  if (rc === 1) return isRemediate ? 'apme-badge passed' : 'apme-badge fixable';
  if (rc === 2) return 'apme-badge ai';
  if (rc === 3) return 'apme-badge manual';
  return 'apme-badge';
}

function groupByFile(violations: ViolationRecord[]): Map<string, ViolationRecord[]> {
  const map = new Map<string, ViolationRecord[]>();
  for (const v of violations) {
    const key = v.file || '(unknown)';
    const arr = map.get(key) ?? [];
    arr.push(v);
    map.set(key, arr);
  }
  return map;
}

interface DisplayRow {
  type: 'violation' | 'combined-fixed';
  violation: ViolationRecord;
  /** For combined-fixed rows, the individual violations that were merged. */
  merged?: ViolationRecord[];
}

interface ViolationOutputProps {
  violations: ViolationRecord[];
  patchByFile: Map<string, string>;
  hasFilters: boolean;
  scanType?: string;
  getRuleDescription?: (ruleId: string) => string | undefined;
  onSectionToggle?: (open: boolean) => void;
  scanId?: string;
  feedbackEnabled?: boolean;
}

export function ViolationOutput({ violations, patchByFile, hasFilters, scanType, getRuleDescription, onSectionToggle, scanId, feedbackEnabled }: ViolationOutputProps) {
  const isRemediate = scanType === 'fix' || scanType === 'remediate';
  const [sectionOpen, setSectionOpen] = useState(true);
  const toggleSection = (open: boolean) => {
    setSectionOpen(open);
    onSectionToggle?.(open);
  };
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [allCollapsed, setAllCollapsed] = useState(false);
  const [selectedViolation, setSelectedViolation] = useState<ViolationRecord | null>(null);
  const [selectedIsCombined, setSelectedIsCombined] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const groups = useMemo(() => groupByFile(violations), [violations]);

  const toggleFile = (file: string) => {
    setCollapsed(prev => ({ ...prev, [file]: !prev[file] }));
  };

  const expandAll = () => {
    const next: Record<string, boolean> = {};
    for (const key of groups.keys()) next[key] = false;
    setCollapsed(next);
    setAllCollapsed(false);
  };

  const collapseAll = () => {
    const next: Record<string, boolean> = {};
    for (const key of groups.keys()) next[key] = true;
    setCollapsed(next);
    setAllCollapsed(true);
  };

  const toggleAll = () => {
    if (allCollapsed) expandAll(); else collapseAll();
  };

  const isCollapsed = (file: string) => collapsed[file] === true;

  const selectedDiff = useMemo(() => {
    if (!selectedViolation) return undefined;
    if (selectedIsCombined) return patchByFile.get(selectedViolation.file);
    return undefined;
  }, [selectedViolation, selectedIsCombined, patchByFile]);

  const ruleTitle = (ruleId: string) => getRuleDescription?.(ruleId) || ruleId;

  const buildRows = (groupKey: string, fileViolations: ViolationRecord[]): DisplayRow[] => {
    if (!isRemediate) {
      const sorted = [...fileViolations].sort(
        (a, b) => severityOrder(severityClass(a.level, a.rule_id)) - severityOrder(severityClass(b.level, b.rule_id))
      );
      return sorted.map(v => ({ type: 'violation', violation: v }));
    }

    const fixed = fileViolations.filter(v => v.remediation_class === 1);
    const rest = fileViolations.filter(v => v.remediation_class !== 1);

    const rows: DisplayRow[] = [];

    if (fixed.length > 0) {
      const summary: ViolationRecord = {
        id: -1,
        rule_id: '',
        level: 'info',
        message: `${fixed.length} violation${fixed.length !== 1 ? 's' : ''} fixed`,
        file: groupKey,
        line: null,
        path: '',
        remediation_class: 1,
      };
      rows.push({ type: 'combined-fixed', violation: summary, merged: fixed });
    }

    const sorted = [...rest].sort(
      (a, b) => severityOrder(severityClass(a.level, a.rule_id)) - severityOrder(severityClass(b.level, b.rule_id))
    );
    for (const v of sorted) {
      rows.push({ type: 'violation', violation: v });
    }

    return rows;
  };

  return (
    <>
      <div className="apme-output-controls">
        <div className="apme-output-controls-left">
          <Button
            variant="plain"
            onClick={() => toggleSection(!sectionOpen)}
            aria-label={sectionOpen ? 'Hide results' : 'Show results'}
            icon={sectionOpen ? <AngleDownIcon /> : <AngleRightIcon />}
            size="sm"
          />
          <span
            style={{ fontSize: 13, fontWeight: 600, paddingLeft: 4, cursor: 'pointer' }}
            role="button"
            tabIndex={0}
            onClick={() => toggleSection(!sectionOpen)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleSection(!sectionOpen); }}
          >
            Results ({violations.length})
          </span>
        </div>
        {sectionOpen && (
          <div className="apme-output-controls-right">
            <Button
              variant="plain"
              onClick={toggleAll}
              aria-label={allCollapsed ? 'Expand all files' : 'Collapse all files'}
              icon={allCollapsed ? <AngleRightIcon /> : <AngleDownIcon />}
              size="sm"
            />
            <Button
              variant="plain"
              onClick={() => {
                scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
              }}
              icon={<AngleDoubleUpIcon />}
              aria-label="Scroll to top"
              size="sm"
            />
            <Button
              variant="plain"
              onClick={() => {
                const el = scrollRef.current;
                if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
              }}
              icon={<AngleDoubleDownIcon />}
              aria-label="Scroll to bottom"
              size="sm"
            />
          </div>
        )}
      </div>

      {sectionOpen && <div className="apme-output-scroll" ref={scrollRef}>
        <div className="apme-output-grid">
          {groups.size === 0 ? (
            <div className="apme-output-empty">
              No violations{hasFilters ? ' matching filters' : ' found'}.
            </div>
          ) : (
            Array.from(groups.entries()).map(([file, fileViolations]) => {
              const fixable = fileViolations.filter(v => v.remediation_class === 1);
              const rows = buildRows(file, fileViolations);

              return (
                <div className="apme-output-file-group" key={file}>
                  <div
                    className="apme-output-row apme-output-row-header"
                    role="button"
                    tabIndex={0}
                    onClick={() => toggleFile(file)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleFile(file); }}
                  >
                    <span className="apme-output-gutter">
                      {isCollapsed(file) ? <AngleRightIcon /> : <AngleDownIcon />}
                    </span>
                    <span className="apme-output-content apme-output-file-line">
                      <span className="apme-output-file-path">{file}</span>
                      <span className="apme-output-file-meta">
                        {fileViolations.length} issue{fileViolations.length !== 1 ? 's' : ''}
                        {fixable.length > 0 && (
                          <span className={isRemediate ? 'apme-badge passed' : 'apme-badge fixable'} style={{ marginLeft: 8, fontSize: 10 }}>
                            {fixable.length} {isRemediate ? 'fixed' : 'fixable'}
                          </span>
                        )}
                      </span>
                    </span>
                  </div>

                  {isCollapsed(file) && (
                    <div className="apme-output-row apme-output-row-ellipsis">
                      <span className="apme-output-gutter" />
                      <span className="apme-output-content">...</span>
                    </div>
                  )}

                  {!isCollapsed(file) && rows.map((row) => {
                    if (row.type === 'combined-fixed') {
                      return (
                        <div
                          className="apme-output-row apme-output-row-item"
                          key="combined-fixed"
                          role="button"
                          tabIndex={0}
                          onClick={() => { setSelectedViolation(row.violation); setSelectedIsCombined(true); }}
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { setSelectedViolation(row.violation); setSelectedIsCombined(true); } }}
                        >
                          <span className="apme-output-gutter apme-output-line-num" />
                          <span className="apme-output-content apme-output-violation-line">
                            <span className="apme-badge passed" style={{ fontSize: 10 }}>Fixed</span>
                            <span className="apme-output-violation-msg">
                              {row.violation.message}
                            </span>
                          </span>
                        </div>
                      );
                    }

                    const v = row.violation;
                    return (
                      <div
                        className="apme-output-row apme-output-row-item"
                        key={v.id}
                        role="button"
                        tabIndex={0}
                        onClick={() => { setSelectedViolation(v); setSelectedIsCombined(false); }}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { setSelectedViolation(v); setSelectedIsCombined(false); } }}
                      >
                        <span className="apme-output-gutter apme-output-line-num">
                          {v.line != null ? v.line : ''}
                        </span>
                        <span className="apme-output-content apme-output-violation-line">
                          <span className={`apme-severity ${severityClass(v.level, v.rule_id)}`}>
                            {severityLabel(v.level, v.rule_id)}
                          </span>
                          <span className="apme-rule-id" title={ruleTitle(v.rule_id)}>
                            {bareRuleId(v.rule_id)}
                          </span>
                          <span
                            className={tierBadgeClass(v.remediation_class, isRemediate)}
                            style={{ fontSize: 10, visibility: v.remediation_class > 0 ? 'visible' : 'hidden' }}
                          >
                            {tierLabel(v.remediation_class, isRemediate) || '\u00A0'}
                          </span>
                          <span className="apme-output-violation-msg">
                            {v.message}
                          </span>
                        </span>
                      </div>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
      </div>}

      {selectedViolation && (
        <ViolationDetailModal
          isOpen={!!selectedViolation}
          onClose={() => { setSelectedViolation(null); setSelectedIsCombined(false); }}
          violation={selectedViolation}
          diff={selectedDiff}
          getRuleDescription={getRuleDescription}
          mergedViolations={selectedIsCombined ? (groups.get(selectedViolation.file || '(unknown)')?.filter(v => v.remediation_class === 1) ?? []) : undefined}
          scanId={scanId}
          feedbackEnabled={feedbackEnabled}
        />
      )}
    </>
  );
}
