import type React from 'react';

export interface DiffViewProps {
  diff: string;
  className?: string;
}

function classifyLine(line: string): 'add' | 'remove' | 'header' | 'context' {
  if (line.startsWith('+++') || line.startsWith('---')) return 'header';
  if (line.startsWith('@@')) return 'header';
  if (line.startsWith('+')) return 'add';
  if (line.startsWith('-')) return 'remove';
  return 'context';
}

const lineStyles: Record<string, React.CSSProperties> = {
  add: { backgroundColor: 'rgba(46, 160, 67, 0.15)', color: 'inherit' },
  remove: { backgroundColor: 'rgba(248, 81, 73, 0.15)', color: 'inherit' },
  header: { color: 'var(--pf-t--global--color--status--info--default)', fontWeight: 600 },
  context: {},
};

export function DiffView({ diff, className }: DiffViewProps) {
  if (!diff) return null;

  const lines = diff.split('\n');

  return (
    <pre className={className} style={{ margin: 0, fontSize: '0.85em', lineHeight: 1.5, overflow: 'auto' }}>
      {lines.map((line, i) => {
        const kind = classifyLine(line);
        return (
          <span key={i} style={{ display: 'block', ...lineStyles[kind], paddingLeft: 4, paddingRight: 4 }}>
            {line || '\u00A0'}
          </span>
        );
      })}
    </pre>
  );
}
