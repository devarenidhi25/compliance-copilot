import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { useLoad } from './hooks';
import { api, type Library, type LibraryDocument } from './lib/api';
import { groupFamilies, type Family } from './lib/library';

interface LibraryContextValue {
  library: Library | null;
  families: Family[];
  byId: Map<string, LibraryDocument>;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

const LibraryContext = createContext<LibraryContextValue | null>(null);

export function LibraryProvider({ children }: { children: ReactNode }) {
  const { data, error, loading, reload } = useLoad(api.library);
  const value = useMemo(() => {
    const documents = data?.documents ?? [];
    return { library: data, families: groupFamilies(documents), byId: new Map(documents.map((d) => [d.id, d])), loading, error, reload };
  }, [data, error, loading, reload]);
  return <LibraryContext.Provider value={value}>{children}</LibraryContext.Provider>;
}

export function useLibrary() {
  const value = useContext(LibraryContext);
  if (!value) throw new Error('useLibrary must be used inside LibraryProvider');
  return value;
}

export interface SourceTarget {
  documentId: string;
  page: number;
  quote?: string;
  section?: string | null;
  /** The finding number shown beside the highlight on the source page. */
  label?: number;
}

interface SourceContextValue {
  target: SourceTarget | null;
  open: (target: SourceTarget) => void;
  close: () => void;
}

const SourceContext = createContext<SourceContextValue | null>(null);

export function SourceProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<SourceTarget | null>(null);
  return <SourceContext.Provider value={{ target, open: setTarget, close: () => setTarget(null) }}>{children}</SourceContext.Provider>;
}

export function useSource() {
  const value = useContext(SourceContext);
  if (!value) throw new Error('useSource must be used inside SourceProvider');
  return value;
}
