"""Choose one *destination* from duplicate Soltech next-page controls.

Two equivalent 'Następne produkty' links are normal (e.g., different
responsive controls). Conflicting destinations remain a hard failure.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit


def _absolute_catalog_url(page_url: str, href: str) -> str:
    """Normalize a catalog link, rejecting empty, unsafe, or off-site URLs."""
    href = (href or "").strip()
    if not href:
        raise RuntimeError("Link do kolejnej strony nie ma href")
    base = urlsplit(page_url)
    target = urlsplit(urljoin(page_url, href))
    if (target.scheme not in ("http", "https")
            or target.scheme != base.scheme
            or target.netloc.lower() != base.netloc.lower()):
        raise RuntimeError("Paginacja prowadzi poza aktualny sklep lub uzywa niedozwolonego URL")
    return urlunsplit((target.scheme, target.netloc, target.path, target.query, ""))


def next_catalog_url(page, current_page: int) -> str | None:
    """Return next URL or None for a genuine last page.

    Multiple matching links are accepted only if their resolved URLs agree.
    Do not silently choose `.first` when destinations conflict.
    """
    candidates = page.get_by_role("link", name="Następne produkty", exact=True)
    count = candidates.count()
    if count == 0:
        # A broken anchor without href is not exposed as a link by ARIA.
        if page.get_by_text("Następne produkty", exact=True).count() > 0:
            raise RuntimeError("Wykryto 'Następne produkty', ale brak prawidlowego linku")
        return None

    urls: set[str] = set()
    for index in range(count):
        href = candidates.nth(index).get_attribute("href")
        urls.add(_absolute_catalog_url(page.url, href))

    if len(urls) != 1:
        # Useful diagnostics without hiding an actual markup regression.
        raise RuntimeError(
            f"Niejednoznaczna paginacja na stronie {current_page}: "
            f"{count} linkow wskazuje {len(urls)} roznych adresow: {sorted(urls)}"
        )
    return next(iter(urls))
