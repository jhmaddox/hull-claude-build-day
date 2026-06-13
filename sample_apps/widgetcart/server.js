// WidgetCart — a tiny Node sample app.
//
// Hull's non-Django generality proof: a repo that ships a Procfile (web: ...)
// and a docker-compose.yml, binds $PORT, and serves real HTTP. It uses only
// Node's built-in `http` module (zero npm dependencies) so it deploys LIVE with
// no install step — both via the process runtime and via Docker Compose.
//
//   PORT=8031 node server.js   ->   http://localhost:8031/

"use strict";

const http = require("http");

// Hull binds the allocated port via $PORT; default to 8000 for local runs.
const PORT = parseInt(process.env.PORT || "8000", 10);
const HOST = "0.0.0.0";

// A tiny seeded catalog so the live page has real content.
const WIDGETS = [
  { name: "Bolt", emoji: "🔩", price: 1.5 },
  { name: "Gear", emoji: "⚙️", price: 3.25 },
  { name: "Spring", emoji: "🌀", price: 2.0 },
  { name: "Magnet", emoji: "🧲", price: 4.75 },
];

function page() {
  const rows = WIDGETS.map(
    (w) =>
      `<li><span class="e">${w.emoji}</span> <strong>${w.name}</strong> ` +
      `<span class="p">$${w.price.toFixed(2)}</span></li>`
  ).join("");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>WidgetCart</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0b0d12;color:#e6e8ee;margin:0;padding:48px;}
  .card{max-width:640px;margin:0 auto;background:#12151c;border:1px solid #232838;border-radius:14px;padding:32px;}
  h1{margin:0 0 6px;} .muted{color:#8b93a7;}
  ul{list-style:none;padding:0;margin:24px 0 0;}
  li{display:flex;gap:12px;align-items:center;padding:12px 0;border-top:1px solid #232838;}
  .e{font-size:22px;} .p{margin-left:auto;color:#34d399;font-variant-numeric:tabular-nums;}
</style></head>
<body><div class="card">
  <h1>🛒 WidgetCart</h1>
  <div class="muted">A tiny Node sample app, deployed live by Hull.</div>
  <ul>${rows}</ul>
</div></body></html>`;
}

// Access log in a format Hull's log ingestion parses (records req/error/latency
// metrics + powers monitors): `"GET /path HTTP/1.1" 200 123`.
function accessLog(req, status, bytes) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] "${req.method} ${req.url} HTTP/1.1" ${status} ${bytes}`);
}

const server = http.createServer((req, res) => {
  const path = (req.url || "/").split("?")[0];

  if (path === "/healthz") {
    const body = JSON.stringify({ status: "ok" });
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(body);
    accessLog(req, 200, Buffer.byteLength(body));
    return;
  }

  // Demo bug: /boom returns HTTP 500 (drives error-rate -> Hull incident).
  if (path === "/boom" || path === "/checkout") {
    const msg = "checkout failed: inventory service returned a malformed price";
    console.error(`ERROR ${msg} (path=${path})`);
    const body = "<h1>500 — Internal Server Error</h1>";
    res.writeHead(500, { "Content-Type": "text/html; charset=utf-8" });
    res.end(body);
    accessLog(req, 500, Buffer.byteLength(body));
    return;
  }

  const body = page();
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(body);
  accessLog(req, 200, Buffer.byteLength(body));
});

server.listen(PORT, HOST, () => {
  console.log(`WidgetCart listening on http://${HOST}:${PORT}`);
  console.log("INFO catalog loaded: " + WIDGETS.length + " widgets");
  // Ambient heartbeat so the live log viewer always has fresh lines to show.
  setInterval(() => console.log(`INFO heartbeat ok · ${WIDGETS.length} widgets in catalog`), 15000);
});
