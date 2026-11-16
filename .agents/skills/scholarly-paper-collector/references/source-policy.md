# Source And Download Policy

Use legal, API-first scholarly sources only.

## Allowed

- WoS official Starter / Expanded API metadata within the user's granted subscription.
- arXiv metadata and arXiv-hosted PDFs.
- OpenAlex metadata and OA locations when authenticated with `OPENALEX_API_KEY`.
- Semantic Scholar metadata and open-access PDF URLs returned by its API.
- Crossref metadata and license/URL metadata.
- Unpaywall OA locations when explicitly requested, using `UNPAYWALL_EMAIL`.
- Publisher-hosted open-access PDFs when the URL is explicitly returned by an allowed metadata/OA API.
- Institutional repositories only when clearly lawful and returned by allowed OA metadata.
- Local `fixture` provenance only inside tests and offline demonstrations.

## Forbidden

- Sci-Hub, Library Genesis, Anna's Archive, Z-Library, shadow libraries, and unauthorized mirrors.
- Paywall bypass, credentialed scraping, session-cookie reuse, or robots/terms-violating scraping.
- Google Scholar scraping.
- PDF URLs discovered only from generic web search without OA provenance.

## Operational Rules

- Keep metadata-only records when no legal PDF is available.
- Store OA provenance in `access.oa_source`, `access.oa_url`, and `access.license`.
- Redact emails, API keys, auth headers, and secret-bearing query params from logs.
- Treat unknown PDF provenance as not downloadable.
- Validate downloaded bytes as PDF content and re-check the final redirect URL before saving.
