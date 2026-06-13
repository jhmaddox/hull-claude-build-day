# sample-app backlog — Sprint 3: a non-Django sample that imports cleanly

- [ ] SAMP-1: Node/Express sample "NodeShop" — create sample_apps/nodeshop/: a
  small real-looking Express web app (home + a couple routes + light styling),
  package.json with a "start" script binding process.env.PORT (default for $PORT),
  and — so it imports under the simplified rule — BOTH a `Procfile`
  (`web: node server.js`) AND a `docker-compose.yml` (web service on the app port;
  add redis only if used). Honor a base-path/HELM_SCRIPT_NAME-style env so it
  works behind Hull's proxy. README with the run command. Initialize an inner git
  repo on `main` with one commit. (acceptance: from a clean clone,
  `npm install && npm start` serves HTTP 200 on $PORT; Procfile + compose present;
  inner git repo on main.)
- [ ] SAMP-2: Node 20 compatible — ensure it builds on node:20 (for the compose
  path) and runs as a plain process (node installed) for the fallback; minimal
  pinned deps. (acceptance: documented; `docker build` succeeds if attempted.)
