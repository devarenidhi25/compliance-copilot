import { describe, expect, it } from 'vitest';
import { locateQuote, markQuote, normalize } from './quote';
import { groupFamilies, joinableFamilies, versionDate } from './library';
import type { LibraryDocument } from './api';

describe('quote matching', () => {
  it('collapses whitespace and maps typographic variants like the backend', () => {
    expect(normalize('  The  regulated\n entity “shall” – act ').text).toBe('The regulated entity "shall" - act');
  });

  it('finds a quotation spread across PDF text items', () => {
    const items = ['The listed entity shall first', 'disclose to the stock', 'exchange(s) all events', 'unrelated footer'];
    expect(locateQuote(items, 'shall first disclose to the stock exchange(s)')).toEqual([0, 1, 2]);
  });

  it('falls back to ignoring whitespace when PDF.js splits words', () => {
    const items = ['thirty min', 'utes from the clo', 'sure of the meeting'];
    expect(locateQuote(items, 'thirty minutes from the closure of the meeting')).toEqual([0, 1, 2]);
  });

  it('returns null when the quotation is not on the page', () => {
    expect(locateQuote(['nothing relevant here'], 'within ninety days')).toBeNull();
  });

  it('marks the original span inside plain text', () => {
    const parts = markQuote('Intro.  The bank  must\nverify identity. End.', 'The bank must verify identity.');
    expect(parts).toEqual([
      { text: 'Intro.  ', marked: false },
      { text: 'The bank  must\nverify identity.', marked: true },
      { text: ' End.', marked: false },
    ]);
  });
});

const doc = (id: string, family: string, uploaded: string, extra: Partial<Record<string, string>> = {}, visibility: 'shared' | 'organization' = 'shared'): LibraryDocument => ({
  id, family_id: family, organization: visibility === 'shared' ? null : 'alpha', kind: 'regulatory', content_hash: id, uploaded_at: uploaded, visibility, page_count: 1, indexed: true,
  metadata: {
    title: { value: `Doc ${id}`, status: 'user_supplied' }, regulator: { value: 'RBI', status: 'user_supplied' },
    document_type: { value: null, status: 'unknown' }, source_url: { value: null, status: 'unknown' },
    publication_date: { value: extra.publication ?? null, status: 'unknown' }, version: { value: extra.version ?? null, status: 'unknown' },
    effective_date: { value: extra.effective ?? null, status: 'unknown' },
  },
});

describe('version families', () => {
  it('groups versions and orders them by effective date, newest first', () => {
    const families = groupFamilies([
      doc('a', 'f1', '2026-05-01T00:00:00', { effective: '2024-01-01' }),
      doc('b', 'f1', '2026-04-01T00:00:00', { effective: '2025-06-01' }),
      doc('c', 'f2', '2026-06-01T00:00:00'),
    ]);
    expect(families.map((f) => f.id)).toEqual(['f2', 'f1']); // f2 has the most recent upload
    expect(families[1].versions.map((v) => v.id)).toEqual(['b', 'a']);
    expect(families[1].latest.id).toBe('b');
    expect(versionDate(families[0].latest)).toBe('2026-06-01');
  });

  it('lets only administrators add to shared families', () => {
    const families = groupFamilies([doc('a', 'shared', '2026-01-01T00:00:00'), doc('b', 'mine', '2026-01-02T00:00:00', {}, 'organization')]);
    expect(joinableFamilies(families, 'regulatory', false).map((f) => f.id)).toEqual(['mine']);
    expect(joinableFamilies(families, 'regulatory', true).map((f) => f.id).sort()).toEqual(['mine', 'shared']);
  });
});

import { markPhrases } from './quote';

describe('answer highlights', () => {
  it('marks each phrase once, in order, without overlaps', () => {
    expect(markPhrases('Within 30 minutes or 12 hours.', ['12 hours', '30 minutes', '30 min'])).toEqual([
      { text: 'Within ', marked: false },
      { text: '30 minutes', marked: true },
      { text: ' or ', marked: false },
      { text: '12 hours', marked: true },
      { text: '.', marked: false },
    ]);
    expect(markPhrases('No match here', ['absent'])).toEqual([{ text: 'No match here', marked: false }]);
  });
});
