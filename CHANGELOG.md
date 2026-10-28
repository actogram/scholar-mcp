# Changelog

## 0.4.1 (2026-10-28)

- While a search runs, the page shows what LabScout is doing, step by step: how PubMed read the search, how many
  records each source has and how they are read, how many papers both sources share, how the affiliations were
  placed (with examples) and the first labs. Europe PMC is read in year ranges side by side when the whole result is
  read, the ROR API checks of a search run side by side, a part of an affiliation that only names a country is not
  taken for an organisation, and a refused PubMed batch is tried again instead of losing the source. A search of
  14,500 records now takes about 40 seconds.

## 0.4.0 (2026-10-28)

- Full searches. The web page reads all papers a search finds, up to 10,000 from each source instead of 100, and the
  `find_labs` tool reads 1,000 by default and up to 10,000. More papers find the smaller labs further down the list.
- Much faster. Affiliations are matched to organisations with a local copy of the ROR registry (built from ROR's CC0
  data dump with `labscout ror-index`, used when `LABSCOUT_ROR_INDEX` names it), so a search no longer waits for one
  request per paper; the ROR API only gets the few affiliations the local copy cannot place. A name counts only when
  all its words stand in one part of the affiliation, and names made of general words such as "Department of Public
  Health" are not taken. PubMed and Europe PMC are searched side by side, and PubMed records are fetched in parallel
  batches within NCBI's limit (10 requests a second with an API key). A search of 500 papers took 160 s and now takes
  about 25 s; one of 14,500 papers takes about two minutes.
- The Docker image builds the ROR index and the Space uses an NCBI API key.

## 0.3.0 (2026-10-27)

- Better searches. LabScout now reads the most relevant papers instead of the newest: PubMed's Best Match and the
  most cited papers on Europe PMC, whose own relevance order is mostly by date. Europe PMC is searched in titles and
  abstracts, as PubMed is, and PubMed field tags such as `[tiab]`, `[ti]`, `[au]` and `[MeSH Terms]` are translated
  for it. `--order newest` (and `order` in the MCP tools and on the web page) still reads the newest.
- A search with an unclosed quote or bracket is stopped with a message, because the sources would otherwise read it
  another way without saying so.
- Fewer false labs. A co-authored paper counts for a lab only when the co-author is clearly the same person (the same
  ORCID iD, or the lab's city or organisation in the affiliation), so a common name such as "Li J" no longer adds up
  papers of many people. One person in two cities is one lab when both records carry the same ORCID iD.
- The report says how many papers each source has for the search and how many were read, gives a hint when the search
  is very broad or very narrow, shows how PubMed read the search, and has two small charts: labs by country and papers
  by year. On a phone the table becomes one card per lab.
- The web page explains the tool: how it works in four drawn steps, search tips with examples, how to read the
  results, and example questions for AI assistants. The year field starts five years back. While a search runs, the
  page shows its steps. A privacy page, `/privacy`, and a `robots.txt` that keeps crawlers away from searches.
- People who ask not to be shown can be hidden with `LABSCOUT_HIDE` (ORCID iDs or names).
- Searches from the web page and from assistants share one pace per source and a limited number of places, so
  parallel searches stay within the sources' limits. Pages are compressed, `GET /mcp` answers 405, and the pages send
  a content security policy.

## 0.2.0 (2026-10-27)

- New name: LabScout. The package and the command are `labscout`; the MCP server is `labscout`.
- A web page, `labscout serve`: search form, report with map and table, Excel, CSV and JSON downloads, and the MCP
  server at `/mcp` on the same address. Searches run in the background and the page refreshes by itself; each visitor
  can start a limited number of searches an hour.
- The MCP endpoint answers only for its own host names (DNS rebinding protection) and runs stateless.
- New sources: UKRI Gateway to Research (UK grants) and the patent records in Europe PMC (up to 2014), with the tools
  `find_patents` and `find_grants` for both funders, and the commands `patents` and `grants --funders`.
- A Docker setup for a Hugging Face Space in `deploy/huggingface`.

## 0.1.0 (2026-10-27)

First version.

- Labs for a topic from PubMed and Europe PMC, merged across sources, with organisations and places from ROR and a
  plain reason for each lab.
- Researcher profiles, NIH RePORTER grants and ClinicalTrials.gov studies.
- Exports: an HTML report with a map and a sortable table, Excel, CSV and JSON.
- An MCP server with five read-only tools, over stdio or Streamable HTTP.
