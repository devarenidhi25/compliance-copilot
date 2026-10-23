// Typed client for the Compliance Copilot backend.
// Every request carries the session's access code; name and role are sent as
// display values for the audit trail (they are not authentication).

export type Role = 'compliance_officer' | 'legal' | 'risk' | 'executive';

export interface Session {
  token: string;
  name: string;
  role: Role;
  organization: string;
  isAdmin: boolean;
}

export interface Field<T = string | null> {
  value: T;
  status: 'user_supplied' | 'verified' | 'unknown';
  verification?: string;
}

export interface DocumentMeta {
  title: Field<string>;
  regulator: Field;
  document_type: Field;
  source_url: Field;
  publication_date: Field;
  version: Field;
  effective_date: Field;
  original_format?: Field;
  [key: string]: Field<unknown> | undefined;
}

export interface LibraryDocument {
  id: string;
  family_id: string;
  organization: string | null;
  kind: 'regulatory' | 'internal';
  metadata: DocumentMeta;
  content_hash: string;
  uploaded_at: string;
  visibility: 'shared' | 'organization';
  page_count: number;
  indexed: boolean;
}

export interface Library {
  documents: LibraryDocument[];
  index: { state: 'ready' | 'pending' | 'unavailable'; message: string | null };
  is_admin: boolean;
}

export interface Citation {
  document_id: string;
  chunk_id: string;
  page: number;
  quote: string;
  section?: string;
  source_url: Field;
  /** The words in the quote that answer the question (checked to appear in the quote). */
  key_phrase?: string;
}

export interface Focus {
  answer: string | null;
  highlights: string[];
  labels: Record<string, string>;
  note: string;
}

export interface ResultItem {
  statement: string;
  interpretation: string;
  citations: Citation[];
  assessment: string | null;
  review_status: string;
  status_label?: string;
  risk?: 'low' | 'medium' | 'high' | 'review';
}

export interface GapSummary {
  score: number | null;
  assessed_items: number;
  not_assessed_items: number;
  high_risk_items: number;
  counts: Record<string, number>;
  method: string;
}

export interface AIResult {
  task: Task;
  items: ResultItem[];
  rejected_items: { index: number; reason: string; statement: string | null }[];
  notes: string[];
  model: string;
  generation_seconds: number;
  evidence_excerpts: number;
  limitations: string;
  audit_id?: string;
  gap_summary?: GapSummary;
  focus?: Focus | null;
  focus_seconds?: number;
}

export type Task = 'qa' | 'comparison' | 'gap_analysis' | 'checklist';
export type Stage = 'queued' | 'retrieving' | 'drafting' | 'verifying' | 'summarising' | 'completed';

export interface Job {
  id: string;
  task: Task;
  question: string;
  document_ids: string[];
  state: 'queued' | 'running' | 'completed' | 'failed';
  stage: Stage;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: AIResult | null;
  error: string | null;
  audit_id: string;
  queue_position: number | null;
  elapsed_seconds: number | null;
}

export interface Change {
  change: 'added' | 'removed' | 'modified';
  old_pages: [number, number];
  new_pages: [number, number];
  removed: string[];
  added: string[];
  truncated: boolean;
}

export interface Comparison {
  older: LibraryDocument;
  newer: LibraryDocument;
  reordered: boolean;
  changes: Change[];
  total_changes: number;
  counts: { added: number; removed: number; modified: number };
}

export interface AuditEntry {
  id: string;
  created_at: string;
  finished_at: string | null;
  user_name: string | null;
  user_role: Role | null;
  role_label: string | null;
  task: Task;
  question: string;
  document_ids: string[];
  status: 'queued' | 'completed' | 'failed';
  model: string | null;
  generation_seconds: number | null;
  accepted: number | null;
  rejected: number | null;
  error: string | null;
  result?: AIResult | null;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

let current: Session | null = null;
export function setApiSession(session: Session | null) {
  current = session;
}

async function request(path: string, init: RequestInit = {}, token = current?.token): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (current) {
    headers.set('X-Copilot-User', current.name);
    headers.set('X-Copilot-Role', current.role);
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const raw = await response.text();
    let message = `Request failed (${response.status})`;
    try {
      const body = JSON.parse(raw);
      message = typeof body.detail === 'string' ? body.detail : body.detail ? JSON.stringify(body.detail) : message;
    } catch {
      if (raw.trim()) message = raw.slice(0, 300);
    }
    if (response.status === 401) message = 'That access code was not recognised. Check it with your administrator.';
    throw new ApiError(message, response.status);
  }
  return response;
}

const json = async <T>(path: string, init?: RequestInit, token?: string) => (await request(path, init, token)).json() as Promise<T>;
const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const api = {
  me: (token: string) => json<{ organization: string; is_admin: boolean; roles: Record<Role, string> }>('/api/app/me', {}, token),
  library: () => json<Library>('/api/app/library'),
  upload: (file: File, metadata: Record<string, unknown>) => {
    const body = new FormData();
    body.append('file', file);
    body.append('metadata', JSON.stringify(metadata));
    return json<LibraryDocument>('/api/documents/upload', { method: 'POST', body });
  },
  sourceFile: async (documentId: string) => (await request(`/api/documents/${documentId}/pdf`)).arrayBuffer(),
  chunks: (documentId: string) => json<{ id: string; page: number; content: string; section: string | null }[]>(`/api/documents/${documentId}/chunks`),
  startJob: (task: Task, question: string, documentIds: string[]) => json<Job>('/api/app/jobs', post({ task, question, document_ids: documentIds })),
  job: (id: string) => json<Job>(`/api/app/jobs/${id}`),
  compare: (a: string, b: string) => json<Comparison>(`/api/app/compare?${new URLSearchParams({ a, b })}`),
  audit: (limit = 50) => json<{ entries: AuditEntry[] }>(`/api/app/audit?limit=${limit}`),
  auditEntry: (id: string) => json<AuditEntry>(`/api/app/audit/${id}`),
  startIndexSync: () => json<IndexJob>('/api/admin/index/sync', { method: 'POST' }),
  indexJob: () => json<IndexJob>('/api/admin/index/sync'),
};

export interface IndexJob {
  state: 'idle' | 'running' | 'complete' | 'failed';
  started_at?: string;
  finished_at?: string;
  error?: string;
  result?: { documents: number };
}
