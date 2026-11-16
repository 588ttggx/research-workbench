#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scholarly_collector.pdf import extract_pdf_text
from scholarly_collector.schema import read_index


def safe_pdf_path(attachments: Path, local_pdf: str) -> Path:
    root = (attachments / "papers").resolve()
    candidate = (attachments / local_pdf).resolve()
    if root not in [candidate, *candidate.parents]:
        raise ValueError(f"local_pdf_path escapes attachments/papers: {local_pdf}")
    return candidate


def packet_for_paper(paper: dict, attachments: Path, max_chars: int) -> dict:
    access = paper.get("access") or {}
    pdf_text = ""
    extraction = {"status": "not_applicable_metadata_only", "reason": "No downloaded legal OA PDF."}
    local_pdf = access.get("local_pdf_path")
    if local_pdf:
        try:
            pdf_text, extraction = extract_pdf_text(safe_pdf_path(attachments, local_pdf), max_chars=max_chars)
        except Exception as exc:
            pdf_text = ""
            extraction = {"status": "failed", "reason": str(exc)[:500]}
        if not pdf_text:
            extraction["fallback"] = "title_abstract_metadata"
    paper["extraction"] = extraction
    basis_parts = [
        f"Title: {paper.get('title') or ''}",
        f"Year: {paper.get('year') or ''}",
        f"Venue: {paper.get('venue') or ''}",
        f"Abstract: {paper.get('abstract') or ''}",
    ]
    if pdf_text:
        basis_parts.append(f"Extracted legal OA PDF text: {pdf_text}")
    else:
        basis_parts.append("Extracted legal OA PDF text: unavailable; analyze from title, abstract, and metadata only.")
    return {
        "paper_id": paper.get("paper_id"),
        "title": paper.get("title"),
        "metadata_rank": paper.get("metadata_rank"),
        "access_status": access.get("status"),
        "analysis_basis": "\n".join(basis_parts)[:max_chars],
        "pdf_extraction": extraction,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare bounded per-paper packets for Codex Chinese analysis.")
    parser.add_argument("--attachments", default="attachments")
    parser.add_argument("--max-chars", type=int, default=8000)
    args = parser.parse_args(argv)
    attachments = Path(args.attachments).resolve()
    index = read_index(attachments / "papers" / "index.json")
    papers = index.get("papers", [])
    packets = {
        "query": index.get("query"),
        "instructions": (
            "Codex must create analysis_zh.json from these packets. Preserve each English title exactly. "
            "Use Chinese for analysis fields and do not fabricate beyond the provided basis."
        ),
        "papers": [packet_for_paper(paper, attachments, args.max_chars) for paper in papers],
    }
    out = attachments / "papers" / "analysis_packets.json"
    out.write_text(json.dumps(packets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (attachments / "papers" / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
