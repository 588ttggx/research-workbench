#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from scholarly_collector.report import render_html, validate_analysis
from scholarly_collector.schema import read_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render Simplified Chinese HTML/PDF overview from index.json and analysis_zh.json.")
    parser.add_argument("--attachments", default="attachments")
    parser.add_argument("--weasyprint-bin", default="weasyprint")
    args = parser.parse_args(argv)
    attachments = Path(args.attachments).resolve()
    index_path = attachments / "papers" / "index.json"
    analysis_path = attachments / "papers" / "analysis_zh.json"
    if not index_path.exists():
        print(f"ERROR: missing {index_path}", file=sys.stderr)
        return 2
    if not analysis_path.exists():
        print(f"ERROR: missing {analysis_path}. Codex must create analysis_zh.json before rendering.", file=sys.stderr)
        return 2
    index = read_index(index_path)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    errors = validate_analysis(index, analysis)
    if errors:
        print("ERROR: invalid analysis_zh.json:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    html_text = render_html(index, analysis, SKILL_DIR)
    html_path = attachments / "overview_zh.html"
    pdf_path = attachments / "overview_zh.pdf"
    html_path.write_text(html_text, encoding="utf-8")
    binary = shutil.which(args.weasyprint_bin)
    if not binary:
        print(
            f"ERROR: weasyprint CLI not found. Preserved {html_path}. "
            "Install or expose the `weasyprint` CLI, then rerun render_report.py.",
            file=sys.stderr,
        )
        return 3
    result = subprocess.run([binary, str(html_path), str(pdf_path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"ERROR: weasyprint failed. Preserved {html_path}.", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode
    print(f"wrote {html_path}")
    print(f"wrote {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
