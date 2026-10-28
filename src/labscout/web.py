"""The web page and the MCP server in one app: `labscout serve` (also what the Hugging Face Space runs).

/           a search form, with how it works and search tips
/search     the report for a search: map, charts, table, downloads; while it runs, a page with the steps
/download   the last results as Excel, CSV or JSON
/privacy    what the page and the tools do with personal data
/mcp        the MCP server (Streamable HTTP) for AI assistants
/health     a plain status answer, and /robots.txt
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import threading
import time
from collections import OrderedDict, defaultdict, deque
from datetime import date
from typing import Any
from urllib.parse import urlencode

import anyio
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route

from . import __version__, art
from .config import REPO
from .errors import SearchError
from .export import csv_text, render_html, xlsx_bytes
from .pipeline import ORDERS, SEARCH_SLOTS, Result, find_labs
from .server import mcp
from .sources import PUBLICATION_SOURCES

MAX_PAPERS = int(os.environ.get("LABSCOUT_WEB_MAX_PAPERS", "10000"))  # per source, for one search on the page
PER_HOUR = int(os.environ.get("LABSCOUT_SEARCHES_PER_HOUR", "20"))  # per visitor
KEEP = 50  # recent results kept in memory for the download links
log = logging.getLogger(__name__)
FRAMES = "frame-ancestors 'self' https://huggingface.co https://*.hf.space"  # the Space page shows the app in a frame
SECURITY = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src 'self' data:; form-action 'self'; base-uri 'none'; " + FRAMES,
}
# the report also loads the map library and the map tiles
REPORT_SECURITY = SECURITY | {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline' https://unpkg.com; "
    "script-src 'unsafe-inline' https://unpkg.com; img-src 'self' data: https://unpkg.com https://tile.openstreetmap.org; "
    "form-action 'self'; base-uri 'none'; " + FRAMES,
}
EXAMPLES = [
    "actigraphy sleep regularity",
    "circadian rhythm shift work",
    "chronotype adolescents",
    '"social jetlag"',
    "wearable step count mortality",
    "(actigraphy OR accelerometry) AND depression",
]
STEPS = {
    "pubmed": "Search PubMed",
    "europepmc": "Search Europe PMC",
    "organisations": "Match each lab's organisation",
    "labs": "Rank the labs and draw the map",
}

_results: OrderedDict[str, Result] = OrderedDict()
_jobs: dict[str, dict[str, Any]] = {}  # searches still running, or failed
_lock = threading.Lock()
_visits: dict[str, deque[float]] = defaultdict(deque)


def _visitor(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _allowed(who: str) -> bool:
    now = time.time()
    if len(_visits) > 5000:  # forget the visitors who have not searched for an hour
        for k in [k for k, v in _visits.items() if not v or now - v[-1] > 3600]:
            del _visits[k]
    seen = _visits[who]
    while seen and now - seen[0] > 3600:
        seen.popleft()
    if len(seen) >= PER_HOUR:
        return False
    seen.append(now)
    return True


def _year(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isdigit() and 1800 <= int(value) <= 2100 else None


def _page(body: str, title: str = "Actogram LabScout", status: int = 200) -> HTMLResponse:
    page = PAGE.replace("{{TITLE}}", html.escape(title)).replace("{{BODY}}", body).replace("{{VERSION}}", __version__)
    return HTMLResponse(page, status_code=status, headers=SECURITY)


async def home(request: Request) -> HTMLResponse:
    base = str(request.base_url).rstrip("/")
    since = str(date.today().year - 5)
    examples = " ".join(
        f'<a href="search?{html.escape(urlencode({"topic": t, "from": since}))}">{html.escape(t)}</a>' for t in EXAMPLES
    )
    body = FORM
    for k, v in {
        "{{MCP}}": html.escape(f"{base}/mcp"),
        "{{REPO}}": REPO,
        "{{MAX}}": f"{MAX_PAPERS:,}",
        "{{FROM}}": since,
        "{{EXAMPLES}}": examples,
        "{{ART}}": art.HERO,
        "{{STEP_TOPIC}}": art.STEP_TOPIC,
        "{{STEP_PAPERS}}": art.STEP_PAPERS,
        "{{STEP_LAB}}": art.STEP_LAB,
        "{{STEP_MAP}}": art.STEP_MAP,
    }.items():
        body = body.replace(k, v)
    return _page(body)


async def privacy(request: Request) -> HTMLResponse:
    return _page(PRIVACY, title="Privacy | Actogram LabScout")


def _work(key: str, topic: str, start: int | None, end: int | None, sources: list[str], order: str) -> None:
    """One search, in its own thread; the page polls until it is done and shows the steps meanwhile."""

    def progress(step: str, text: str) -> None:
        with _lock:
            if key in _jobs:
                _jobs[key]["steps"][step] = text

    try:
        if not SEARCH_SLOTS.acquire(blocking=False):
            progress("queue", "Waiting for a free place: other searches are running")
            SEARCH_SLOTS.acquire()
        try:
            result = find_labs(topic, start, end, MAX_PAPERS, sources, order=order, progress=progress)
        finally:
            SEARCH_SLOTS.release()
        with _lock:
            _results[key] = result
            while len(_results) > KEEP:
                _results.popitem(last=False)
            _jobs.pop(key, None)
    except SearchError as err:
        with _lock:
            _jobs[key] = {"error": str(err), "started": _jobs.get(key, {}).get("started", time.time())}
    except Exception as err:  # a source failing badly: say so on the page, keep the server running
        log.exception("search failed")
        with _lock:
            _jobs[key] = {
                "error": f"The search failed ({type(err).__name__}). Please try again in a minute.",
                "started": time.time(),
            }


def _steps(job: dict[str, Any]) -> str:
    """The steps of a running search: done, now, still to come."""
    told = dict(job.get("steps", {}))
    order = [s for s in job.get("sources", PUBLICATION_SOURCES)] + ["organisations", "labs"]
    started = [s for s in order if s in told]
    items = []
    if "queue" in told and not started:
        items.append(f'<li class="now">{html.escape(told["queue"])}</li>')
    for s in order:
        if s in told:
            state = "now" if s == started[-1] else "done"
            items.append(f'<li class="{state}">{html.escape(told[s])}</li>')
        else:
            items.append(f'<li class="todo">{html.escape(STEPS.get(s, s))}</li>')
    return '<ol class="steps">' + "".join(items) + "</ol>"


async def search(request: Request) -> Response:
    q = request.query_params
    topic = (q.get("topic") or "").strip()[:300]
    if not topic:
        return _page(FORM_ERROR.format(msg="Type a topic to search for."), status=400)
    start, end = _year(q.get("from")), _year(q.get("to"))
    if start and end and start > end:
        start, end = end, start
    sources = [s for s in q.getlist("source") if s in PUBLICATION_SOURCES] or list(PUBLICATION_SOURCES)
    order = q.get("order") if q.get("order") in ORDERS else "relevance"
    key = hashlib.sha256(json.dumps([topic, start, end, sources, order]).encode()).hexdigest()[:16]
    with _lock:
        result = _results.get(key)
        job = _jobs.get(key)
        if result is not None:
            _results.move_to_end(key)
    if result is not None:
        toolbar = (
            f'<p class="tools"><a href="./">New search</a><a href="download/{key}.xlsx">Excel</a>'
            f'<a href="download/{key}.csv">CSV</a><a href="download/{key}.json">JSON</a></p>'
        )
        footer = '<p><a href="./">New search</a>. <a href="privacy">Privacy</a>.</p>'
        page = render_html(result, top=200, toolbar=toolbar, footer=footer)
        return HTMLResponse(page, headers=REPORT_SECURITY)
    if job and "error" in job:
        with _lock:
            _jobs.pop(key, None)
        return _page(FORM_ERROR.format(msg=html.escape(job["error"])), status=400)
    if job is None:
        if not _allowed(_visitor(request)):
            return _page(
                FORM_ERROR.format(msg=f"You have run {PER_HOUR} searches this hour. Please try again later."),
                status=429,
            )
        with _lock:
            job = _jobs.setdefault(key, {"started": time.time(), "steps": {}, "sources": sources})
        threading.Thread(target=_work, args=(key, topic, start, end, sources, order), daemon=True).start()
    with _lock:
        steps = _steps(job)
    waited = int(time.time() - job["started"])
    body = WAIT.format(topic=html.escape(topic), steps=steps, waited=waited)
    resp = _page(body, title="Searching | Actogram LabScout")
    resp.headers["Refresh"] = "4"
    return resp


async def download(request: Request) -> Response:
    key, fmt = request.path_params["key"], request.path_params["fmt"]
    result = _results.get(key)
    if result is None:
        return PlainTextResponse("These results are no longer kept. Please run the search again.", status_code=404)
    name = f"labscout_{key}.{fmt}"
    disposition = {"Content-Disposition": f'attachment; filename="{name}"'}
    if fmt == "xlsx":
        data = await anyio.to_thread.run_sync(lambda: xlsx_bytes(result))
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return Response(data, media_type=mime, headers=disposition)
    if fmt == "csv":
        return Response(csv_text(result), media_type="text/csv; charset=utf-8", headers=disposition)
    body = json.dumps(result.summary(top=len(result.labs)), ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json", headers=disposition)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


async def robots(request: Request) -> PlainTextResponse:
    """Search engines may read the pages, but not start searches or downloads: each one costs the sources work."""
    return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /search\nDisallow: /download/\nDisallow: /mcp\n")


async def mcp_get(request: Request) -> PlainTextResponse:
    """The server is stateless and sends no messages of its own, so it offers no stream to open with GET."""
    return PlainTextResponse("Use POST for MCP requests.", status_code=405, headers={"Allow": "POST"})


def mcp_security() -> TransportSecuritySettings:
    """The MCP endpoint answers only for this site's own host names, against DNS rebinding. Hugging Face Spaces set
    SPACE_HOST; other hosts can be added in LABSCOUT_ALLOWED_HOSTS (comma separated)."""
    hosts = [h.strip() for h in os.environ.get("LABSCOUT_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if os.environ.get("SPACE_HOST"):
        hosts.append(os.environ["SPACE_HOST"])
    local = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    origins = [f"https://{h}" for h in hosts] + ["http://localhost:*", "http://127.0.0.1:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts + local, allowed_origins=origins
    )


def create_app() -> Starlette:
    # stateless: every request stands alone, so a restart of the Space never strands an assistant's session
    mcp_app = mcp.streamable_http_app(stateless_http=True, transport_security=mcp_security())
    pages = Starlette(
        routes=[
            Route("/", home),
            Route("/search", search),
            Route("/download/{key:str}.{fmt:str}", download),
            Route("/privacy", privacy),
            Route("/health", health),
            Route("/robots.txt", robots),
        ],
        middleware=[Middleware(GZipMiddleware, minimum_size=1000)],  # pages only: the MCP answers stream
    )
    routes: list[Any] = [Route("/mcp", mcp_get, methods=["GET"]), *mcp_app.routes, Mount("/", app=pages)]
    return Starlette(routes=routes, lifespan=mcp_app.router.lifespan_context)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, proxy_headers=True, forwarded_allow_ips="*")


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<meta name="description" content="Find the labs, people and studies behind a research topic, on a map, from public sources.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='13' cy='13' r='8.5' fill='none' stroke='%23006956' stroke-width='3.5'/%3E%3Cpath d='M19.5 19.5l7 7' stroke='%23006956' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E">
<style>
:root { --ink:#1d2b27; --soft:#4f5a56; --green:#006956; --deep:#00473a; --mint:#d8f8f2; --tint:#f1f8f5; --line:#dfe8e4; }
* { box-sizing:border-box; }
body { margin:0; font:17px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color:var(--ink); background:#fff; }
main { max-width:900px; margin:0 auto; padding:36px 20px 56px; }
h1 { font-size:34px; line-height:1.15; margin:0 0 10px; letter-spacing:-.01em; }
h1 span { color:var(--green); }
.lead { color:var(--soft); font-size:19px; margin:0 0 26px; }
.hero { display:grid; grid-template-columns:1fr 250px; gap:28px; align-items:center; }
.hero .lead { margin-bottom:22px; }
.art-hero { width:100%; height:auto; }
form { display:grid; gap:14px; padding:22px; border:1px solid var(--line); border-radius:14px; background:var(--tint); }
label { display:grid; gap:6px; font-weight:600; font-size:15px; }
input[type=text], input[type=number] { font:inherit; padding:11px 13px; border:1px solid #b9cbc4; border-radius:9px; background:#fff; }
.row { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
fieldset { border:0; padding:0; margin:0; display:flex; flex-wrap:wrap; gap:4px 20px; font-size:15px; }
fieldset legend { font-weight:600; margin-bottom:4px; padding:0; }
label.check { display:inline-flex; align-items:center; gap:8px; min-height:32px; font-weight:500; cursor:pointer; }
label.check input { width:20px; height:20px; margin:0; accent-color:var(--green); }
button { font:inherit; font-weight:600; padding:12px 18px; border:0; border-radius:10px; background:var(--green); color:#fff; cursor:pointer; }
button:hover { background:var(--deep); }
.note { color:var(--soft); font-size:15px; }
.examples a { display:inline-block; margin:0 14px 6px 0; padding:2px 0; }
h2 { font-size:22px; margin:38px 0 10px; }
code { font:14.5px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:var(--tint); padding:2px 6px; border-radius:6px; overflow-wrap:anywhere; }
.how { list-style:none; margin:12px 0 0; padding:0; display:grid; grid-template-columns:repeat(4, 1fr); gap:14px; }
.how li { display:grid; gap:6px; align-content:start; padding:14px; border:1px solid var(--line); border-radius:12px; font-size:15px; }
.how svg { width:100%; max-width:120px; height:auto; }
.how b { font-size:15.5px; line-height:1.3; }
.how span { color:var(--soft); }
.tips { width:100%; border-collapse:collapse; font-size:15px; margin:8px 0 6px; }
.tips th, .tips td { text-align:left; vertical-align:top; padding:8px 10px; border-bottom:1px solid var(--line); }
.tips th { background:var(--tint); font-size:14px; }
.tips td:first-child { width:42%; }
ul.plain { padding-left:20px; }
ul.plain li { margin:0 0 8px; }
.steps { list-style:none; margin:22px 0; padding:0; display:grid; gap:12px; font-size:17px; }
.steps li { position:relative; padding-left:34px; min-height:22px; }
.steps li::before { content:""; position:absolute; left:0; top:2px; width:18px; height:18px; border:2px solid var(--line); border-radius:50%; }
.steps li.done::before { content:"\2713"; border-color:var(--green); background:var(--green); color:#fff; font:700 12px/18px system-ui, sans-serif; text-align:center; }
.steps li.now { font-weight:600; }
.steps li.now::before { border-color:var(--green); border-top-color:transparent; animation:spin 1s linear infinite; }
.steps li.todo { color:var(--soft); }
@keyframes spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion:reduce) { .steps li.now::before { animation:none; border-top-color:var(--green); } }
.err { padding:12px 14px; border-radius:10px; background:#fdeeee; color:#7a1f1f; margin:0 0 16px; }
a { color:var(--green); }
footer { color:var(--soft); font-size:14px; margin-top:40px; border-top:1px solid var(--line); padding-top:16px; }
.wait { display:none; color:var(--soft); margin:0; }
form.busy .wait { display:block; }
@media (max-width:760px) { .hero { grid-template-columns:1fr; } .art-hero { max-width:300px; } .how { grid-template-columns:1fr 1fr; } }
@media (max-width:600px) { h1 { font-size:28px; } .row { grid-template-columns:1fr; } }
@media (max-width:460px) { .how { grid-template-columns:1fr; } .how svg { max-width:100px; } }
</style>
</head>
<body>
<main>
{{BODY}}
<footer>Actogram LabScout {{VERSION}}. Open source under the MIT licence, part of
  <a href="https://actogram.org">Actogram Open Science</a>. Data from PubMed, Europe PMC, ROR, NIH RePORTER, UKRI
  Gateway to Research and ClinicalTrials.gov, shown as published, without e-mail addresses.
  <a href="privacy">Privacy</a>.</footer>
</main>
<script>
document.querySelectorAll('form').forEach(function (f) { f.addEventListener('submit', function () { f.classList.add('busy'); }); });
</script>
</body>
</html>
"""

