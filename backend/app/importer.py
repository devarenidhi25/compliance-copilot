"""Single user-requested official PDF fetch; no crawling or redirects."""
from urllib.parse import urlsplit
import httpx

HOSTS = {'rbi.org.in':'RBI', 'www.rbi.org.in':'RBI', 'website.rbi.org.in':'RBI', 'rbidocs.rbi.org.in':'RBI', 'sebi.gov.in':'SEBI', 'www.sebi.gov.in':'SEBI'}


def official_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS or parts.username or parts.password or parts.port not in (None,443) or parts.fragment:
        raise ValueError('Use an HTTPS PDF URL on an explicitly supported official RBI/SEBI host')
    return HOSTS[parts.hostname]


async def fetch_pdf(url):
    regulator = official_url(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=30, trust_env=False) as client:
        async with client.stream('GET', url, headers={'User-Agent':'ComplianceCopilot/0.1 (user-requested document import)'}) as response:
            if response.is_redirect:
                raise ValueError('Redirect refused. Open the official site and copy the final direct PDF URL.')
            if response.status_code != 200:
                raise ValueError(f'Official source returned HTTP {response.status_code}; download manually if permitted')
            if 'application/pdf' not in response.headers.get('content-type','').lower():
                raise ValueError('Source is not served as a PDF. Use the official direct PDF download link.')
            data = bytearray()
            async for block in response.aiter_bytes():
                data.extend(block)
                if len(data) > 20 * 1024 * 1024:
                    raise ValueError('PDF exceeds 20 MiB limit')
    return bytes(data), regulator
