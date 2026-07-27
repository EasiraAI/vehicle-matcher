"""Local demo UI for manual testing: type a description, see the match, the
confidence, and the candidate score table. Standard library only — this is a
development harness, not a deployment shape (see README operating notes).

Usage: python scripts/demo_server.py   ->  http://localhost:8765
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vehicle_matcher.config import get_settings  # noqa: E402
from vehicle_matcher.llm_extractor import LLMExtractor  # noqa: E402
from vehicle_matcher.matcher import Matcher  # noqa: E402

PORT = 8765

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vehicle Matcher — demo</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.5 system-ui, sans-serif; max-width: 860px; margin: 2.5rem auto; padding: 0 1rem; }
  h1 { font-size: 1.3rem; }
  form { display: flex; gap: .5rem; margin: 1rem 0; }
  input[type=text] { flex: 1; padding: .55rem .7rem; font-size: 1rem; border: 1px solid #8885; border-radius: 6px; }
  button { padding: .55rem 1.1rem; font-size: 1rem; border: 0; border-radius: 6px; background: #2563eb; color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; }
  .examples button { background: none; color: #2563eb; padding: .15rem .4rem; font-size: .85rem; border: 1px solid #2563eb44; margin: .15rem; }
  #verdict { font-size: 1.05rem; margin: 1rem 0 .5rem; }
  #verdict b { font-size: 1.15rem; }
  .conf { display: inline-block; min-width: 2.2rem; text-align: center; border-radius: 5px; padding: .1rem .4rem; color: #fff; font-weight: 600; }
  table { border-collapse: collapse; width: 100%; font-size: .85rem; }
  th, td { text-align: left; padding: .3rem .55rem; border-bottom: 1px solid #8883; }
  th { font-weight: 600; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .muted { color: #888; font-size: .85rem; }
  pre { background: #8881; padding: .6rem; border-radius: 6px; overflow-x: auto; font-size: .8rem; }
</style>
</head>
<body>
<h1>Vehicle Matcher — manual test console</h1>
<p class="muted">Type any marketplace-style car description. The response shows the matched
vehicle, the 0–10 confidence, which tier answered (rules or LLM), and the scored candidates.</p>
<form id="f">
  <input type="text" id="q" placeholder="e.g. Amrok h/line 4x4 quick sale" autofocus>
  <button id="go">Match</button>
</form>
<div class="examples" id="examples"></div>
<div id="verdict"></div>
<div id="table"></div>
<details><summary class="muted">extraction record</summary><pre id="extract"></pre></details>
<script>
const EXAMPLES = [
  "Volkswagen Golf 110TSI Comfortline Petrol Automatic Front Wheel Drive",
  "VW Amarok Ultimate", "Amrok h/line 4x4", "Golf GTI", "Golf cart",
  "Ford Ranger XLT Dual Cab", "Toyota Corolla Ascent Sport Auto",
  "Selling my tiguan r-line in exchange for a toyota camry hybrid",
  "Toyota Kluger Sports Hybrid (It's actually a Toyota 86 GT but the website didn't let me select that, sorry)",
];
const ex = document.getElementById("examples");
for (const e of EXAMPLES) {
  const b = document.createElement("button");
  b.textContent = e.length > 48 ? e.slice(0, 45) + "…" : e;
  b.title = e;
  b.onclick = () => { document.getElementById("q").value = e; run(); };
  ex.appendChild(b);
}
document.getElementById("f").onsubmit = (ev) => { ev.preventDefault(); run(); };
async function run() {
  const q = document.getElementById("q").value.trim();
  if (!q) return;
  const go = document.getElementById("go");
  go.disabled = true;
  try {
    const r = await fetch("/api/match", { method: "POST", body: q });
    const d = await r.json();
    const color = d.confidence >= 8 ? "#16a34a" : d.confidence >= 5 ? "#d97706" : "#dc2626";
    const head = d.vehicle_id
      ? `<b>${d.vehicle.make} ${d.vehicle.model} ${d.vehicle.badge}</b>
         <span class="muted">(${d.vehicle.transmission_type}, ${d.vehicle.fuel_type}, ${d.vehicle.drive_type})</span>
         — ID <code>${d.vehicle_id}</code>`
      : `<b>No match (null)</b> — the vehicle is not in the catalogue`;
    document.getElementById("verdict").innerHTML =
      `${head} &nbsp; confidence <span class="conf" style="background:${color}">${d.confidence}</span>
       <span class="muted">tier: ${d.tier}, ${d.candidate_count} candidates</span>`;
    document.getElementById("table").innerHTML = d.scored.length ? `
      <table><tr><th>candidate</th><th>spec</th><th class="num">score</th>
      <th class="num">conflicts</th><th class="num">listings</th></tr>` +
      d.scored.map(s => `<tr><td>${s.make} ${s.model} <b>${s.badge}</b></td>
        <td class="muted">${s.transmission_type}, ${s.fuel_type}, ${s.drive_type}</td>
        <td class="num">${s.score.toFixed(2)}</td><td class="num">${s.conflicts}</td>
        <td class="num">${s.listing_count}</td></tr>`).join("") + "</table>" : "";
    document.getElementById("extract").textContent = JSON.stringify(d.extracted, null, 2);
  } finally { go.disabled = false; }
}
</script>
</body>
</html>
"""


def build_matcher() -> Matcher:
    settings = get_settings()
    conn = psycopg.connect(settings.dsn)
    fallback = None
    if settings.llm_enabled:
        fallback = LLMExtractor(settings, cache_path=Path(".cache/llm_extractions.json"))
    return Matcher(conn, settings=settings, fallback_extractor=fallback)


class Handler(BaseHTTPRequestHandler):
    matcher: Matcher
    # One shared connection behind a threaded server: serialize matching.
    lock = threading.Lock()

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.path != "/":
            self.send_error(404)
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        if self.path != "/api/match":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        text = self.rfile.read(length).decode("utf-8", errors="replace")
        with self.lock:
            result = self.matcher.match(text)
        top = result.debug.scored[0].candidate if result.debug.scored else None
        payload = {
            "vehicle_id": result.vehicle_id,
            "confidence": result.confidence,
            "matcher_version": result.matcher_version,
            "tier": result.debug.tier,
            "candidate_count": result.debug.candidate_count,
            "vehicle": top.model_dump() if (result.vehicle_id and top) else None,
            "scored": [
                {**s.candidate.model_dump(), "score": s.score, "conflicts": s.conflicts}
                for s in result.debug.scored
            ],
            "extracted": result.debug.extracted.model_dump(),
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # keep the console quiet


def main() -> None:
    Handler.matcher = build_matcher()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"vehicle-matcher demo: http://localhost:{PORT}  (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
