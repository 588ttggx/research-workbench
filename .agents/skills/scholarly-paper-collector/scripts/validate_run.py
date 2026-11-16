#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scholarly_collector.report import REQUIRED_HEADINGS, validate_analysis
from scholarly_collector.schema import read_index
from scholarly_collector.legal import ALLOWED_PROVENANCE, is_forbidden_url


VALID_ACCESS_STATUSES = {
    "downloaded_oa_pdf",
    "oa_pdf_available_not_downloaded",
    "oa_landing_only",
    "metadata_only_no_legal_pdf",
    "download_failed_retryable",
    "download_blocked_by_policy",
}


def validate_index_legal_fields(index: dict, attachments: Path) -> list[str]:
    errors: list[str] = []
    for paper in index.get("papers", []):
        prefix = paper.get("paper_id") or paper.get("title") or "unknown paper"
        access = paper.get("access")
        if not isinstance(access, dict):
            errors.append(f"{prefix}: missing access object")
            continue
        status = access.get("status")
        if status not in VALID_ACCESS_STATUSES:
            errors.append(f"{prefix}: invalid access.status {status!r}")
        oa_url = access.get("oa_url")
        oa_source = access.get("oa_source")
        if is_forbidden_url(oa_url):
            errors.append(f"{prefix}: forbidden OA URL host")
        if status in {"downloaded_oa_pdf", "oa_pdf_available_not_downloaded", "oa_landing_only", "download_failed_retryable"}:
            if not oa_source:
                errors.append(f"{prefix}: missing access.oa_source for OA status")
            elif oa_source not in ALLOWED_PROVENANCE:
                errors.append(f"{prefix}: untrusted access.oa_source {oa_source!r}")
            if not oa_url:
                errors.append(f"{prefix}: missing access.oa_url for OA status")
        if status == "downloaded_oa_pdf":
            local_pdf = access.get("local_pdf_path")
            if not local_pdf:
                errors.append(f"{prefix}: missing local_pdf_path for downloaded PDF")
            else:
                path = (attachments / local_pdf).resolve()
                papers_root = (attachments / "papers").resolve()
                if papers_root not in [path, *path.parents]:
                    errors.append(f"{prefix}: local_pdf_path escapes attachments/papers")
                elif not path.exists():
                    errors.append(f"{prefix}: local PDF file does not exist")
            if not access.get("pdf_sha256"):
                errors.append(f"{prefix}: missing pdf_sha256 for downloaded PDF")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate scholarly-paper-collector run artifacts.")
    parser.add_argument("--attachments", default="attachments")
    parser.add_argument("--require-pdf", action="store_true")
    args = parser.parse_args(argv)
    attachments = Path(args.attachments).resolve()
    index_path = attachments / "papers" / "index.json"
    bib_path = attachments / "papers" / "bibtex.bib"
    analysis_path = attachments / "papers" / "analysis_zh.json"
    html_path = attachments / "overview_zh.html"
    pdf_path = attachments / "overview_zh.pdf"
    errors: list[str] = []
    for path in (index_path, bib_path, analysis_path, html_path):
        if not path.exists():
            errors.append(f"missing {path}")
    if args.require_pdf and not pdf_path.exists():
        errors.append(f"missing {pdf_path}")
    index = None
    if index_path.exists():
        index = read_index(index_path)
        errors.extend(validate_index_legal_fields(index, attachments))
    if index is not None and analysis_path.exists():
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        errors.extend(validate_analysis(index, analysis))
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        for heading in REQUIRED_HEADINGS:
            if heading not in html:
                errors.append(f"missing heading {heading}")
        if "逐篇论文分析" in html and "缺少逐篇分析" in html:
            errors.append("report contains placeholder per-paper analysis")
        if index and index.get("papers"):
            if "排名" not in html:
                errors.append("report missing ranked paper list")
            if not any((paper.get("access") or {}).get("status") == "metadata_only_no_legal_pdf" for paper in index.get("papers", [])):
                pass
            elif "仅元数据，未发现合法开放 PDF" not in html:
                errors.append("report missing metadata-only label")
    if errors:
        print("Run validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    print("run validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
