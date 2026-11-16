from __future__ import annotations

import logging
from typing import Any


def resolve_pdf_for_doi(doi: str, client: Any, logger: logging.Logger, *, email: str) -> dict | None:
    if not doi or not email:
        return None
    data = client.get_json(
        f"https://api.unpaywall.org/v2/{doi}",
        params={"email": email},
        headers={"User-Agent": "scholarly-paper-collector/1.0"},
        cache_namespace="unpaywall",
    )
    if not isinstance(data, dict) or not data.get("is_oa"):
        return None
    best = data.get("best_oa_location") or {}
    pdf_url = best.get("url_for_pdf")
    if not pdf_url:
        return {
            "status": "oa_landing_only",
            "oa_url": best.get("url"),
            "oa_source": "unpaywall",
            "license": best.get("license"),
            "local_pdf_path": None,
            "pdf_sha256": None,
            "notes": ["Unpaywall returned OA landing page but no direct PDF URL."],
        }
    logger.info("unpaywall resolved DOI=%s", doi)
    return {
        "status": "oa_pdf_available_not_downloaded",
        "oa_url": pdf_url,
        "oa_source": "unpaywall",
        "license": best.get("license"),
        "local_pdf_path": None,
        "pdf_sha256": None,
        "notes": [],
    }
