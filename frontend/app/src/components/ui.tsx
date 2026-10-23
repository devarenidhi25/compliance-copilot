import type { ReactNode } from 'react';
import type { LibraryDocument } from '../lib/api';

export function PageHead({ title, intro, actions }: { title: string; intro?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {intro && <p>{intro}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="notice error" role="alert">
      <div>{children}</div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function VisibilityBadge({ doc }: { doc: Pick<LibraryDocument, 'visibility'> }) {
  return doc.visibility === 'shared' ? <span className="badge">Shared library</span> : <span className="badge plain">Your organisation only</span>;
}

export function IndexBadge({ doc }: { doc: Pick<LibraryDocument, 'indexed'> }) {
  return doc.indexed ? (
    <span className="badge ok"><span className="dot" />Ready for AI</span>
  ) : (
    <span className="badge warn"><span className="dot" />Waiting to be indexed</span>
  );
}

const RISK: Record<string, { label: string; tone: string }> = {
  high: { label: 'High risk', tone: 'bad' },
  medium: { label: 'Medium risk', tone: 'warn' },
  low: { label: 'Low risk', tone: 'ok' },
  review: { label: 'Needs review', tone: 'dashed' },
};

export function RiskBadge({ risk }: { risk?: string }) {
  const info = RISK[risk ?? 'review'] ?? RISK.review;
  return <span className={`badge ${info.tone}`}>{info.label}</span>;
}

export function duration(seconds: number | null | undefined) {
  if (seconds == null) return '';
  const whole = Math.round(seconds);
  if (whole < 60) return `${whole} s`;
  return `${Math.floor(whole / 60)} min ${whole % 60} s`;
}
