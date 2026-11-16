#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import hashlib
import json
from datetime import datetime, timezone
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scholarly_collector.bibtex import write_bibtex
from scholarly_collector.cache import FileCache
from scholarly_collector.config import CollectorConfig, redact
from scholarly_collector.http import HTTPClient
from scholarly_collector.pdf import download_legal_pdf, sha256_file
from scholarly_collector.ranking import apply_metadata_ranking
from scholarly_collector.schema import base_access, dedupe_papers, make_paper, write_index
from scholarly_collector.providers import arxiv, crossref, openalex, semantic_scholar, unpaywall, wos


DEFAULT_SOURCES = ["wos", "openalex", "crossref", "semantic_scholar", "arxiv"]

NETWORK_FAILURE_MARKERS = (
    "nodename nor servname provided",
    "temporary failure in name resolution",
    "network is unreachable",
    "name or service not known",
)

FIXTURE_PDF = b"""%PDF-1.4
1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj
2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj
3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj
4 0 obj <</Length 86>> stream
BT /F1 12 Tf 72 720 Td (A legal open access fixture paper about agentic LLM tool use.) Tj ET
endstream endobj
5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000241 00000 n
0000000378 00000 n
trailer <</Root 1 0 R /Size 6>>
startxref
448
%%EOF
"""


def setup_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return logging.getLogger("scholarly-paper-collector")


def parse_sources(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_SOURCES)
    return [part.strip() for part in value.split(",") if part.strip()]


def looks_like_network_permission_failure(warnings: list[str]) -> bool:
    joined = "\n".join(warnings).lower()
    return any(marker in joined for marker in NETWORK_FAILURE_MARKERS)


def fixture_papers(out_dir: Path, no_results: bool = False) -> list[dict]:
    if no_results:
        return []
    papers_dir = out_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = papers_dir / "p001.pdf"
    pdf_path.write_bytes(FIXTURE_PDF)
    oa_access = {
        "status": "downloaded_oa_pdf",
        "oa_url": "https://arxiv.org/pdf/2401.00001.pdf",
        "oa_source": "fixture",
        "license": "CC-BY-4.0",
        "local_pdf_path": "papers/p001.pdf",
        "pdf_sha256": sha256_file(pdf_path),
        "notes": [],
    }
    duplicate_access = base_access()
    return [
        make_paper(
            title="Agentic LLM Tool Use: A Benchmark Framework",
            source="fixture_arxiv",
            authors=["Ada Researcher", "Bo Scholar"],
            year=2025,
            venue="arXiv",
            abstract="This paper introduces a benchmark framework for agentic LLM tool use, planning, and evaluation.",
            doi="10.0000/fixture.oa",
            arxiv_id="2401.00001",
            citation_count=42,
            influential_citation_count=7,
            access=oa_access,
        ),
        make_paper(
            title="Agentic LLM Tool Use: A Benchmark Framework",
            source="fixture_semantic_scholar",
            authors=["Ada Researcher", "Bo Scholar"],
            year=2025,
            venue="arXiv",
            abstract="A duplicate metadata record for the same benchmark framework paper.",
            doi="https://doi.org/10.0000/fixture.oa",
            semantic_scholar_id="S2FIXTUREOA",
            citation_count=45,
            influential_citation_count=8,
            access=duplicate_access,
        ),
        make_paper(
            title="Planning-Centric Agents with Tool Feedback",
            source="fixture_crossref",
            authors=["Chen Analyst"],
            year=2024,
            venue="Proceedings of Example AI",
            abstract="A metadata-only paper about planning-centric language agents and tool feedback loops.",
            doi="10.0000/fixture.metadata",
            citation_count=8,
            influential_citation_count=1,
        ),
    ]


