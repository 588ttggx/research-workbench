#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scholarly_collector.ranking import apply_analysis_reranking
from scholarly_collector.report import validate_analysis
from scholarly_collector.schema import read_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add analysis-informed ranks without deleting metadata ranking fields.")
    parser.add_argument("--attachments", default="attachments")
    args = parser.parse_args(argv)
    attachments = Path(args.attachments).resolve()
    index_path = attachments / "papers" / "index.json"
    analysis_path = attachments / "papers" / "analysis_zh.json"
    if not analysis_path.exists():
        print(f"ERROR: missing {analysis_path}. Codex must create analysis_zh.json before reranking.", file=sys.stderr)
        return 2
    index = read_index(index_path)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    errors = validate_analysis(index, analysis)
    if errors:
        print("ERROR: invalid analysis_zh.json:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    updated = apply_analysis_reranking(index, analysis)
    index_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
