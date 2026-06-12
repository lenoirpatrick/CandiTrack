"""Dynamic logo/favicon resolution for job sites (issue #366).

`fetch_logo_url` does a best-effort retrieval of a site's logo from its URL:
it reads the page and looks for an ``apple-touch-icon`` / ``<link rel="icon">``
/ ``og:image``. On any failure (network, parsing, no icon) it falls back to a
deterministic favicon-service URL derived from the domain.

Only the Python standard library is used (urllib + html.parser) so no extra
dependency is required.
"""

import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

USER_AGENT = "CandiTrack/0.1 (+logo-fetcher)"
TIMEOUT = 5  # seconds
MAX_BYTES = 200_000  # only the <head> matters; cap the download


def _normalize(url):
    """Ensure the URL has a scheme so urlparse/urlopen behave."""
    if not url:
        return ""
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def _domain(url):
    return urlparse(_normalize(url)).netloc


def favicon_service_url(url):
    """Deterministic favicon URL derived from the domain (no network call)."""
    domain = _domain(url)
    if not domain:
        return ""
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


class _IconParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icon = None
        self.apple_icon = None
        self.og_image = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link":
            rel = a.get("rel", "").lower()
            href = a.get("href")
            if href and "icon" in rel:
                if "apple-touch-icon" in rel:
                    self.apple_icon = self.apple_icon or href
                else:
                    self.icon = self.icon or href
        elif tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop == "og:image" and a.get("content"):
                self.og_image = self.og_image or a["content"]


def fetch_logo_url(url):
    """Best-effort absolute logo URL for ``url``; falls back to favicon service."""
    url = _normalize(url)
    if not url:
        return ""
    fallback = favicon_service_url(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            html = resp.read(MAX_BYTES).decode(charset, errors="replace")
    except Exception:
        return fallback

    parser = _IconParser()
    try:
        parser.feed(html)
    except Exception:
        return fallback

    candidate = parser.apple_icon or parser.icon or parser.og_image
    if candidate:
        return urljoin(url, candidate)
    return fallback
