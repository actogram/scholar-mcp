"""The web page and the MCP server in one app: `labscout serve` (also what the Hugging Face Space runs).

/           a search form
/search     the report for a search: map, table, downloads
/download   the last results as Excel, CSV or JSON
/mcp        the MCP server (Streamable HTTP) for AI assistants
/health     a plain status answer
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
from typing import Any

import anyio
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from . import __version__
from .config import REPO
from .errors import SearchError
from .export import csv_text, render_html, xlsx_bytes
from .pipeline import Result, find_labs
from .server import mcp
from .sources import PUBLICATION_SOURCES

MAX_PAPERS = int(os.environ.get("LABSCOUT_WEB_MAX_PAPERS", "100"))  # per source, for one search on the page
PER_HOUR = int(os.environ.get("LABSCOUT_SEARCHES_PER_HOUR", "20"))  # per visitor
KEEP = 50  # recent results kept in memory for the download links
RUNNING = threading.BoundedSemaphore(int(os.environ.get("LABSCOUT_PARALLEL_SEARCHES", "2")))
log = logging.getLogger(__name__)
SECURITY = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # the Space page on huggingface.co shows the app in a frame
    "Content-Security-Policy": "frame-ancestors 'self' https://huggingface.co https://*.hf.space",
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
    return _page(
        FORM.replace("{{MCP}}", html.escape(f"{base}/mcp"))
        .replace("{{REPO}}", REPO)
        .replace("{{MAX}}", str(MAX_PAPERS))
    )


def _work(key: str, topic: str, start: int | None, end: int | None, sources: list[str]) -> None:
    """One search, in its own thread; the page polls until it is done."""
    try:
        with RUNNING:
            result = find_labs(topic, start, end, MAX_PAPERS, sources)
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


async def search(request: Request) -> Response:
    q = request.query_params
    topic = (q.get("topic") or "").strip()[:300]
    if not topic:
        return _page(FORM_ERROR.format(msg="Type a topic to search for."), status=400)
    start, end = _year(q.get("from")), _year(q.get("to"))
    sources = [s for s in q.getlist("source") if s in PUBLICATION_SOURCES] or list(PUBLICATION_SOURCES)
    key = hashlib.sha256(json.dumps([topic, start, end, sources]).encode()).hexdigest()[:16]
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
        return HTMLResponse(render_html(result, top=200, toolbar=toolbar), headers=SECURITY)
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
            job = _jobs.setdefault(key, {"started": time.time()})
        threading.Thread(target=_work, args=(key, topic, start, end, sources), daemon=True).start()
    waited = int(time.time() - job["started"])
    body = WAIT.format(topic=html.escape(topic), waited=waited)
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
    routes: list[Any] = [
        Route("/", home),
        Route("/search", search),
        Route("/download/{key:str}.{fmt:str}", download),
        Route("/health", health),
        *mcp_app.routes,
    ]
    return Starlette(routes=routes, lifespan=mcp_app.router.lifespan_context)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, proxy_headers=True, forwarded_allow_ips="*")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<meta name="description" content="Find the labs, people and studies behind a research topic, on a map, from public sources.">
<style>
:root { --ink:#1d2b27; --soft:#4f5a56; --green:#006956; --deep:#00473a; --mint:#d8f8f2; --tint:#f1f8f5; --line:#dfe8e4; }
* { box-sizing:border-box; }
body { margin:0; font:17px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color:var(--ink); background:#fff; }
main { max-width:860px; margin:0 auto; padding:36px 20px 56px; }
h1 { font-size:34px; line-height:1.15; margin:0 0 10px; letter-spacing:-.01em; }
h1 span { color:var(--green); }
.lead { color:var(--soft); font-size:19px; margin:0 0 26px; }
form { display:grid; gap:14px; padding:22px; border:1px solid var(--line); border-radius:14px; background:var(--tint); }
label { display:grid; gap:6px; font-weight:600; font-size:15px; }
input[type=text], input[type=number] { font:inherit; padding:11px 13px; border:1px solid #b9cbc4; border-radius:9px; background:#fff; }
.row { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
fieldset { border:0; padding:0; margin:0; display:flex; gap:18px; font-size:15px; }
fieldset legend { font-weight:600; margin-bottom:6px; }
button { font:inherit; font-weight:600; padding:12px 18px; border:0; border-radius:10px; background:var(--green); color:#fff; cursor:pointer; }
button:hover { background:var(--deep); }
.note { color:var(--soft); font-size:15px; }
.examples a { margin-right:12px; }
h2 { font-size:22px; margin:34px 0 8px; }
code { font:14.5px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:var(--tint); padding:2px 6px; border-radius:6px; word-break:break-all; }
.err { padding:12px 14px; border-radius:10px; background:#fdeeee; color:#7a1f1f; margin:0 0 16px; }
a { color:var(--green); }
footer { color:var(--soft); font-size:14px; margin-top:40px; border-top:1px solid var(--line); padding-top:16px; }
.wait { display:none; color:var(--soft); }
form.busy .wait { display:block; }
@media (max-width:600px) { h1 { font-size:28px; } .row { grid-template-columns:1fr; } }
</style>
</head>
<body>
<main>
{{BODY}}
<footer>Actogram LabScout {{VERSION}}. Open source under the MIT licence, part of
  <a href="https://actogram.org">Actogram Open Science</a>. Data from PubMed, Europe PMC, ROR, NIH RePORTER, UKRI
  Gateway to Research and ClinicalTrials.gov, shown as published, without e-mail addresses.
  <a href="https://actogram.org/privacy">Privacy</a>.</footer>
</main>
<script>
document.querySelectorAll('form').forEach(function (f) { f.addEventListener('submit', function () { f.classList.add('busy'); }); });
</script>
</body>
</html>
"""

