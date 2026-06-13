"""Favicon resolution for job sites (issues #366, #27).

`favicon_service_url` builds a deterministic favicon URL from a site's domain
(no network call). It is used to load a site's logo by default when the site is
saved (see `tracking/forms.py`).

Only the Python standard library is used (urllib.parse) so no extra dependency
is required.
"""

from urllib.parse import urlparse


def _normalize(url):
    """Ensure the URL has a scheme so urlparse behaves."""
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
