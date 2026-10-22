import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Job } from './lib/api';

/** Load data once (and on demand), keeping the last good value while reloading. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loader = useRef(load);
  loader.current = load;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loader.current());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void reload(), deps);
  return { data, error, loading, reload };
}

/**
 * Track an AI job by id. The id is remembered per page in sessionStorage, so the
 * reviewer can leave the page during a slow generation and find the result on return.
 */
export function useJob(storageKey: string) {
  const key = `compliance-copilot-job-${storageKey}`;
  const [jobId, setJobId] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  });
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.job(jobId);
        if (cancelled) return;
        setJob(next);
        setError(null);
        if (next.state === 'queued' || next.state === 'running') timer = setTimeout(poll, 1500);
      } catch (exc) {
        if (cancelled) return;
        // A restarted server forgets running jobs; the audit trail keeps finished ones.
        setError(exc instanceof Error ? exc.message : String(exc));
        forget();
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const remember = (id: string | null) => {
    try {
      if (id) sessionStorage.setItem(key, id);
      else sessionStorage.removeItem(key);
    } catch {
      /* storage unavailable: tracking still works while the page stays open */
    }
  };

  const start = (next: Job) => {
    remember(next.id);
    setJob(next);
    setError(null);
    setJobId(next.id);
  };

  const forget = () => {
    remember(null);
    setJobId(null);
    setJob(null);
  };

  const busy = job?.state === 'queued' || job?.state === 'running';
  return { job, error, busy, start, forget, setError };
}
