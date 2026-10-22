import type { LibraryDocument } from './api';

export interface Family {
  id: string;
  kind: LibraryDocument['kind'];
  regulator: string | null;
  visibility: LibraryDocument['visibility'];
  latest: LibraryDocument;
  versions: LibraryDocument[]; // newest first
}

/** Effective date, else publication date, else upload date: the order versions take effect. */
export function versionDate(doc: LibraryDocument): string {
  return doc.metadata.effective_date?.value || doc.metadata.publication_date?.value || doc.uploaded_at.slice(0, 10);
}

function newestFirst(a: LibraryDocument, b: LibraryDocument) {
  const byDate = versionDate(b).localeCompare(versionDate(a));
  return byDate !== 0 ? byDate : b.uploaded_at.localeCompare(a.uploaded_at);
}

export function groupFamilies(documents: LibraryDocument[]): Family[] {
  const families = new Map<string, LibraryDocument[]>();
  for (const doc of documents) families.set(doc.family_id, [...(families.get(doc.family_id) ?? []), doc]);
  return [...families.entries()]
    .map(([id, versions]) => {
      const sorted = [...versions].sort(newestFirst);
      const latest = sorted[0];
      return { id, kind: latest.kind, regulator: latest.metadata.regulator?.value ?? null, visibility: latest.visibility, latest, versions: sorted };
    })
    .sort((a, b) => lastUpload(b).localeCompare(lastUpload(a)));
}

/** Most recent upload in a family, so recently changed families list first. */
export function lastUpload(family: Pick<Family, 'versions'>) {
  return family.versions.reduce((max, v) => (v.uploaded_at > max ? v.uploaded_at : max), '');
}

export function title(doc: LibraryDocument) {
  return doc.metadata.title.value;
}

export function versionName(doc: LibraryDocument) {
  return doc.metadata.version?.value || `Uploaded ${formatDate(doc.uploaded_at)}`;
}

export function formatDate(value: string | null | undefined) {
  if (!value) return '';
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '';
  const date = new Date(value);
  return date.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

/** Families an upload may join: the caller's own, plus shared ones for administrators. */
export function joinableFamilies(families: Family[], kind: LibraryDocument['kind'], isAdmin: boolean) {
  return families.filter((f) => f.kind === kind && (f.visibility === 'organization' || (isAdmin && kind === 'regulatory')));
}