def collect_live(args: argparse.Namespace, out_dir: Path, config: CollectorConfig, logger: logging.Logger) -> tuple[list[dict], list[str]]:
    try:
        cache = FileCache(config.cache_dir)
    except OSError:
        cache = FileCache(out_dir/'.spc_cache')
    client = HTTPClient(cache, logger)
    warnings: list[str] = []
    papers: list[dict] = []
    sources = parse_sources(args.sources)
    for source in sorted(sources, key=lambda source: source != 'wos'):
        query=(getattr(args,'provider_queries',{}) or {}).get(source,args.query)
        try:
            if source == 'wos':
                if not config.wos_api_key:
                    message = 'WoS skipped: configure WOS_API_KEY in local settings; website login does not grant official API access.'
                    client.observations[source] = {'status': 'needs_configuration', 'retrieved': 0, 'exhausted': False}
                    if args.strict_providers or sources == ['wos']:
                        raise openalex.ProviderConfigError(message)
                    warnings.append(message)
                    continue
                if not args.wos_query:
                    raise ValueError('WoS needs --wos-query with explicit field syntax; no query was invented')
                papers.extend(wos.search(args.wos_query, args.from_year, args.to_year, args.max_results,
                    client, logger, api_key=config.wos_api_key, api=config.wos_api, database=config.wos_database))
            elif source == "arxiv":
                papers.extend(arxiv.search(query, args.from_year, args.to_year, args.max_results, client, logger))
            elif source == "openalex":
                explicit_openalex_only = sources == ["openalex"]
                if not config.openalex_api_key and not args.strict_providers and not explicit_openalex_only:
                    message = "OpenAlex skipped: set OPENALEX_API_KEY to enable OpenAlex API access."
                    logger.warning(message)
                    warnings.append(message)
                    client.observations[source] = {'status': 'needs_configuration', 'retrieved': 0, 'exhausted': False}
                    continue
                papers.extend(
                    openalex.search(
                        query,
                        args.from_year,
                        args.to_year,
                        args.max_results,
                        client,
                        logger,
                        api_key=config.openalex_api_key,
                        strict=args.strict_providers,
                        explicit=explicit_openalex_only,
                    )
                )
            elif source == "semantic_scholar":
                papers.extend(
                    semantic_scholar.search(
                        query,
                        args.from_year,
                        args.to_year,
                        args.max_results,
                        client,
                        logger,
                        api_key=config.semantic_scholar_api_key,
                    )
                )
            elif source == "crossref":
                papers.extend(crossref.search(query, args.from_year, args.to_year, args.max_results, client, logger, contact_email=config.contact_email))
            else:
                message = f"Unknown provider skipped: {source}"
                if args.strict_providers:
                    raise RuntimeError(f"Unknown provider requested in strict mode: {source}")
                logger.warning(message)
                warnings.append(message)
        except openalex.ProviderConfigError:
            raise
        except Exception as exc:
                partial = client.partial_papers.get(source, [])
                papers.extend(partial)
                client.observations[source] = {**client.observations.get(source, {}),
                    'status': 'partial' if partial else 'failed', 'retrieved': len(partial), 'exhausted': False}
                message = f"Provider {source} failed and was skipped: {redact(exc)}"
                if "HTTP 429" in message and source == "semantic_scholar" and not config.semantic_scholar_api_key:
                    message += " Public unauthenticated Semantic Scholar pool is throttled; set SEMANTIC_SCHOLAR_API_KEY or omit semantic_scholar for this run."
                if "HTTP Error 429" in message and source == "arxiv":
                    message += " arXiv is throttling this client/IP; wait before retrying or omit arxiv for this run."
                logger.warning(message)
                warnings.append(message)

    papers = dedupe_papers(papers)
    if getattr(args, 'resolve_oa', False) and config.unpaywall_email:
        for paper in papers:
            if paper.get("doi") and not paper.get("access", {}).get("oa_url"):
                try:
                    access = unpaywall.resolve_pdf_for_doi(paper["doi"], client, logger, email=config.unpaywall_email)
                    if access:
                        paper["access"] = access
                except Exception as exc:
                    message = f"Unpaywall lookup failed for {paper.get('doi')}: {redact(exc)}"
                    logger.warning(message)
                    warnings.append(message)
    elif getattr(args, 'resolve_oa', False):
        message = "Unpaywall skipped: set UNPAYWALL_EMAIL to resolve DOI OA PDFs."
        logger.warning(message)
        warnings.append(message)
    receipt = {'generated_at': datetime.now(timezone.utc).isoformat(), 'query': args.query, 'wos_query': getattr(args, 'wos_query', None),
        'from_year': args.from_year, 'to_year': args.to_year, 'limit_per_source': args.max_results,
        'sources_requested': sources, 'providers': client.observations, 'requests': client.requests,
        'cache_dir': str(cache.root), 'warnings': warnings,
        'scope': 'Bounded metadata retrieval; empty, failed, unavailable and exhausted are distinct. No full-text reading asserted.'}
    (out_dir/'search-log.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return papers, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect lawful scholarly paper metadata and OA PDFs.")
    parser.add_argument("--query", default="", help="Topic query.")
    parser.add_argument('--wos-query', default='', help='Explicit WoS field query, e.g. TS=(terahertz AND starch).')
    parser.add_argument('--check-config', action='store_true', help='Show only configured/not-configured states; never print credentials.')
    parser.add_argument("--from-year", type=int, default=None)
    parser.add_argument("--to-year", type=int, default=None)
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument("--sources", default=None, help="Comma-separated providers; wos is queried first when requested.")
    parser.add_argument("--out", default=None, help="Output directory; defaults to this workspace's output/文献检索/<query identity>.")
    parser.add_argument('--refresh', action='store_true', help='Explicitly refresh existing machine search results; analysis files stay untouched.')
    parser.add_argument('--resolve-oa', action='store_true', help='Explicitly enable optional Unpaywall DOI enrichment.')
    parser.add_argument("--download-oa", action="store_true", help="Download legal OA PDFs when available.")
    parser.add_argument("--strict-providers", action="store_true", help="Fail when a requested provider is not configured.")
    parser.add_argument("--offline-fixture", choices=["smoke", "no-result"], default=None, help="Internal deterministic fixture mode for smoke tests.")
    args = parser.parse_args(argv)

    logger = setup_logger()
    workspace = next((path for path in SCRIPT_DIR.parents if (path/'科研知识库/文献/library.json').is_file()), Path.cwd())
    if args.check_config:
        config = CollectorConfig.from_env(workspace/'output/文献检索')
        print(json.dumps({'wos': bool(config.wos_api_key), 'wos_api': config.wos_api,
            'openalex': bool(config.openalex_api_key), 'semantic_scholar': bool(config.semantic_scholar_api_key),
            'crossref_contact': bool(config.contact_email), 'arxiv': True}, ensure_ascii=True))
        return 0
    if not 1 <= args.max_results <= 5000:
        parser.error('--max-results must be between 1 and 5000 per provider')
    if args.from_year and args.to_year and args.from_year > args.to_year:
        parser.error('--from-year must not exceed --to-year')
    sources = parse_sources(args.sources)
    if any(source not in DEFAULT_SOURCES for source in sources):
        parser.error('Unknown source; choose wos,openalex,crossref,semantic_scholar,arxiv')
    identity = hashlib.sha256(json.dumps([args.query, args.wos_query, args.from_year, args.to_year, sources, args.max_results]).encode()).hexdigest()[:16]
    out_dir = Path(args.out).resolve() if args.out else workspace/'output/文献检索'/identity
    if (out_dir/'papers/index.json').exists() and not args.refresh:
        logger.error('Existing search results preserved; use --refresh only to update machine results in this task directory.')
        return 2
    papers_dir = out_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    sources = parse_sources(args.sources)
    warnings: list[str] = []
    if args.offline_fixture:
        query = args.query or "agentic LLM tool use"
        papers = fixture_papers(out_dir, no_results=args.offline_fixture == "no-result")
    else:
        if not args.query:
            parser.error("--query is required unless --offline-fixture is used")
        query = args.query
        config = CollectorConfig.from_env(out_dir)
        try:
            papers, warnings = collect_live(args, out_dir, config, logger)
        except openalex.ProviderConfigError as exc:
            logger.error(str(exc))
            return 2
        if not papers and looks_like_network_permission_failure(warnings):
            write_index(papers_dir / "index.json", query=query, sources_requested=sources, warnings=warnings, papers=[])
            write_bibtex(papers_dir / "bibtex.bib", [])
            logger.error(
                "Live provider calls failed due to network/DNS access. In Codex sandboxed environments, rerun this live collection with network permission/escalation. Offline fixture mode does not need network."
            )
            return 4

    papers = dedupe_papers(papers)
    library_path = workspace/'科研知识库/文献/library.json'
    if library_path.is_file():
        library = json.loads(library_path.read_text('utf-8-sig')).get('records', [])
        for paper in papers:
            matches = [record for record in library if (paper.get('doi') and record.get('doi') and
                paper['doi'] == str(record['doi']).lower().removeprefix('https://doi.org/')) or
                (paper.get('wos_id') and (record.get('wos_id') == paper['wos_id'] or record.get('id') == 'wos-'+paper['wos_id'].split(':')[-1]))]
            paper['workspace_matches'] = [{'id': record['id'], 'artifacts': record.get('artifacts', [])} for record in matches]
    apply_metadata_ranking(papers, query, args.from_year, args.to_year)
    if args.download_oa and not args.offline_fixture:
        for paper in papers:
            if paper.get("access", {}).get("oa_url"):
                download_legal_pdf(paper, papers_dir, logger)
    write_index(papers_dir / "index.json", query=query, sources_requested=sources, warnings=warnings, papers=papers)
    write_bibtex(papers_dir / "bibtex.bib", papers)
    logger.info("wrote %s", papers_dir / "index.json")
    logger.info("wrote %s", papers_dir / "bibtex.bib")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
