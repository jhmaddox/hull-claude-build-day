# Build session log

**[`session-log.md`](session-log.md)** is the Claude Code session that built and
operated **Hull** end-to-end during Claude Build Day — from an empty folder to a
live, multi-tenant control plane on EC2, including the multi-agent build
workflows, the autonomous incident→fix loop, and the demo polish.

Generated with Claude Code's `/export`. Scanned for secrets — none present (the
session sourced credentials from gitignored env files and never echoed them); the
`demo / demo12345` login is an intentionally public demo credential, also
documented in [`../SUBMISSION.md`](../SUBMISSION.md).
