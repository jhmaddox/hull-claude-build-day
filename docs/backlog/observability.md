# observability backlog — Sprint 3: manual declare-incident

- [ ] OBS-1: Manual "Declare incident" — a button + form on /obs/incidents/
  (fields: project, severity, title, message) that creates an Incident
  (status=firing, org=request.org) through a new
  `observability.services.create_manual_incident(...)` helper which reuses
  `next_incident_number`, emits the pagerduty-style core.Event, and fires the
  on-call hook (oncall loop on_incident_opened) exactly like auto-detected
  incidents — so it shows a timeline and (if auto-remediate is on) can kick the
  loop. Do NOT modify the Incident schema or the ingest_line/open_or_update_incident
  contracts the autonomous loop depends on. (acceptance: declaring an incident
  creates one that appears in /obs/incidents/ and on its detail page with a
  timeline entry; org-scoped; loop contracts unchanged.)
