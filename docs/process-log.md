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

## 2026-09-27T18:06-07:00 — instruction gap: notebook and process-log entries written in batches, not at the moment
Chapter: [I1](notebook/I1.md)
What happened: several I1 notebook entries were written after the events, in batches:
two at 17:52, four at 17:54 and three at 17:58. All three process-log entries were
written together at 17:59, some minutes after the friction they describe. Their
timestamps are the times of writing, not the times of the events, so the index's
staleness signal looks fresher than the work was. The independent reviewer flagged
the clustering.
Cost: a review finding; less trustworthy ordering in the chapter.
Prevention: lab-notebook says to write each entry "at the moment of writing" when it
happens. Append the entry in the same tool call as the step that triggers it, rather
than after several steps.
Fix belongs in: skill `lab-notebook` (a concrete "same call" rule) / agent habit
Status: open

## 2026-09-27T18:16-07:00 — surprise: `reuse lint` reports gitignored files in untracked directories
Chapter: [M1](notebook/M1.md)
What happened: before the first commit, `uv run reuse lint` failed on
`scripts/__pycache__/*.pyc` and `tests/__pycache__/*.pyc` although `.gitignore`
lists `__pycache__/`. reuse's git query (`ls-files --ignored --others --directory
--no-empty-directory`) does not list ignored directories nested in untracked ones.
Cost: three tool calls reading reuse's source to rule out a real header gap.
Prevention: when a license linter reports generated files, first check whether the
files around them are tracked; lint a copy with everything added to a fresh index.
Fix belongs in: tool (reuse/git behavior); nothing to change in the project
Status: open

## 2026-09-27T18:18-07:00 — failed command: `/usr/bin/time` is not installed
Chapter: [M1](notebook/M1.md)
What happened: the two-live-runs loop used `/usr/bin/time -f`; the container has no
`time` binary (exit 127), so both iterations failed before resolving anything.
Cost: one retried step (seconds; no network work lost).
Prevention: time commands with `date +%s` arithmetic or the shell's `time` keyword.
Fix belongs in: agent habit (no project change)
Status: open

## 2026-09-27T19:01-07:00 — failed command: multi-line sed replacement silently did nothing
Chapter: [M2](notebook/M2.md)
What happened: a `sed -i 's|…\n|X|'` meant to reword a two-line doc comment matched
nothing (sed works line by line) and exited 0; noticed only because the next step used a
Python replacement with an exact-count assert.
Cost: one redone edit.
Prevention: for multi-line or exact replacements use the Edit tool or a script that
asserts the match count, as this project's other edits do.
Fix belongs in: agent habit (the harness guidance already says so)
Status: open

## 2026-09-27T19:23-07:00 — instruction gap: M2 notebook entries at 19:01 were written in one batch after the events
Chapter: [M2](notebook/M2.md)
What happened: the four M2 entries stamped 19:01 were written together in one call. They
cover the API-level fix, the rules_cc bump, the Bazel 8.1.0 dead end, the 8.5.1 decision
and the successful links. That was after three builds and the 8.5.1 download
(roughly 18:55–19:01). This process-log entry about sed, also stamped 19:01, was written
right after them. So the stamps are the times of writing, not the times of the events. The same
pattern was logged for I1. The independent reviewer noticed the shared timestamp.
Cost: a review nit; less trustworthy ordering in the chapter.
Prevention: append each entry in the same tool call as the step that triggers it
(for example, chain the notebook append onto the build command whose outcome it records).
Fix belongs in: skill `lab-notebook` (the "same call" rule proposed for I1) / agent habit
Status: open

## 2026-09-27T19:48-07:00 — failed command: a trial extraction ran into the 10-minute tool timeout
Chapter: [M2a](notebook/M2a.md)
What happened: the first trial of `idk_extract.py` (Python `tarfile` in streaming mode
`r|gz`) on the 3 GB IDK was moved to the background at the 600 s tool timeout, having
written 1 MB; a probe then hit a 60 s `timeout` too. `r:gz` does the same job in 48 s.
Cost: about 12 minutes of wall time and two tool calls.
Prevention: before running a new extraction over a multi-GB archive, time it on a
bounded slice (e.g. 20 s of iteration) and extrapolate.
Fix belongs in: agent habit (no project change)
Status: open

## 2026-09-27T20:34-07:00 — failed command: `pkill -f` killed its own shell, dropping a chained notebook append
Chapter: [M3](notebook/M3.md)
What happened: `pkill -f blockproxy.py` in the same bash command as a notebook
append matched that bash process too (its command line contains the pattern), so the
shell died with exit 144 before the append ran.
Cost: one redone notebook entry (written a few minutes after the event, noted in it).
Prevention: stop background helpers by PID (`$!` saved to a file), or `pkill -f` with a
pattern the calling command line cannot contain (e.g. `[b]lockproxy`).
Fix belongs in: agent habit (no project change)
Status: open

## 2026-09-27T20:46-07:00 — failed command: step-log names built from the command line
Chapter: [M3](notebook/M3.md)
What happened: a helper named each step's log `$R/$1-$2.log`; for `scripts/emu setup` that
is `$R/scripts/emu-setup.log`, in a directory that did not exist, so the redirect failed,
the step "exited 1 in 0 s" and the sequence stopped (after the clean slate was made).
Cost: one rerun of a 4-minute sequence (the clean slate was still intact).
Prevention: number step logs, or dry-run a sequence helper on a trivial command first.
Fix belongs in: agent habit (no project change)
Status: open

## 2026-09-27T21:07-07:00 — failed command: `pgrep -f` matched its own shell again
Chapter: [M3](notebook/M3.md)
What happened: `kill -9 $(pgrep -f 'bin/qemu-system-x86_64')` in a chained command also
matched the bash running it, so the shell died (exit 1) after killing QEMU; the rest of
the chain (list, stop) did not run. Same cause as the `pkill -f` entry earlier today,
whose prevention I did not apply.
Cost: one rerun of the remaining steps.
Prevention: the `[q]emu` bracket trick or a saved PID, every time; a helper script for
"kill the emulator's QEMU" would make it habitual.
Fix belongs in: agent habit (no project change)
Status: open

## 2026-09-27T21:17-07:00 — surprise: a checkpoint commit deleted eight plan entries
Chapter: [M4](notebook/M4.md)
What happened: the M3 checkpoint `9c15cd9` removed the detailed plan entries for
M4–M10 and I2 (364 lines) while moving M3's entry to its evidence; nothing in the M3
review caught it. The M4 session found its own milestone entry missing and had to
recover it from `c860458`.
Cost: a few minutes of history search; without the recovery a later session would have
executed M4–M10 from the one-line status rows only.
Prevention: at checkpoint, diff the plan's `## ` heading list before and after the
edit (`git diff -- docs/implementation-plan.md | grep '^[-+]## '`); only the
completed milestone's heading may change.
Fix belongs in: project-plan skill (close-out step 4) or orchestrate-milestones review
Status: open

