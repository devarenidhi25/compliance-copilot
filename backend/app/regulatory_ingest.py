"""Explicit, bounded ingestion of documents discovered from configured official listings."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import text

from .importer import HOSTS, official_url
from .store import Store

MAX_LISTING_PAGES = 5
MAX_DOCUMENTS = 25
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
KYC_TERMS = re.compile(r'\b(kyc|know your customer|customer due diligence|anti[- ]money laundering|money laundering|pmla)\b', re.I)


class ListingParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links = []
        self._anchor = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self._skip += 1
        if tag == 'a' and attrs.get('href'):
            self._anchor = {'url':urljoin(self.base_url, attrs['href']), 'text':[], 'rel':attrs.get('rel',''), 'title':attrs.get('title','')}

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self._skip:
            self._skip -= 1
        if tag == 'a' and self._anchor:
            self._anchor['text'] = ' '.join(' '.join(self._anchor['text']).split())
            self.links.append(self._anchor)
            self._anchor = None

    def handle_data(self, data):
        if not self._skip and self._anchor:
            self._anchor['text'].append(data)


class TextSectionsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = []
        self.title = 'Document'
        self.parts = []
        self.skip = 0
        self.heading = None

    def _flush(self):
        text_value = ' '.join(' '.join(self.parts).split())
        if text_value:
            self.sections.append((self.title, text_value))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.skip += 1
        if tag in ('h1','h2','h3','h4','h5','h6'):
            self._flush()
            self.heading = tag
            self.parts = []
        elif tag in ('p','li','tr','br') and not self.skip:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg') and self.skip:
            self.skip -= 1
        if self.heading == tag:
            heading = ' '.join(' '.join(self.parts).split())
            if heading:
                self.title = heading
            self.parts = []
            self.heading = None
        elif tag in ('p','li','tr','div') and not self.skip:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def finish(self):
        self._flush()
        return self.sections


def load_registry(path):
    registry = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(registry, dict) or not isinstance(registry.get('sources'), list):
        raise ValueError('Source registry must contain a sources array')
    for source in registry['sources']:
        if not {'id','url','regulator','category','enabled'} <= source.keys():
            raise ValueError('Each source requires id, url, regulator, category and enabled')
        if source['regulator'] not in ('RBI','SEBI'):
            raise ValueError(f"Unsupported regulator for source {source['id']}")
        official_url(source['url'])
        if HOSTS[urlsplit(source['url']).hostname] != source['regulator']:
            raise ValueError(f"Registry regulator does not match source host: {source['id']}")
    return registry


def _document_candidates(base_url, content):
    parser = ListingParser(base_url)
    parser.feed(content)
    candidates, pagination = [], []
    for link in parser.links:
        try:
            official_url(link['url'])
        except ValueError:
            continue
        title = link['text'] or link['title']
        path = urlsplit(link['url']).path.lower()
        rel = link['rel'].lower()
        if 'next' in rel or re.search(r'(^|\b)(next|older|more)($|\b)', title, re.I):
            pagination.append(link['url'])
            continue
        if not title or len(title) < 5:
            continue
        if path.endswith('.pdf') or KYC_TERMS.search(title):
            candidates.append({'url':link['url'], 'title':title})
    if not candidates and not pagination:
        raise ValueError('Listing parser found no official document or pagination links')
    return candidates, pagination


def _already_stored(store, source_url, digest):
    with store.engine.connect() as conn:
        rows = conn.execute(text('SELECT id,content_hash,metadata FROM documents')).mappings()
        for row in rows:
            metadata = json.loads(row['metadata'])
            if metadata.get('source_url', {}).get('value') == source_url and row['content_hash'] == digest:
                return row['id']
    return None


def _source_family(store, source_url):
    with store.engine.connect() as conn:
        rows = conn.execute(text('SELECT family_id,metadata FROM documents')).mappings()
        for row in rows:
            if json.loads(row['metadata']).get('source_url', {}).get('value') == source_url:
                return row['family_id']
    return None


def _fetch(client, url, retries):
    last_error = None
    for attempt in range(retries + 1):
        try:
            official_url(url)
            response = client.get(url, follow_redirects=False)
            if response.is_redirect:
                raise ValueError('Redirect refused; use the final official document URL')
            response.raise_for_status()
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ValueError('Response exceeds 20 MiB limit')
            return response
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt >= retries or isinstance(exc, ValueError):
                raise
            time.sleep(0.25 * (attempt + 1))
    raise last_error


def run_ingestion(store, registry_path, *, max_listing_pages=2, max_documents=10, client=None, request_delay=0.25):
    if not 1 <= max_listing_pages <= MAX_LISTING_PAGES:
        raise ValueError(f'max_listing_pages must be between 1 and {MAX_LISTING_PAGES}')
    if not 1 <= max_documents <= MAX_DOCUMENTS:
        raise ValueError(f'max_documents must be between 1 and {MAX_DOCUMENTS}')
    if not 0 <= request_delay <= 10:
        raise ValueError('request_delay must be between 0 and 10 seconds')
    registry = load_registry(registry_path)
    report = {'sources_checked':[], 'listing_pages_processed':0, 'documents_discovered':0,
              'documents_downloaded':0, 'documents_added':0, 'documents_updated':0,
              'duplicates_skipped':0, 'extraction_failures':[], 'unsupported_formats':[], 'failed_urls':[]}
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=20, headers={'User-Agent':'ComplianceCopilot/0.1 (bounded user-requested ingestion)'}, trust_env=False)
    try:
        discovered = []
        for source in registry['sources']:
            if not source['enabled']:
                continue
            report['sources_checked'].append(source['id'])
            queue, seen = [source['url']], set()
            pages = 0
            while queue and pages < max_listing_pages:
                listing_url = queue.pop(0)
                if listing_url in seen:
                    continue
                seen.add(listing_url)
                try:
                    response = _fetch(client, listing_url, retries=2)
                    if 'html' not in response.headers.get('content-type','').lower():
                        raise ValueError('Listing did not return HTML')
                    candidates, pagination = _document_candidates(listing_url, response.text)
                    pages += 1
                    report['listing_pages_processed'] += 1
                    for item in candidates:
                        item.update({'source_id':source['id'], 'regulator':source['regulator'], 'category':source['category']})
                        if KYC_TERMS.search(item['title']):
                            discovered.append(item)
                    queue.extend(url for url in pagination if url not in seen)
                    time.sleep(request_delay)
                except Exception as exc:
                    report['failed_urls'].append({'url':listing_url,'reason':str(exc)})
                    # A configured source whose first page cannot be parsed is explicitly reported.
                    break
        deduplicated = {item['url']:item for item in discovered}
        candidates = list(deduplicated.values())[:max_documents]
        report['documents_discovered'] = len(deduplicated)
        for item in candidates:
            try:
                response = _fetch(client, item['url'], retries=2)
                report['documents_downloaded'] += 1
                media_type = response.headers.get('content-type','').split(';',1)[0].strip().lower()
                raw = response.content
                digest = hashlib.sha256(raw).hexdigest()
                existing_id = _already_stored(store, item['url'], digest)
                if existing_id:
                    report['duplicates_skipped'] += 1
                    continue
                title = item['title'][:500]
                # Dates are left unknown unless a source-specific parser can establish
                # their meaning; a date appearing in a title may be an effective date.
                publication_date = None
                family_id = _source_family(store, item['url'])
                metadata = SimpleNamespace(title=title, kind='regulatory', regulator=item['regulator'],
                    document_type=item['category'], source_url=item['url'], publication_date=publication_date,
                    version=None, effective_date=None, family_id=family_id)
                source_meta = {'source_identifier':item['url'], 'category':item['category'],
                    'document_identifier':None, 'updated_date':None,
                    'downloaded_at':datetime.now(timezone.utc).isoformat(),
                    'ingested_at':datetime.now(timezone.utc).isoformat()}
                is_update = family_id is not None
                if 'application/pdf' in media_type or raw.startswith(b'%PDF-'):
                    result = store.ingest(raw, metadata, 'official-regulatory-library', verified_source=item['url'],
                        source_metadata={**source_meta,'original_format':'pdf'})
                elif 'text/html' in media_type:
                    parser = TextSectionsParser()
                    parser.feed(response.text)
                    sections = parser.finish()
                    try:
                        result = store.ingest_html(raw, metadata, 'official-regulatory-library', sections,
                            verified_source=item['url'], source_metadata=source_meta)
                    except ValueError as exc:
                        report['extraction_failures'].append({'url':item['url'],'reason':str(exc)})
                        continue
                else:
                    report['unsupported_formats'].append({'url':item['url'],'content_type':media_type or 'unknown'})
                    continue
                if result:
                    report['documents_updated' if is_update else 'documents_added'] += 1
            except Exception as exc:
                message = str(exc)
                if 'extract' in message.lower() or 'parse' in message.lower() or 'pdf' in message.lower():
                    report['extraction_failures'].append({'url':item['url'],'reason':message})
                else:
                    report['failed_urls'].append({'url':item['url'],'reason':message})
            finally:
                time.sleep(request_delay)
        return report
    finally:
        if owns_client:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default='datasets/official_sources.json')
    parser.add_argument('--max-listing-pages', type=int, default=2)
    parser.add_argument('--max-documents', type=int, default=10)
    parser.add_argument('--request-delay', type=float, default=0.25)
    parser.add_argument('--report', default='data/ingestion-report.json')
    args = parser.parse_args()
    if not 0 <= args.request_delay <= 10:
        parser.error('--request-delay must be between 0 and 10 seconds')
    store = Store(__import__('os').getenv('COPILOT_DB','data/corpus.sqlite3'))
    report = run_ingestion(store, args.registry, max_listing_pages=args.max_listing_pages,
                           max_documents=args.max_documents, request_delay=args.request_delay)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'report_path':str(report_path), **report}, indent=2))


if __name__ == '__main__':
    main()
