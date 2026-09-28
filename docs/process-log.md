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
