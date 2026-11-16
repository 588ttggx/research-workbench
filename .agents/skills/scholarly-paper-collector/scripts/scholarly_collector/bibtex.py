from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def bib_key(paper: dict[str, Any]) -> str:
    first_author = (paper.get("authors") or ["paper"])[0].split()[-1].lower()
    first_author = re.sub(r"[^a-z0-9]", "", first_author) or "paper"
    year = paper.get("year") or "nd"
    title_word = next(iter(re.findall(r"[A-Za-z0-9]+", paper.get("title") or "")), "work").lower()
    return f"{first_author}{year}{title_word}"


def escape(value: object) -> str:
    return str(value or "").replace("{", "\\{").replace("}", "\\}")


def write_bibtex(path: Path, papers: list[dict[str, Any]]) -> None:
    entries = []
    used: dict[str, int] = {}
    for paper in papers:
        key = bib_key(paper)
        used[key] = used.get(key, 0) + 1
        if used[key] > 1:
            key = f"{key}{used[key]}"
        fields = {
            "title": paper.get("title"),
            "author": " and ".join(paper.get("authors") or []),
            "year": paper.get("year"),
            "journal": paper.get("venue"),
            "doi": paper.get("doi"),
            "eprint": paper.get("arxiv_id"),
            "url": paper.get("access", {}).get("oa_url"),
        }
        body = [f"  {name} = {{{escape(value)}}}" for name, value in fields.items() if value]
        entries.append("@article{" + key + ",\n" + ",\n".join(body) + "\n}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")