FORM = """<div class="hero">
<div>
<h1>Who works on your topic, <span>and where?</span></h1>
<p class="lead">LabScout reads the key papers on a topic from PubMed and Europe PMC, finds the lab behind each one,
  puts the labs on a map and says why each came up.</p>
</div>
{{ART}}
</div>
<form action="search" method="get">
  <label>Topic<input type="text" name="topic" required maxlength="300"
    placeholder="for example: actigraphy sleep regularity"></label>
  <div class="row">
    <label>From year<input type="number" name="from" min="1900" max="2100" value="{{FROM}}"></label>
    <label>To year<input type="number" name="to" min="1900" max="2100" placeholder="now"></label>
  </div>
  <div class="row">
    <fieldset><legend>Sources</legend>
      <label class="check"><input type="checkbox" name="source" value="pubmed" checked> PubMed</label>
      <label class="check"><input type="checkbox" name="source" value="europepmc" checked> Europe PMC</label>
    </fieldset>
    <fieldset><legend>Papers to read</legend>
      <label class="check"><input type="radio" name="order" value="relevance" checked> Most relevant</label>
      <label class="check"><input type="radio" name="order" value="newest"> Newest</label>
    </fieldset>
  </div>
  <button type="submit">Find labs</button>
  <p class="wait">Starting the search. The next page shows each step; most topics take under a minute, a very broad one
    with thousands of papers two or three.</p>
  <p class="note">LabScout reads up to {{MAX}} papers from each source: PubMed's best matches and the most cited on
    Europe PMC, or the newest. The last five years show the labs that are active now; clear the year to search all
    years.</p>
</form>
<p class="note examples">Try: {{EXAMPLES}}</p>

<h2>How it works</h2>
<ol class="how">
  <li>{{STEP_TOPIC}}<b>1. Type a topic</b><span>A few key words, or a PubMed search with quotes, OR and NOT.</span></li>
  <li>{{STEP_PAPERS}}<b>2. LabScout reads the papers</b><span>The {{MAX}} best matches on PubMed and the {{MAX}} most
    cited on Europe PMC, in the years you choose.</span></li>
  <li>{{STEP_LAB}}<b>3. It finds the lab behind each paper</b><span>The last author usually leads the lab. Their
    affiliation is matched to an organisation in the Research Organization Registry.</span></li>
  <li>{{STEP_MAP}}<b>4. You see who works on it, and where</b><span>A map, a table with the reason each lab came up and
    its papers, and Excel, CSV or JSON.</span></li>
</ol>

<h2>Search tips</h2>
<table class="tips">
  <thead><tr><th scope="col">To find</th><th scope="col">Type</th></tr></thead>
  <tbody>
    <tr><td>Papers on a topic</td><td><code>actigraphy sleep regularity</code></td></tr>
    <tr><td>An exact phrase</td><td><code>"sleep regularity index"</code></td></tr>
    <tr><td>Either of two words</td><td><code>actigraphy OR accelerometry</code></td></tr>
    <tr><td>Without a word</td><td><code>circadian NOT mice</code></td></tr>
    <tr><td>A word in the title or abstract only</td><td><code>chronotype[tiab] adolescents</code></td></tr>
    <tr><td>Groups put together</td><td><code>(actigraphy OR accelerometry) AND depression</code></td></tr>
  </tbody>
</table>
<p class="note">Too many papers? Add a word, use quotes or narrow the years. Too few? Use fewer words or OR. The report
  says which, and shows how PubMed read your search.</p>

<h2>Reading the results</h2>
<ul class="plain">
  <li>Each lab is named after the last author of its papers, who usually leads it. Older PubMed records give only the
    first author's affiliation; then the lab is placed there.</li>
  <li>Organisations are matched automatically. In Excel, the column <i>match</i> says how each one was found: check it
    before you write to anyone.</li>
  <li>One person at two places is one lab when it is clearly the same person: the same city, or the same ORCID iD.
    Otherwise the name shows twice, because it may be two people.</li>
  <li>LabScout shows what researchers have published. Use it to find research and collaborators, not to judge
    people.</li>
</ul>

<h2>Use it from your AI assistant</h2>
<p>LabScout is also an MCP server with tools for labs, papers, researcher profiles, grants, trials and patents. Add this
  address as a custom connector in an assistant that supports MCP:</p>
<p><code>{{MCP}}</code></p>
<p>Then ask in plain words, for example:</p>
<ul class="plain">
  <li>Find labs working on sleep regularity in older adults since {{FROM}} and list the ten top ones with their
    organisations.</li>
  <li>Make a profile of Susan Redline: topics, frequent co-authors and NIH grants.</li>
  <li>Which registered studies on actigraphy and sleep are recruiting now?</li>
</ul>

<h2>Run it yourself</h2>
<p>The code is on <a href="{{REPO}}">GitHub</a>. It installs with <code>pip install "labscout @ git+{{REPO}}"</code> and
  then runs as <code>labscout labs "your topic" --html labs.html</code>.</p>
"""

