from __future__ import annotations

import hashlib
import logging
import subprocess
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

from .config import redact
from .legal import legal_pdf_decision


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_legal_pdf(paper: dict, papers_dir: Path, logger: logging.Logger) -> None:
    access = paper.setdefault("access", {})
    url = access.get("oa_url")
    provenance = access.get("oa_source")
    allowed, reason = legal_pdf_decision(url, provenance)
    if not allowed:
        access["status"] = "download_blocked_by_policy"
        access.setdefault("notes", []).append(reason)
        logger.warning("blocked PDF download paper_id=%s reason=%s", paper.get("paper_id"), reason)
        return
    papers_dir.mkdir(parents=True, exist_ok=True)
    target = papers_dir / f"{paper.get('paper_id')}.pdf"
    if target.exists() and target.stat().st_size > 0:
        access["status"] = "downloaded_oa_pdf"
        access["local_pdf_path"] = f"papers/{target.name}"
        access["pdf_sha256"] = sha256_file(target)
        logger.info("reuse existing PDF paper_id=%s path=%s", paper.get("paper_id"), target)
        return
    try:
        logger.info("download legal OA PDF paper_id=%s url=%s", paper.get("paper_id"), redact(url))
        with urlopen(Request(url, headers={"User-Agent": "scholarly-paper-collector/1.0"}), timeout=45) as response:
            final_url = response.geturl()
            final_allowed, final_reason = legal_pdf_decision(final_url, provenance)
            if not final_allowed:
                raise RuntimeError(f"final redirected URL blocked: {final_reason}")
            data = response.read()
        if len(data) < 100:
            raise RuntimeError("downloaded PDF is unexpectedly small")
        if not data.lstrip().startswith(b"%PDF"):
            raise RuntimeError("downloaded bytes do not start with PDF magic header")
        target.write_bytes(data)
        access["status"] = "downloaded_oa_pdf"
        access["local_pdf_path"] = f"papers/{target.name}"
        access["pdf_sha256"] = sha256_file(target)
    except Exception as exc:
        access["status"] = "download_failed_retryable"
        access.setdefault("notes", []).append(str(exc))
        logger.warning("PDF download failed paper_id=%s error=%s", paper.get("paper_id"), redact(exc))


def extract_pdf_text(path: Path, max_chars: int = 8000) -> tuple[str, dict]:
    if not path.exists():
        return "", {"status": "failed", "reason": "PDF path does not exist"}
    try:
        import pymupdf
        with pymupdf.open(path) as document:
            text = '\n'.join(page.get_text() for page in document)[:max_chars].strip()
        if len(text) >= 40:
            return text, {'status': 'ok', 'method': 'pymupdf', 'chars': len(text)}
    except (ImportError, RuntimeError, ValueError, OSError):
        pass
    if shutil.which('pdftotext'):
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        text = result.stdout.strip()
        if result.returncode == 0 and len(text) >= 40:
            return text[:max_chars], {"status": "ok", "method": "pdftotext", "chars": min(len(text), max_chars)}
        reason = result.stderr.strip() or "pdftotext returned unusable text"
        return "", {"status": "failed", "method": "pdftotext", "reason": reason[:500]}
    return "", {"status": "failed", "method": "fallback", "reason": "PDF extraction unavailable or yielded unusable text"}
