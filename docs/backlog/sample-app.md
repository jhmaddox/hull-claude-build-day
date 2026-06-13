# sample-app backlog — Sprint 3: a non-Django sample to prove "import any repo"

- [ ] SAMP-1: Node/Express sample "NodeShop" — create sample_apps/nodeshop/: a
  small but real-looking Express web app (a home page + a couple routes + a bit
  of styling), a package.json with a "start" script that binds 0.0.0.0:$PORT (or
  process.env.PORT), and NO Dockerfile/compose (so Hull's configure agent must
  generate one — this is the import-loop test case). Honor a HELM_SCRIPT_NAME /
  base-path env like PocketShop does so it works behind Hull's proxy. Add a
  README documenting the run command. Initialize an inner git repo on branch
  `main` with one commit so Hull can clone it. (acceptance: from a clean clone,
  `npm install && npm start` serves HTTP 200 on $PORT; no Dockerfile present;
  inner git repo on main.)
- [ ] SAMP-2: Keep it deployable both ways — ensure the app runs under Node 20
  (so an agent-generated Dockerfile using node:20 builds) AND as a plain process
  (node installed) for the fallback path. (acceptance: documented; minimal deps.)
