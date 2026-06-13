#!/usr/bin/env bash
# Fake `claude` CLI for Helm Slice B testing.
# Emits valid stream-json lines to stdout and makes a real file change in cwd,
# so run_agent's parse + commit + PR pipeline can be tested without spawning a
# real (costly, recursive) Claude agent.
#
# Usage: set HELM_CLAUDE_BIN=/abs/path/to/fake_claude.sh
# It ignores its CLI args (claude -p "<prompt>" --output-format stream-json ...).

set -e

# 1) system/init
printf '%s\n' '{"type":"system","subtype":"init","model":"fake-opus","cwd":"'"$PWD"'"}'

# 2) assistant message with text + a tool_use
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Adding a marker file to prove the agent ran."},{"type":"tool_use","name":"Write","input":{"file_path":"AGENT_WAS_HERE.txt"}}]}}'

# Make a real change in the worktree.
echo "Helm agent was here at $(date -u +%Y-%m-%dT%H:%M:%SZ)" > AGENT_WAS_HERE.txt

# 3) user tool_result
printf '%s\n' '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"File created successfully."}]}}'

# 4) result (final)
printf '%s\n' '{"type":"result","subtype":"success","result":"Created AGENT_WAS_HERE.txt as requested.","num_turns":2,"total_cost_usd":0.0123}'