## 2026-09-27T21:39-07:00 — instruction gap: orchestrator landed a checkpoint that dropped plan entries
Chapter: [M3](notebook/M3.md)
What happened: M3's checkpoint commit removed 364 lines of the plan (entries M4–M10
and I2). The orchestrator verified branch, tests, evidence and plan status before
landing, but not that unrelated plan sections survived, so main lacked those entries
from PR #6 until M4 restored them (found by M4's implementer).
Cost: one milestone's worth of main without the M4–M10/I2 definitions; M4 had to
reconstruct its own entry from history.
Prevention: before each landing the orchestrator compares `## ` headings of the plan
and design against the base, and line counts of every doc file, and sends any
unexplained drop back to the implementer (applied from M4's landing on).
Fix belongs in: orchestrate-milestones skill (step 4 "Finished: verify before landing").
Status: open

## 2026-09-27T22:38-07:00 — failed command: `git grep` in a blobless clone
Chapter: [M6](notebook/M6.md)
What happened: to find a build argument's default I ran `git grep … <rev> -- '*.gni'` in
a `--filter=blob:none` clone. git grep needs every matching blob, so the partial clone
started fetching them one by one; the command hit the 2-minute timeout and was stopped.
Cost: about 2 minutes, one stopped background task (no harm: the clone stayed 5 MB).
Prevention: in a blobless clone, find paths with `ls-tree` and read single blobs with
`cat-file`; never `git grep`/`git log -p` there.
Fix belongs in: agent habit; could be a note in the M5/M6 regen.py docstring ("GitSource
is blobless")
Status: open

## 2026-09-27T22:42-07:00 — failed command: `git ls-tree -l` in a blobless clone
Chapter: [M6](notebook/M6.md)
What happened: four minutes after the `git grep` entry, `ls-tree -r -l` (sizes) in the
same blobless clone again started fetching every blob and timed out; stopped.
Cost: about 2 minutes. The prevention in the previous entry was written but not applied
to "any git command that needs blob contents or sizes".
Prevention: treat blob sizes like contents: `ls-tree` without `-l`, count files instead.
Fix belongs in: agent habit
Status: open

## 2026-09-27T23:13-07:00 — instruction gap: four notebook entries written as one batch
Chapter: [M6](notebook/M6.md)
What happened: the entries stamped 2026-09-27T22:37-07:00 (surprise, decision, attempt,
surprise) were written together after the first closure run, not each when it happened;
they share one timestamp that reflects the writing, not the events (about 22:25–22:36).
The review noticed it. Timestamps were not rewritten.
Cost: the chapter's order is right but its timing is coarse for that stretch.
Prevention: append an entry at each trigger (the decision to write gn_eval.py, the
first run's result) before starting the next step, even when the steps follow quickly.
Fix belongs in: agent habit (lab-notebook skill already says so)
Status: open
