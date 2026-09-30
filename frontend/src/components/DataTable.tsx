import { ReactNode } from 'react';
import { Skeleton } from './Skeleton';

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  align?: 'left' | 'right';
  hide?: 'md' | 'sm';
  width?: string | number;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectedId?: string | null;
  minWidth?: number;
  emptyLabel?: string;
  loading?: boolean;
  loadingRows?: number;
}

export default function DataTable<T>({
  columns,
  rows,
  rowId,
  onRowClick,
  selectedId,
  minWidth = 640,
  emptyLabel = 'NO ROWS.',
  loading = false,
  loadingRows = 5,
}: Props<T>) {
  return (
    <div className="ledger-wrap">
      <table className="ledger" style={{ minWidth }}>
        <thead>
          <tr>
            {columns.map(c => (
              <th
                key={c.key}
                className={`${c.align === 'right' ? 'r' : ''} ${c.hide ? `hide-${c.hide}` : ''}`}
                style={{ width: c.width }}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: loadingRows }).map((_, rIdx) => (
              <tr key={`skeleton-row-${rIdx}`} className="border-b border-line/40">
                {columns.map((c, cIdx) => (
                  <td
                    key={`skeleton-cell-${rIdx}-${cIdx}`}
                    className={`${c.align === 'right' ? 'r' : ''} ${c.hide ? `hide-${c.hide}` : ''}`}
                  >
                    <Skeleton
                      height={14}
                      width={
                        c.align === 'right'
                          ? '60%'
                          : cIdx === 0
                          ? '80%'
                          : cIdx === 1
                          ? '65%'
                          : '75%'
                      }
                      className={c.align === 'right' ? 'ml-auto' : ''}
                    />
                  </td>
                ))}
              </tr>
            ))
          ) : rows.length === 0 ? (
            <tr className="empty">
              <td colSpan={columns.length}>{emptyLabel}</td>
            </tr>
          ) : (
            rows.map((row, idx) => {
              const id = rowId(row);
              return (
                <tr
                  key={id}
                  className={`stagger-row ${selectedId === id ? 'sel ' : ''}${
                    onRowClick ? 'clickable' : ''
                  }`}
                  style={{
                    animationDelay: `${Math.min(idx * 35, 350)}ms`,
                  }}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {columns.map(c => (
                    <td
                      key={c.key}
                      className={`${c.align === 'right' ? 'r' : ''} ${
                        c.hide ? `hide-${c.hide}` : ''
                      }`}
                    >
                      {c.render
                        ? c.render(row)
                        : String((row as Record<string, unknown>)[c.key] ?? '')}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
