import { ReactNode } from 'react';

interface Props {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  pad?: boolean;
}

export default function BentoCard({ title, right, children, className = '', pad = true }: Props) {
  return (
    <section className={`panel ${className}`}>
      {(title || right) && (
        <header className="panel-head">
          <p className="eyebrow">{title}</p>
          {right}
        </header>
      )}
      <div className={pad ? 'panel-body' : ''}>{children}</div>
    </section>
  );
}
