# Changelog

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
