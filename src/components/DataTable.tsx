import { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  align?: 'left' | 'right';
  hide?: 'md' | 'sm';
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectedId?: string | null;
  minWidth?: number;
  emptyLabel?: string;
}

export default function DataTable<T>({
  columns, rows, rowId, onRowClick, selectedId, minWidth = 640, emptyLabel = 'NO ROWS.',
}: Props<T>) {
  return (
    <div className="ledger-wrap">
      <table className="ledger" style={{ minWidth }}>
        <thead>
          <tr>
            {columns.map(c => (
              <th key={c.key} className={`${c.align === 'right' ? 'r' : ''} ${c.hide ? `hide-${c.hide}` : ''}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr className="empty"><td colSpan={columns.length}>{emptyLabel}</td></tr>
          )}
          {rows.map(row => {
            const id = rowId(row);
            return (
              <tr
                key={id}
                className={`${selectedId === id ? 'sel ' : ''}${onRowClick ? 'clickable' : ''}`}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map(c => (
                  <td key={c.key} className={`${c.align === 'right' ? 'r' : ''} ${c.hide ? `hide-${c.hide}` : ''}`}>
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? '')}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
