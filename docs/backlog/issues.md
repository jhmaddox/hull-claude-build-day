# issues backlog — Sprint 3: ticket → workspace → agent

- [ ] ISS-1: "Work this ticket" action — on the ticket detail page, a button that
  creates a worktree + launches an agent (`agents.services.launch_agent(project,
  kind="feature", title=ticket.title, prompt=<ticket title + description>,
  dispatch=True)`), and sets the ticket status to in_progress. Link the AgentRun
  to the ticket. (acceptance: clicking "Work this ticket" creates an AgentRun
  linked to the ticket and flips status to in_progress; org-scoped.)
- [ ] ISS-2: Link the resulting PR back to the ticket — when the ticket's agent
  opens a PR, associate it with the ticket; ticket detail shows the linked PR +
  its ci_status; when that PR merges, move the ticket to done. (acceptance:
  ticket detail renders the linked PR and reflects merge → done.)
