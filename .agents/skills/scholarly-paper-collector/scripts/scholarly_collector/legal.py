from __future__ import annotations

from urllib.parse import urlparse


FORBIDDEN_HOST_PARTS = (
    "sci-hub",
    "libgen",
    "library.lol",
    "annas-archive",
    "z-library",
    "zlib",
)

ALLOWED_PROVENANCE = {
    "arxiv",
    "openalex",
    "semantic_scholar",
    "unpaywall",
    "publisher_oa",
    "institutional_repository",
    "fixture",
}


def is_forbidden_url(url: str | None) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return any(part in host for part in FORBIDDEN_HOST_PARTS)


def is_pdf_like(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and (parsed.path.lower().endswith(".pdf") or "/pdf" in parsed.path.lower())


def legal_pdf_decision(url: str | None, provenance: str | None) -> tuple[bool, str]:
    if not url:
        return False, "missing PDF URL"
    if is_forbidden_url(url):
        return False, "URL belongs to a forbidden source family"
    if provenance not in ALLOWED_PROVENANCE:
        return False, f"untrusted OA provenance: {provenance or 'unknown'}"
    if not is_pdf_like(url):
        return False, "URL does not look like a direct PDF endpoint"
    return True, "allowed legal OA PDF"
