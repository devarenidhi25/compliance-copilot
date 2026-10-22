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
from .paths import DEFAULT_INGESTION_REPORT, DEFAULT_REGISTRY, corpus_path
from .store import Store

MAX_LISTING_PAGES = 5
MAX_DOCUMENTS = 25
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
# Only unambiguous pagination labels; generic words like 'more' ('Read more') are content links.
PAGINATION_TEXT = re.compile(r'^(next|next page|older|older entries|\u203a|\u00bb|>|>>)$', re.I)
PAGE_NUMBER = re.compile(r'^\d{1,3}$')
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
            href = attrs['href'].strip()
            url = href if href.lower().startswith('javascript:') else urljoin(self.base_url, href)
            self._anchor = {'url':url, 'text':[], 'rel':attrs.get('rel') or '', 'title':attrs.get('title') or ''}

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


def _is_pagination(link, title):
    return 'next' in link['rel'].lower().split() or bool(PAGINATION_TEXT.match(title))


def _document_candidates(base_url, content):
    """Return (document candidates, followable pagination URLs, unfollowable postback pagination labels)."""
    parser = ListingParser(base_url)
    parser.feed(content)
    candidates, pagination, postback = [], [], []
    for link in parser.links:
        title = (link['text'] or link['title']).strip()
        if link['url'].lower().startswith('javascript:'):
            # ASP.NET listings (e.g. RBI) paginate with __doPostBack form posts,
            # which this crawler does not submit; report them instead of ignoring.
            if '__dopostback' in link['url'].lower() and (_is_pagination(link, title) or PAGE_NUMBER.match(title)):
                postback.append(title)
            continue
        try:
            official_url(link['url'])
        except ValueError:
            continue
        if _is_pagination(link, title):
            pagination.append(link['url'])
            continue
        if not title or len(title) < 5:
            continue
        path = urlsplit(link['url']).path.lower()
        if path.endswith('.pdf') or KYC_TERMS.search(title):
            candidates.append({'url':link['url'], 'title':title})
    if not candidates and not pagination:
        detail = ' (pagination uses ASP.NET postback, which is not followed)' if postback else ''
        raise ValueError('Listing parser found no official document or pagination links' + detail)
    return candidates, pagination, postback


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


def _download(client, url):
    """Stream a response, aborting as soon as it exceeds the size limit."""
    with client.stream('GET', url, follow_redirects=False) as response:
        if response.is_redirect:
            raise ValueError('Redirect refused; use the final official document URL')
        response.raise_for_status()
        declared = response.headers.get('content-length')
        if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
            raise ValueError('Response exceeds 20 MiB limit')
        data = bytearray()
        for block in response.iter_bytes():
            data.extend(block)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError('Response exceeds 20 MiB limit')
        # Body is already decoded; drop encoding headers so it is not decoded twice.
        headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')]
        return httpx.Response(response.status_code, headers=headers, content=bytes(data), request=response.request)


def _fetch(client, url, retries):
    for attempt in range(retries + 1):
        try:
            official_url(url)
            return _download(client, url)
        except httpx.HTTPStatusError as exc:
            # Client errors (404, 403) will not succeed on retry.
            if attempt >= retries or exc.response.status_code < 500:
                raise
        except httpx.TransportError:
            if attempt >= retries:
                raise
        time.sleep(0.25 * (attempt + 1))


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
              'duplicates_skipped':0, 'extraction_failures':[], 'unsupported_formats':[], 'failed_urls':[],
              'unfollowed_pagination':[]}
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
                    candidates, pagination, postback = _document_candidates(listing_url, response.text)
                    if postback:
                        report['unfollowed_pagination'].append({'url':listing_url, 'links':postback,
                            'reason':'ASP.NET postback pagination is not followed; only this page was read'})
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
                try:
                    response = _fetch(client, item['url'], retries=2)
                except (httpx.HTTPError, ValueError) as exc:
                    report['failed_urls'].append({'url':item['url'], 'reason':f'{type(exc).__name__}: {exc}'})
                    continue
                report['documents_downloaded'] += 1
                media_type = response.headers.get('content-type','').split(';',1)[0].strip().lower()
                raw = response.content
                digest = hashlib.sha256(raw).hexdigest()
                if _already_stored(store, item['url'], digest):
                    report['duplicates_skipped'] += 1
                    continue
                # Dates are left unknown unless a source-specific parser can establish
                # their meaning; a date appearing in a title may be an effective date.
                family_id = _source_family(store, item['url'])
                metadata = SimpleNamespace(title=item['title'][:500], kind='regulatory', regulator=item['regulator'],
                    document_type=item['category'], source_url=item['url'], publication_date=None,
                    version=None, effective_date=None, family_id=family_id)
                now = datetime.now(timezone.utc).isoformat()
                source_meta = {'source_identifier':item['url'], 'category':item['category'],
                    'document_identifier':None, 'updated_date':None, 'downloaded_at':now, 'ingested_at':now}
                try:
                    if 'application/pdf' in media_type or raw.startswith(b'%PDF-'):
                        result = store.ingest(raw, metadata, 'official-regulatory-library', verified_source=item['url'],
                            source_metadata={**source_meta,'original_format':'pdf'}, shared=True)
                    elif 'text/html' in media_type:
                        parser = TextSectionsParser()
                        parser.feed(response.text)
                        result = store.ingest_html(raw, metadata, 'official-regulatory-library', parser.finish(),
                            verified_source=item['url'], source_metadata=source_meta, shared=True)
                    else:
                        report['unsupported_formats'].append({'url':item['url'],'content_type':media_type or 'unknown'})
                        continue
                except ValueError as exc:
                    report['extraction_failures'].append({'url':item['url'],'reason':str(exc)})
                    continue
                if result:
                    report['documents_updated' if family_id is not None else 'documents_added'] += 1
            except Exception as exc:
                report['failed_urls'].append({'url':item['url'], 'reason':f'Unexpected {type(exc).__name__}: {exc}'})
            finally:
                time.sleep(request_delay)
        return report
    finally:
        if owns_client:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default=str(DEFAULT_REGISTRY))
    parser.add_argument('--max-listing-pages', type=int, default=2)
    parser.add_argument('--max-documents', type=int, default=10)
    parser.add_argument('--request-delay', type=float, default=0.25)
    parser.add_argument('--report', default=str(DEFAULT_INGESTION_REPORT))
    args = parser.parse_args()
    if not 0 <= args.request_delay <= 10:
        parser.error('--request-delay must be between 0 and 10 seconds')
    store = Store(corpus_path())
    report = run_ingestion(store, args.registry, max_listing_pages=args.max_listing_pages,
                           max_documents=args.max_documents, request_delay=args.request_delay)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'report_path':str(report_path), **report}, indent=2))


if __name__ == '__main__':
    main()
