<!--
SPDX-FileCopyrightText: 2026 Curtis Galloway
SPDX-License-Identifier: Apache-2.0
-->

# Process log

Where the agent's process cost time on this project. Input for improving the agent's
instructions and skills; project findings go in the backlog instead.

## 2026-09-27T17:46-07:00 — instruction gap: project-plan skill not available in the cloud session
Chapter: [design](notebook/design.md)
What happened: the `agent-workflow` plugin (with `project-plan` and `lab-notebook`) is
installed locally only. The cloud session's skill list lacked it, and the agent began
writing the plan from repo conventions until the user stopped it. The agent then
searched claude.ai skills/plugins and `agent-config` before finding it in
`public-skills`.
Cost: about 4 turns and one user correction.
Prevention: when a request names a process ("resume the project-plan process") that
matches no loaded skill, stop and ask where it lives before proceeding. Also have
the repo name the skill's source, e.g. a line in project instructions: "process skills:
curtisgalloway/public-skills plugins/agent-workflow".
Fix belongs in: project instructions (this repo has no CLAUDE.md/AGENTS.md), or the
cloud environment's setup script installing the plugin.
Status: open

## 2026-09-27T17:59-07:00 — failed command: CIPD tag loop assumed every package had a `version:` tag
Chapter: [I1](notebook/I1.md)
What happened: a loop resolving `version:33.20260927.4.1` for two CIPD packages piped
the reply into `json.load`. `fuchsia-bazel-rules` answered 404 `no such tag` (plain
text), and the first `DescribeInstance` omitted `"describeTags":true`, so no tags
printed. Both showed only as a Python traceback.
Cost: one retried step (about 2 minutes).
Prevention: print HTTP status and raw body (`curl -w '%{http_code}'`) on the first
call to an unfamiliar API before parsing; CIPD `DescribeInstance` needs
`describeTags`/`describeRefs` to return them.
Fix belongs in: project instructions (a CIPD request recipe in the brief's App. B)
Status: open

## 2026-09-27T17:59-07:00 — surprise: foreground `sleep` blocked by the harness
Chapter: [I1](notebook/I1.md)
What happened: `sleep 45; cat <output>` to wait for a background stream was refused
("Blocked: sleep 45 followed by …"); an `until … do sleep 3; done` loop worked.
Cost: one turn.
Prevention: wait on background work with an `until <condition>` loop from the start.
Fix belongs in: tool (harness behavior; no project change)
Status: open

## 2026-09-27T17:59-07:00 — instruction gap: reviewer subagent requested but no Agent tool available
Chapter: [I1](notebook/I1.md)
What happened: the plan's review method and the session's task both name a reviewer
subagent via the `Agent` tool, but this implementer session (itself a subagent) had
no `Agent` tool. Fell back to explicit self-review with the per-criterion checklist,
as the conventions block allows.
Cost: no independent review for I1.
Prevention: when an orchestrator delegates a unit to a subagent, it should either run
the reviewer itself after hand-back or say up front that the fallback applies.
Fix belongs in: skill `orchestrate-milestones` / `project-plan` (review method for
nested sessions)
Status: open
