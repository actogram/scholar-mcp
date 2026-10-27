"""Command line: `actogram-scholar labs "actigraphy sleep regularity" --from 2020 --xlsx labs.xlsx --html labs.html`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap

from . import __version__
from .errors import SearchError
from .export import to_csv, to_html, to_json, to_xlsx
from .http import Http
from .pipeline import collect, find_labs, profile, split_name
from .sources import PUBLICATION_SOURCES, clinicaltrials, nih_reporter


def _sources(value: str) -> list[str]:
    chosen = [s.strip() for s in value.split(",") if s.strip()]
    bad = [s for s in chosen if s not in PUBLICATION_SOURCES]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown source {', '.join(bad)}; use {', '.join(PUBLICATION_SOURCES)}")
    return chosen


def _years(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from", dest="start", type=int, help="first publication year")
    p.add_argument("--to", dest="end", type=int, help="last publication year")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="actogram-scholar", description="Find the labs, people and studies behind a topic."
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("-v", "--verbose", action="store_true", help="show what is being fetched")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("labs", help="labs working on a topic, ranked, with the reason each one came up")
    p.add_argument("topic")
    _years(p)
    p.add_argument("--max", type=int, default=200, help="papers to read from each source (default 200)")
    p.add_argument("--top", type=int, default=25, help="labs to print (default 25; files get all labs)")
    p.add_argument(
        "--sources", type=_sources, default=list(PUBLICATION_SOURCES), help="pubmed,europepmc (default both)"
    )
    p.add_argument("--grants", type=int, default=0, metavar="N", help="add NIH grants for the N top labs")
    for fmt in ("xlsx", "html", "json", "csv"):
        p.add_argument(f"--{fmt}", metavar="FILE", help=f"save the results as {fmt.upper()}")

    p = sub.add_parser("papers", help="papers on a topic, merged across sources")
    p.add_argument("topic")
    _years(p)
    p.add_argument("--max", type=int, default=25)
    p.add_argument("--sources", type=_sources, default=list(PUBLICATION_SOURCES))
    p.add_argument("--json", action="store_true", help="print JSON")

    p = sub.add_parser("profile", help="one researcher: places, co-authors, topics, recent papers, NIH grants")
    p.add_argument("name", help='"Susan Redline" or "Redline, Susan"')
    p.add_argument("--topic", default="")
    p.add_argument("--organization", default="")
    p.add_argument("--max", type=int, default=100)

    p = sub.add_parser("trials", help="registered studies on ClinicalTrials.gov with investigators and sites")
    p.add_argument("topic")
    p.add_argument("--max", type=int, default=25)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("grants", help="NIH-funded projects from NIH RePORTER")
    p.add_argument("--pi", default="", help='investigator, e.g. "Susan Redline"')
    p.add_argument("--text", default="", help="words in the project title and terms")
    p.add_argument("--since", type=int, help="first fiscal year (default: the last five years)")
    p.add_argument("--max", type=int, default=25)

    p = sub.add_parser("mcp", help="run the MCP server for AI assistants")
    p.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    return ap


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    if args.command == "mcp":
        from .server import run

        run(http=args.http, host=args.host, port=args.port)
        return 0
    if args.command == "labs":
        res = find_labs(args.topic, args.start, args.end, args.max, args.sources, grants=args.grants)
        print(
            f"{res.counts.get('papers', 0)} papers, {len(res.labs)} labs "
            f"({', '.join(f'{k} {v}' for k, v in res.counts.items() if k in PUBLICATION_SOURCES)})"
        )
        for i, lab in enumerate(res.labs[: args.top], 1):
            org = lab.organization
            place = ", ".join(x for x in (org.city, org.country_name or org.country) if x)
            print(f"{i:>3}. {lab.lead} | {_short(org.name, 48)}{' (' + place + ')' if place else ''}")
            print(textwrap.indent(textwrap.fill(lab.why, 110), "     "))
        for fmt, writer in (("xlsx", to_xlsx), ("html", to_html), ("json", to_json), ("csv", to_csv)):
            target = getattr(args, fmt)
            if target:
                print(f"saved {writer(res, target)}")
        return 0
    if args.command == "papers":
        with Http() as http:
            papers, counts = collect(http, args.topic, args.start, args.end, args.max, args.sources)
        papers.sort(key=lambda p: -(p.year or 0))
        if args.json:
            print(
                json.dumps(
                    {"counts": counts, "papers": [p.brief() for p in papers[: args.max]]}, ensure_ascii=False, indent=2
                )
            )
        else:
            for p in papers[: args.max]:
                lead = p.authors[-1].display if p.authors else ""
                print(f"{p.year or '----'}  {_short(p.title, 90)}\n      {lead} | {p.url}")
        return 0
    if args.command == "profile":
        print(json.dumps(profile(args.name, args.topic, args.organization, args.max), ensure_ascii=False, indent=2))
        return 0
    if args.command == "trials":
        with Http() as http:
            trials = clinicaltrials.search(http, args.topic, args.max)
        if args.json:
            print(json.dumps([t.__dict__ | {"url": t.url} for t in trials], ensure_ascii=False, indent=2))
        else:
            for t in trials:
                who = "; ".join(f"{o['name']} ({o['role']})" for o in t.officials[:2])
                print(
                    f"{t.nct_id}  {_short(t.title, 90)}\n      {t.status} | {t.sponsor} | {who} | {len(t.sites)} sites"
                )
        return 0
    if args.command == "grants":
        if not args.pi and not args.text:
            print("give --pi, --text or both", file=sys.stderr)
            return 2
        last, first = split_name(args.pi) if args.pi else ("", "")
        with Http() as http:
            grants = nih_reporter.search(
                http,
                pi_last=last,
                pi_first=first.split(" ")[0] if first else "",
                text=args.text,
                since=args.since,
                limit=args.max,
            )
        for g in grants:
            print(
                f"{g.fiscal_year}  {g.number}  {_short(g.title, 80)}\n"
                f"      {g.organization} | {', '.join(g.investigators)}"
            )
        return 0
    return 1


def run() -> int:
    try:
        return main()
    except SearchError as err:
        print(f"actogram-scholar: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run())
