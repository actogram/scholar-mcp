# Actogram LabScout

Find the labs, people and studies behind a research topic, and see on a map who works on it and where.

LabScout searches public sources, groups the papers by their senior author and organisation, and says in one sentence
why each lab came up: how many papers on the topic it led, in which years, with what kind of data and which species.
It also finds grants, registered trials and patents on a topic. You can use it in three ways:

- **on the web page** at [actogram-labscout.hf.space](https://actogram-labscout.hf.space): type a topic, get a map, a
  table and an Excel file;
- **from an AI assistant**, as an MCP server at `https://actogram-labscout.hf.space/mcp`;
- **from the command line** or your own Python code.

It grew out of [pubmed2worldmap](https://github.com/timpyrkov/pubmed2worldmap) by Tim Pyrkov, and is part of
[Actogram Open Science](https://actogram.org).

## What it uses

| Source | What it gives | Terms |
|---|---|---|
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) through [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/) | papers, authors, affiliations, MeSH terms, funders | free; at most 3 requests a second, 10 with an API key; [NCBI policies](https://www.ncbi.nlm.nih.gov/home/about/policies/) |
| [Europe PMC](https://europepmc.org/RestfulWebService) | papers and preprints, ORCID iDs, funders, links to datasets; patent records up to 2014 | free |
| [Research Organization Registry](https://ror.org/) | the organisation behind an affiliation, its city and coordinates | free, CC0 |
| [NIH RePORTER](https://api.reporter.nih.gov/) | NIH-funded projects and their investigators (USA) | free, about one request a second |
| [UKRI Gateway to Research](https://gtr.ukri.org/resources/api.html) | UKRI-funded projects, lead investigators and organisations (UK) | free |
| [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) | registered studies, their investigators and sites | free |

Only the official APIs are used. Requests are paced to each source's limits, sent with a clear User-Agent, and kept in
a local cache for seven days, so a repeated search costs the sources nothing.

## Install

Python 3.10 or newer.

```bash
pip install "labscout @ git+https://github.com/actogram/scholar-mcp"
```

For development:

```bash
git clone https://github.com/actogram/scholar-mcp
cd scholar-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## The web page

The hosted page is at https://actogram-labscout.hf.space. To run it on your own computer:

```bash
labscout serve                     # http://127.0.0.1:8000, with the MCP server at /mcp
```

Type a topic and press **Find labs**. A new topic takes about a minute; the page shows each step of the search and
refreshes by itself. The report says how many papers the sources have and how many were read, gives a hint when the
search is very broad or very narrow, and has charts of labs by country and papers by year, a map of the labs with a
known place, a table you can sort and filter with the papers behind each lab, and downloads as Excel, CSV and JSON.
The start page explains the steps and gives search tips.

## From an AI assistant (MCP)

```bash
labscout mcp                       # stdio, for assistants on this computer
labscout mcp --http --port 8000    # Streamable HTTP at http://127.0.0.1:8000/mcp
```

Most MCP clients take a configuration like this:

```json
{
  "mcpServers": {
    "labscout": { "command": "labscout", "args": ["mcp"] }
  }
}
```

The hosted LabScout works the same way: add `https://actogram-labscout.hf.space/mcp` as a custom connector.

The tools, all read-only:

| Tool | What it does |
|---|---|
| `find_labs` | labs working on a topic, ranked, with the reason each one came up; optional NIH grants |
| `search_papers` | papers on a topic from PubMed and Europe PMC, the most relevant or the newest, with species and data hints |
| `lab_profile` | one researcher: organisations, years, co-authors, topics, recent papers, NIH grants |
| `find_grants` | funded projects from NIH RePORTER and UKRI Gateway to Research |
| `find_trials` | registered studies on ClinicalTrials.gov with investigators and sites |
| `find_patents` | patents on a topic as background: inventors, country, CPC classes, Espacenet link (records up to 2014) |

## From the command line

```bash
labscout labs "actigraphy sleep regularity older adults" --from 2020 --xlsx labs.xlsx --html labs.html
labscout labs "circadian rhythm shift work" --from 2022 --grants 5      # NIH grants for the five top labs
labscout labs "chronotype[tiab] adolescents" --from 2021 --order newest # the newest papers instead
labscout papers "wearable step counts circadian" --max 20
labscout profile "Susan Redline" --topic "sleep regularity"
labscout grants --pi "Susan Redline"                                     # NIH RePORTER
labscout grants --text "circadian actigraphy"                            # NIH RePORTER and UKRI
labscout trials "actigraphy sleep"
labscout patents "actigraphy AND sleep"
```

Searches use PubMed syntax, so `actigraphy AND "sleep regularity"`, `OR`, `NOT` and field tags such as `[tiab]` work;
LabScout puts them in Europe PMC's terms for that source. Each source gives at most `--max` papers: by default PubMed's
best matches and the most cited on Europe PMC, with `--order newest` the newest.

## Settings

| Variable | Meaning |
|---|---|
| `LABSCOUT_EMAIL` | your contact address, sent to NCBI and in the User-Agent as their policies ask (recommended) |
| `NCBI_API_KEY` | an [NCBI API key](https://support.nlm.nih.gov/kbArticle/?pn=KA-05317) for faster PubMed searches |
| `LABSCOUT_CACHE_DIR` | where the cache lives (default `~/.cache/labscout`); an empty value switches it off |
| `LABSCOUT_WEB_MAX_PAPERS` | papers per source for one search on the web page (default 10000) |
| `LABSCOUT_ROR_INDEX` | a local copy of the ROR registry, made with `labscout ror-index ror_index.json.gz`; organisations are then matched in memory, which makes big searches many times faster |
| `LABSCOUT_ROR_API_BUDGET` | with the local copy, how many affiliations of one search may still go to the ROR API (default 20) |
| `LABSCOUT_SEARCHES_PER_HOUR` | searches one visitor of the web page can start in an hour (default 20) |
| `LABSCOUT_PARALLEL_SEARCHES` | searches the web page runs at the same time (default 2) |
| `LABSCOUT_ALLOWED_HOSTS` | host names the MCP endpoint answers for, besides localhost (Hugging Face sets `SPACE_HOST` itself) |
| `LABSCOUT_HIDE` | people who asked not to be shown, as ORCID iDs or names separated by `;` (a name hides everyone with that last name and first initial) |

## Host it

The folder `deploy/huggingface` holds a Docker setup for a [Hugging Face Docker Space](https://huggingface.co/docs/hub/spaces-sdks-docker),
which also runs anywhere Docker does:

```bash
deploy/huggingface/build_space.sh build/space       # the Space files: Dockerfile, card, package
docker build -t labscout build/space
docker run -p 7860:7860 -e LABSCOUT_EMAIL=you@example.org labscout
```

To publish a Space, upload `build/space` to a new Docker Space and set `LABSCOUT_EMAIL` as a Space variable. The web page
and the MCP endpoint (`https://<space>.hf.space/mcp`) then run together.

## How a lab is found

1. Papers on the topic come from PubMed (its Best Match order) and Europe PMC (titles and abstracts, most cited first;
   its own relevance order is mostly by date), or the newest of both, and are merged by PMID, DOI or title and year.
2. The senior (last) author of each paper leads its lab. Older PubMed records list only the first author's
   affiliation; then the lab is placed with that one.
3. The affiliation is matched to an organisation in ROR. A match is accepted only when ROR is confident, or when a
   name search finds an organisation whose name words all appear in the affiliation and whose country agrees. Otherwise
   only the country is taken from the text. The column `match` (`ror`, `ror-name` or `text`) shows which.
4. One person at two organisations is one lab when it is clearly the same person: the same city, such as a university
   and its hospital, or the same ORCID iD. Otherwise the same name stays apart, because it may be two people.
5. Labs are ranked by papers led, papers co-authored, recent work, the kinds of data mentioned and the search words
   found. A co-authored paper counts only when the co-author is clearly the same person: the same ORCID iD, or the
   lab's city or organisation in the affiliation.

## Privacy and fair use

LabScout shows information that researchers have made public in their work: names, affiliations, publications, grants,
patents and registered studies. It removes e-mail addresses from affiliations and never returns them. Use the results to
find research and collaborators, not to judge people. Organisation matching is automatic and can be wrong, so check
before you act on a result. The web page has a privacy notice at `/privacy`; people who ask not to be shown are hidden
with `LABSCOUT_HIDE`.

## Development

```bash
ruff check src tests && ruff format --check src tests
pytest                 # offline tests on recorded answers of the real APIs
pytest -m network      # a few live requests to the public APIs
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Planned next: newer patents through a patent office service, EU grants from
CORDIS.

## Cite

See [CITATION.cff](CITATION.cff). Please cite the version you used.

## Licence

MIT, see [LICENSE](LICENSE). The data belongs to its sources and keeps their terms.