FORM = """<h1>Who works on your topic, <span>and where?</span></h1>
<p class="lead">LabScout reads PubMed and Europe PMC, finds the labs behind the papers, places them on a map and says why
  each one came up: papers led, years, kinds of data and species.</p>
<form action="search" method="get">
  <label>Topic<input type="text" name="topic" required maxlength="300"
    placeholder='for example: actigraphy sleep regularity older adults'></label>
  <div class="row">
    <label>From year<input type="number" name="from" min="1900" max="2100" placeholder="2020"></label>
    <label>To year<input type="number" name="to" min="1900" max="2100" placeholder="2026"></label>
  </div>
  <fieldset><legend>Sources</legend>
    <label><span><input type="checkbox" name="source" value="pubmed" checked> PubMed</span></label>
    <label><span><input type="checkbox" name="source" value="europepmc" checked> Europe PMC</span></label>
  </fieldset>
  <button type="submit">Find labs</button>
  <p class="wait">Searching. This usually takes 20 to 60 seconds.</p>
  <p class="note">Up to {{MAX}} papers per source, newest first. PubMed search syntax works, such as
    <code>actigraphy AND "sleep regularity"</code>.</p>
</form>
<p class="note examples">Try: <a href="search?topic=actigraphy+sleep+regularity&amp;from=2020">actigraphy sleep regularity</a>
  <a href="search?topic=circadian+rhythm+shift+work&amp;from=2022">circadian rhythm shift work</a></p>

<h2>Use it from your AI assistant</h2>
<p>LabScout is also an MCP server with tools for labs, papers, researcher profiles, grants, trials and patents. Add this
  address as a custom connector in an assistant that supports MCP:</p>
<p><code>{{MCP}}</code></p>

<h2>Run it yourself</h2>
<p>The code is on <a href="{{REPO}}">GitHub</a>. It installs with <code>pip install "labscout @ git+{{REPO}}"</code> and
  then runs as <code>labscout labs "your topic" --html labs.html</code>.</p>
"""

FORM_ERROR = '<p class="err">{msg}</p><p><a href="./">Back to the search</a></p>'

WAIT = '<h1>Searching for <span>{topic}</span></h1><p class="lead">LabScout is reading the sources and matching the organisations. {waited} seconds so far; a new topic usually takes 30 to 90 seconds, a repeated one is instant. This page refreshes by itself.</p><p><a href="./">Back to the search</a></p>'
