"""Version ordering and line-aligned comparison of stored page text.

Pages are compared as one aligned sequence of lines, so inserting or removing a
page produces one change instead of marking every later page as different.
Each change keeps the physical page ranges it touches in both versions.
"""
import difflib
import json

from sqlalchemy import text

from .store import collapse_whitespace

MAX_HUNK_CHARS = 3000


def stored_pages(store, document_id):
    with store.engine.connect() as conn:
        return [row[0] for row in conn.execute(text('SELECT content FROM pages WHERE document_id=:id ORDER BY number'), {'id':document_id})]


def _metadata(doc):
    meta = doc['metadata']
    return json.loads(meta) if isinstance(meta, str) else meta


def version_date(doc):
    meta = _metadata(doc)
    for key in ('effective_date', 'publication_date'):
        value = (meta.get(key) or {}).get('value')
        if value:
            return value
    return None


def order_versions(first, second):
    """Return (older, newer, swapped).

    Uses effective date, then publication date, when both versions have one;
    otherwise falls back to upload time.
    """
    a, b = version_date(first), version_date(second)
    if a and b and a != b:
        swapped = a > b
    else:
        swapped = first['uploaded_at'] > second['uploaded_at']
    return (second, first, True) if swapped else (first, second, False)


def page_lines(pages):
    return [(number, collapse_whitespace(line)) for number, content in enumerate(pages, 1)
            for line in content.splitlines() if line.strip()]


def _page_range(lines, low, high):
    if high > low:
        return [lines[low][0], lines[high - 1][0]]
    # Pure insertion/deletion: anchor to the neighbouring line's page.
    if not lines:
        return [1, 1]
    anchor = lines[low - 1][0] if low > 0 else lines[0][0]
    return [anchor, anchor]


def diff_hunks(old_pages, new_pages):
    old, new = page_lines(old_pages), page_lines(new_pages)
    matcher = difflib.SequenceMatcher(None, [line for _, line in old], [line for _, line in new])
    hunks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        hunks.append({'change':{'replace':'modified', 'delete':'removed', 'insert':'added'}[tag],
                      'old_pages':_page_range(old, i1, i2), 'new_pages':_page_range(new, j1, j2),
                      'removed':[line for _, line in old[i1:i2]], 'added':[line for _, line in new[j1:j2]]})
    return hunks


def render(hunk, limit=MAX_HUNK_CHARS):
    body = '\n'.join(['-' + line for line in hunk['removed']] + ['+' + line for line in hunk['added']])
    return body if len(body) <= limit else body[:limit] + '\n[truncated]'


def page_set(ranges):
    pages = set()
    for low, high in ranges:
        pages.update(range(low, high + 1))
    return pages
