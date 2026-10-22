// Find a validated quotation inside a PDF page's text items so it can be highlighted.
// Mirrors the backend's matching: whitespace is collapsed and curly quotes /
// dash variants compare equal. PDF.js splits text differently from PyMuPDF, so a
// second pass ignores whitespace entirely before giving up.

const EQUIVALENT: Record<string, string> = {
  '‘': "'", '’': "'", '‚': "'", '‛': "'", '′': "'",
  '“': '"', '”': '"', '„': '"', '″': '"',
  '‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-', '−': '-',
};

interface Normalized {
  text: string;
  positions: number[]; // index in the original string for each normalized character
}

export function normalize(value: string, dropWhitespace = false): Normalized {
  let text = '';
  const positions: number[] = [];
  let pendingSpace = false;
  for (let i = 0; i < value.length; i++) {
    const char = value[i];
    if (/\s/.test(char)) {
      pendingSpace = text.length > 0;
      continue;
    }
    if (pendingSpace && !dropWhitespace) {
      text += ' ';
      positions.push(i - 1);
    }
    pendingSpace = false;
    text += EQUIVALENT[char] ?? char;
    positions.push(i);
  }
  return { text, positions };
}

/** Indexes of the text items that contain the quotation, or null when it cannot be placed. */
export function locateQuote(items: string[], quote: string): number[] | null {
  let joined = '';
  const owner: number[] = [];
  items.forEach((item, index) => {
    for (const char of item) {
      joined += char;
      owner.push(index);
    }
    joined += ' ';
    owner.push(-1);
  });
  for (const dropWhitespace of [false, true]) {
    const haystack = normalize(joined, dropWhitespace);
    const needle = normalize(quote, dropWhitespace).text;
    if (!needle) return null;
    const start = haystack.text.indexOf(needle);
    if (start < 0) continue;
    const covered = new Set<number>();
    for (let i = start; i < start + needle.length; i++) {
      const index = owner[haystack.positions[i]];
      if (index >= 0) covered.add(index);
    }
    return [...covered].sort((a, b) => a - b);
  }
  return null;
}

/** Split plain text into segments, marking the part that matches the quotation. */
export function markQuote(content: string, quote: string): { text: string; marked: boolean }[] {
  const haystack = normalize(content);
  const needle = normalize(quote).text;
  const start = needle ? haystack.text.indexOf(needle) : -1;
  if (start < 0) return [{ text: content, marked: false }];
  const from = haystack.positions[start];
  const to = haystack.positions[start + needle.length - 1] + 1;
  return [
    { text: content.slice(0, from), marked: false },
    { text: content.slice(from, to), marked: true },
    { text: content.slice(to), marked: false },
  ].filter((part) => part.text);
}
