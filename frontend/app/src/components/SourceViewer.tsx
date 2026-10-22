import { useEffect, useRef, useState } from 'react';
import * as pdfjs from 'pdfjs-dist';
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import type { TextItem } from 'pdfjs-dist/types/src/display/api';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { api } from '../lib/api';
import { locateQuote, markQuote } from '../lib/quote';
import { useLibrary, useSource, type SourceTarget } from '../context';
import { ErrorNote } from './ui';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

// Each document is downloaded once per session and reused between citations.
const documents = new Map<string, Promise<PDFDocumentProxy>>();
function loadPdf(documentId: string) {
  if (!documents.has(documentId)) {
    const loading = api.sourceFile(documentId).then((data) => pdfjs.getDocument({ data }).promise);
    loading.catch(() => documents.delete(documentId));
    documents.set(documentId, loading);
  }
  return documents.get(documentId)!;
}

interface Mark { left: number; top: number; width: number; height: number }

function PdfPage({ target, onPageCount }: { target: SourceTarget; onPageCount: (n: number) => void }) {
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'not-found' | 'error'>('loading');
  const [error, setError] = useState('');
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = frame.current?.parentElement;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!width) return;
    let cancelled = false;
    let page: PDFPageProxy | null = null;
    setStatus('loading');
    (async () => {
      try {
        const pdf = await loadPdf(target.documentId);
        if (cancelled) return;
        onPageCount(pdf.numPages);
        page = await pdf.getPage(Math.min(Math.max(target.page, 1), pdf.numPages));
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: width / base.width });
        const ratio = window.devicePixelRatio || 1;
        const node = canvas.current!;
        node.width = Math.floor(viewport.width * ratio);
        node.height = Math.floor(viewport.height * ratio);
        frame.current!.style.width = `${viewport.width}px`;
        frame.current!.style.height = `${viewport.height}px`;
        await page.render({ canvasContext: node.getContext('2d')!, viewport: page.getViewport({ scale: (width / base.width) * ratio }) }).promise;
        if (cancelled) return;
        if (!target.quote) {
          setMarks([]);
          setStatus('ready');
          return;
        }
        const content = await page.getTextContent();
        const items = content.items.filter((item): item is TextItem => 'str' in item);
        const found = locateQuote(items.map((item) => item.str), target.quote);
        if (!found) {
          setMarks([]);
          setStatus('not-found');
          return;
        }
        setMarks(found.map((index) => {
          const item = items[index];
          const t = pdfjs.Util.transform(viewport.transform, item.transform);
          const height = Math.hypot(t[2], t[3]);
          return { left: t[4], top: t[5] - height, width: item.width * viewport.scale, height: height * 1.15 };
        }));
        setStatus('ready');
      } catch (exc) {
        if (cancelled) return;
        setError(exc instanceof Error ? exc.message : String(exc));
        setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
      page?.cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.documentId, target.page, target.quote, width]);

  useEffect(() => {
    if (marks.length) frame.current?.querySelector('.pdf-mark')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [marks]);

  return (
    <>
      {status === 'error' && <ErrorNote>The source file could not be opened: {error}</ErrorNote>}
      {status === 'not-found' && (
        <div className="notice warn" style={{ marginBottom: 12 }}>
          The quotation was validated against this page's stored text, but it could not be pinpointed in the PDF's own text layer. Read it on the page below.
        </div>
      )}
      <div className="pdf-page" ref={frame} aria-busy={status === 'loading'}>
        <canvas ref={canvas} aria-label={`Page ${target.page} of the source document`} />
        {marks.map((mark, i) => (
          <span key={i} className="pdf-mark" style={{ left: mark.left, top: mark.top, width: mark.width, height: mark.height }} />
        ))}
      </div>
    </>
  );
}

function TextSource({ target }: { target: SourceTarget }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.chunks(target.documentId)
      .then((chunks) => {
        const page = chunks.filter((c) => c.page === target.page);
        // Chunks overlap by design; rebuild the section from non-overlapping starts.
        setText(page.map((c, i) => (i === 0 ? c.content : c.content.slice(200))).join(''));
      })
      .catch((exc) => setError(String(exc.message ?? exc)));
  }, [target.documentId, target.page]);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (text === null) return <p className="muted">Loading the section…</p>;
  return (
    <div className="text-source">
      {markQuote(text, target.quote ?? '').map((part, i) => (part.marked ? <mark key={i} className="hit">{part.text}</mark> : <span key={i}>{part.text}</span>))}
    </div>
  );
}

export function SourcePane() {
  const { target, open, close } = useSource();
  const { byId } = useLibrary();
  const [pages, setPages] = useState(0);
  if (!target) return null;
  const doc = byId.get(target.documentId);
  const isHtml = doc?.metadata.original_format?.value === 'html';
  const go = (page: number) => open({ documentId: target.documentId, page, quote: page === target.page ? target.quote : undefined });

  return (
    <aside className="source-pane" aria-label="Source document">
      <div className="source-head">
        <div className="row">
          <h2>{doc?.metadata.title.value ?? 'Source document'}</h2>
          <button className="button quiet small" onClick={close}>Close</button>
        </div>
        <div className="row">
          <span className="muted small-text">
            {isHtml ? `Section: ${target.section ?? target.page}` : `Page ${target.page}${pages ? ` of ${pages}` : ''}`}
          </span>
          {!isHtml && (
            <span className="row" style={{ gap: 4 }}>
              <button className="button small" disabled={target.page <= 1} onClick={() => go(target.page - 1)}>Previous page</button>
              <button className="button small" disabled={!!pages && target.page >= pages} onClick={() => go(target.page + 1)}>Next page</button>
            </span>
          )}
        </div>
        {target.quote && <p className="source-quote"><span className="quote-mark">{target.quote}</span></p>}
      </div>
      <div className="source-body">
        {isHtml ? <TextSource target={target} /> : <PdfPage key={target.documentId} target={target} onPageCount={setPages} />}
      </div>
    </aside>
  );
}
