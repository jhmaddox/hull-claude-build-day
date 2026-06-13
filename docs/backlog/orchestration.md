# orchestration backlog — Sprint 3: unified agent observability dashboard

- [ ] ORCH-1: Agent observability dashboard — a live view (e.g. /orchestration/agents)
  listing ALL recent + running AgentRuns across the current org: kind, title,
  status, cost_usd, num_turns, project, and last action; running ones highlighted
  with a live pulse. HTMX-polled (every ~2s) so it updates as the swarm works.
  (acceptance: page returns 200 authenticated, lists multiple agents, auto-refreshes,
  org-scoped; a nav link points to it.)
- [ ] ORCH-2: Swarm summary tiles — stat tiles at the top: running / queued / done
  counts and total cost_usd, live-updating. (acceptance: tiles render with correct
  counts derived from AgentRun.)
