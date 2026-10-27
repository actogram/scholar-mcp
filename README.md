# Actogram Scholar

Find the labs, people and studies behind a research topic, and see on a map who works on it and where.

Scholar searches public sources, groups the papers by their senior author and organisation, and says in one sentence
why each lab came up: how many papers on the topic it led, in which years, with what kind of data and which species.
It works from the command line, and as an MCP server that AI assistants can call.

It grew out of [pubmed2worldmap](https://github.com/timpyrkov/pubmed2worldmap) by Tim Pyrkov, and is part of
[Actogram Open Science](https://actogram.org).

## What it uses

| Source | What it gives | Terms |
|---|---|---|
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) through [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/) | papers, authors, affiliations, MeSH terms, funders | free; at most 3 requests a second, 10 with an API key; [NCBI policies](https://www.ncbi.nlm.nih.gov/home/about/policies/) |
| [Europe PMC](https://europepmc.org/RestfulWebService) | papers and preprints, ORCID iDs, funders, links to datasets | free |
| [Research Organization Registry](https://ror.org/) | the organisation behind an affiliation, its city and coordinates | free, CC0 |
| [NIH RePORTER](https://api.reporter.nih.gov/) | NIH-funded projects and their investigators | free, about one request a second |
| [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) | registered studies, their investigators and sites | free |

Only the official APIs are used. Requests are paced to each source's limits, sent with a clear User-Agent, and kept in
a local cache for seven days, so a repeated search costs the sources nothing.

## Install

Python 3.10 or newer.

```bash
pip install "actogram-scholar @ git+https://github.com/actogram/scholar-mcp"
```

For development:

```bash
git clone https://github.com/actogram/scholar-mcp
cd scholar-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Use it from the command line

```bash
# labs working on a topic, with a map and a table in one HTML file, and an Excel workbook
actogram-scholar labs "actigraphy sleep regularity older adults" --from 2020 --xlsx labs.xlsx --html labs.html

# add NIH grants for the five top labs
actogram-scholar labs "circadian rhythm shift work" --from 2022 --grants 5

# papers, newest first, merged across PubMed and Europe PMC
actogram-scholar papers "wearable step counts circadian" --max 20

# one researcher: organisations, frequent co-authors and topics, recent papers, NIH grants
actogram-scholar profile "Susan Redline" --topic "sleep regularity"

# registered studies with investigators and sites
actogram-scholar trials "actigraphy sleep"

# NIH-funded projects by investigator or by words
actogram-scholar grants --pi "Susan Redline"
actogram-scholar grants --text "circadian actigraphy"
```

Searches use PubMed syntax, so `actigraphy AND "sleep regularity"` and field tags such as `[tiab]` work. Each source
gives at most `--max` papers, newest first.

The HTML report is a single file: a map of the labs with a known place, and a table you can sort and filter, with the
papers behind each lab. The Excel workbook has the sheets Labs, Papers and About.

## Use it from an AI assistant (MCP)

```bash
actogram-scholar mcp                           # stdio, for assistants on this computer
actogram-scholar mcp --http --port 8000       # Streamable HTTP at http://127.0.0.1:8000/mcp
```

Most MCP clients take a configuration like this:

```json
{
  "mcpServers": {
    "actogram-scholar": { "command": "actogram-scholar", "args": ["mcp"] }
  }
}
```

The tools, all read-only:

| Tool | What it does |
|---|---|
| `find_labs` | labs working on a topic, ranked, with the reason each one came up; optional NIH grants |
| `search_papers` | papers on a topic from PubMed and Europe PMC, with species and data hints |
| `lab_profile` | one researcher: organisations, years, co-authors, topics, recent papers, NIH grants |
| `find_trials` | registered studies on ClinicalTrials.gov with investigators and sites |
| `find_grants` | NIH-funded projects by investigator or by words |

## Settings

| Variable | Meaning |
|---|---|
| `SCHOLAR_EMAIL` | your contact address, sent to NCBI and in the User-Agent as their policies ask (recommended) |
| `NCBI_API_KEY` | an [NCBI API key](https://support.nlm.nih.gov/kbArticle/?pn=KA-05317) for faster PubMed searches |
| `SCHOLAR_CACHE_DIR` | where the cache lives (default `~/.cache/actogram-scholar`); an empty value switches it off |

## How a lab is found

1. Papers on the topic come from PubMed and Europe PMC and are merged by PMID, DOI or title and year.
2. The senior (last) author of each paper leads its lab. Older PubMed records list only the first author's
   affiliation; then the lab is placed with that one.
3. The affiliation is matched to an organisation in ROR. A match is accepted only when ROR is confident, or when a
   name search finds an organisation whose name words all appear in the affiliation and whose country agrees. Otherwise
   only the country is taken from the text. The column `match` (`ror`, `ror-name` or `text`) shows which.
4. One person at two organisations in the same city, such as a university and its hospital, is one lab. The same name
   in different cities stays apart, because it may be two people.
5. Labs are ranked by papers led, papers co-authored, recent work, the kinds of data mentioned and the search words
   found.

## Privacy and fair use

Scholar shows information that researchers have made public in their work: names, affiliations, publications, grants
and registered studies. It removes e-mail addresses from affiliations and never returns them. Use the results to find
research and collaborators, not to judge people. Organisation matching is automatic and can be wrong, so check before
you act on a result.

## Development

```bash
ruff check src tests && ruff format --check src tests
pytest                 # offline tests on recorded answers of the real APIs
pytest -m network      # a few live requests to the public APIs
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Planned next: patent sources for prior art, CORDIS and UKRI grants, and a
simple web page.

## Cite

See [CITATION.cff](CITATION.cff). Please cite the version you used.

## Licence

MIT, see [LICENSE](LICENSE). The data belongs to its sources and keeps their terms.
