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
    <span className="badge good"><span className="dot" />Ready for AI</span>
  ) : (
    <span className="badge warn"><span className="dot" />Waiting to be indexed</span>
  );
}

const RISK: Record<string, { label: string; tone: string }> = {
  high: { label: 'High risk', tone: 'bad' },
  medium: { label: 'Medium risk', tone: 'warn' },
  low: { label: 'Low risk', tone: 'good' },
  review: { label: 'Needs review', tone: 'plain' },
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

export const Icon = {
  home: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5" /><path d="M5.5 10v10h13V10" /></svg>,
  ask: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" /><path d="M8.5 9.5h7M8.5 12.5h4" /></svg>,
  library: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M5 4h4v16H5zM10 4h4v16h-4z" /><path d="m15.5 5 3.8-.9 3 15.6-3.8.9z" /></svg>,
  changes: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M7 4v16M17 4v16" /><path d="m4 8 3-4 3 4M14 16l3 4 3-4" /></svg>,
  gaps: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M5 4h10l4 4v12H5z" /><path d="m9 13 2 2 4-4" /></svg>,
  audit: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></svg>,
  check: <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>,
};