FORM_ERROR = '<p class="err">{msg}</p><p><a href="./">Back to the search</a></p>'

WAIT = """<h1>Searching for <span>{topic}</span></h1>
<p class="lead">A new topic takes about a minute. This page follows the search and shows the report when it is
  ready.</p>
{steps}
<p class="note">{waited} seconds so far.</p>
<p><a href="./">Back to the search</a></p>"""

PRIVACY = """<h1>Privacy</h1>
<p class="lead">What LabScout does with personal data, on this page and in its tools for AI assistants.</p>

<h2>Who we are</h2>
<p>LabScout is run by Actogram Ltd, registered in England and Wales (company No. 14594952), 71-75 Shelton Street,
  Covent Garden, London WC2H 9JQ, United Kingdom, and registered with the UK Information Commissioner's Office
  (ZC252163). For anything about your data, write to <a href="mailto:services@actogram.ai">services@actogram.ai</a>.
  Our representative in the EU is Prighter:
  <a href="https://app.prighter.com/portal/11935821603">app.prighter.com/portal/11935821603</a>.</p>

<h2>When you use LabScout</h2>
<ul class="plain">
  <li>There are no accounts, no cookies and no analytics.</li>
  <li>Hugging Face hosts LabScout and processes technical data such as your IP address to deliver the page; see the
    <a href="https://huggingface.co/privacy">Hugging Face privacy policy</a>.</li>
  <li>To keep the tool fair, the page counts the searches from each IP address for one hour. The count stays in the
    server's memory and is not stored.</li>
  <li>Your search words go to PubMed (US National Library of Medicine) and Europe PMC (EMBL-EBI), and the
    affiliations in the papers go to the Research Organization Registry, to find the papers and the organisations.
    The last 50 reports stay in memory for the download links, and the answers of the sources are kept for seven
    days so that a repeated search is fast.</li>
  <li>Requests from an AI assistant are handled the same way.</li>
</ul>

<h2>Researchers shown in LabScout</h2>
<p>LabScout shows what researchers have made public in their work: names and affiliations as printed in
  publications, grants and trial registers, the places of those organisations, and the publications, grants and
  studies themselves. It takes them from PubMed, Europe PMC (including its patent records), the Research Organization
  Registry, NIH RePORTER, UKRI Gateway to Research and ClinicalTrials.gov. It removes e-mail addresses and collects no
  other contact details.</p>
<p>The legal basis is our legitimate interest, and that of the people who use LabScout, in finding research and
  collaborators. The information is professional, already public and shown in its original context.</p>
<p>You can object at any time and ask us to hide your entry. Write to
  <a href="mailto:services@actogram.ai">services@actogram.ai</a> with your name and, if you have one, your ORCID iD.
  A hidden entry stays hidden in later searches.</p>

<h2>Your rights</h2>
<p>You can ask to see the data we hold about you, to correct or delete it, to restrict its use, or object to it. We
  answer within one month. You can also complain to the UK Information Commissioner's Office (ico.org.uk) or, in the
  EU, to the data protection authority where you live or work.</p>
<p class="note">Last updated 27 October 2026.</p>
"""
