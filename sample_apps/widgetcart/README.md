# WidgetCart — Hull's non-Django generality proof

A tiny **Node** sample app that Hull imports, deploys to staging + prod, and
serves live — proving the import → (verify) → deploy pipeline is not
Django-specific.

It ships everything Hull's runtime detection looks for:

- a **`Procfile`** with a `web:` line (`web: node server.js`),
- a **`docker-compose.yml`** declaring a single `web` service that binds `$PORT`,
- a **`Dockerfile`** for the compose build.

It uses only Node's built-in `http` module (**zero npm dependencies**), so it
deploys live with **no install/build step** — both via Hull's Docker Compose
runtime (when Docker is present) and via the process-runtime fallback
(`node server.js`, reading `$PORT` from the environment) when it is not.

## Run it standalone

```bash
PORT=8031 node server.js
# -> http://localhost:8031/   (and /healthz returns {"status":"ok"})
```

## How Hull imports it

`detect_runtime` finds `docker-compose.yml` first and classifies the repo as
`framework="compose"`, parsing the `web` service + published port. On a
Docker-enabled box Hull deploys the compose stack; otherwise it falls back to
the process runtime using the Procfile `web:` command. Either way the live
deployment returns **HTTP 200**.

See `import_widgetcart.py` (next to this README) for a scripted import that
asserts a live 200.
