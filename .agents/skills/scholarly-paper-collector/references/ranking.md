# Ranking Design

Ranking is two-stage.

## Stage 1: Metadata Ranking

`collect_papers.py` computes deterministic metadata scores:

- topical relevance from title and abstract query-token coverage, with stop words removed and title matches weighted higher than abstract matches.
- recency inside the requested year window.
- citation impact from citation count.
- influential impact from influential citation count when available.
- source and venue quality heuristic.
- contribution proxy from metadata terms such as benchmark, dataset, framework, method, architecture, evaluation, agent, tool, and planning.

The script stores `ranking.metadata_scores`, `ranking.metadata_score`, and `metadata_rank`.

## Stage 2: Analysis-Informed Reranking

After Codex writes `analysis_zh.json`, run `rerank_with_analysis.py`.

The reranker:

- preserves `metadata_rank` and all deterministic score fields.
- reads `contribution_score` and Chinese analysis fields.
- writes `ranking.analysis_scores`, `analysis_rank`, and `final_rank`.
- never deletes deterministic ranking fields.

Recommended final score:

`0.70 * metadata_score + 0.30 * normalized_analysis_score`

Tie handling is deterministic: final sorting uses score, year, citation count, then title. Citation signals are log-scaled and capped so older highly cited papers cannot dominate weak topical matches.
