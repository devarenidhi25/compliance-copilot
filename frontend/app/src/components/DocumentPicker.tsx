import type { LibraryDocument } from '../lib/api';
import { formatDate, versionName } from '../lib/library';

interface Props {
  documents: LibraryDocument[];
  selected: string[];
  onChange: (ids: string[]) => void;
  max: number;
  label: string;
}

/** Choose up to `max` documents by name; unindexed documents are shown but cannot be chosen. */
export function DocumentPicker({ documents, selected, onChange, max, label }: Props) {
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);
  return (
    <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend style={{ fontWeight: 600, color: 'var(--ink)', fontSize: 14, marginBottom: 6 }}>{label}</legend>
      <div className="picker">
        {documents.map((doc) => {
          const checked = selected.includes(doc.id);
          const disabled = !doc.indexed || (!checked && selected.length >= max);
          return (
            <label key={doc.id} className={disabled && !checked ? 'disabled' : ''}>
              <input type="checkbox" checked={checked} disabled={disabled && !checked} onChange={() => toggle(doc.id)} />
              <div>
                <strong>{doc.metadata.title.value}</strong>
                <span>
                  {[doc.metadata.regulator?.value, versionName(doc), doc.metadata.effective_date?.value ? `effective ${formatDate(doc.metadata.effective_date.value)}` : null]
                    .filter(Boolean).join(', ')}
                  {!doc.indexed && ' — waiting to be indexed'}
                </span>
              </div>
            </label>
          );
        })}
      </div>
      <small className="muted">{selected.length} of {max} selected</small>
    </fieldset>
  );
}
