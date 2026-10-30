# ADR-0057: Bound AI attempts and runs

Status: accepted, implementation planned in the
[Admin page plan](../features/admin-page-20261030/plan.md).

Configure two integer minute limits in `settings.yaml`: `ai.step_limit_minutes`
from 1 to 15, default 5, and `ai.run_limit_minutes` from 5 to 60, default 20.
Apply them to every AI entry point, including brief drafting, market queries,
editor AI Mode and batch brief runs. Capture limits and provider configuration
together when a run starts. Edits affect subsequent runs.

A provider attempt and its one output repair share the step deadline. The next
fallback provider gets a fresh step allowance, clipped to the remaining run
budget. The whole-run deadline also covers successive tasks and market research.
Keep monotonic clocks and process-tree termination on cancellation or timeout.
Timeout messages must state the configured limit.

Require `run_limit_minutes >= enabled_provider_count * step_limit_minutes`.
The UI raises the run limit in the same save when a larger step limit or newly
enabled provider requires it. It prevents dragging the run limit below that
floor. Disabling a provider or reducing the step limit does not lower the
seller's run limit. The maximum floor is 45 minutes for the three supported
providers, within the 60-minute maximum.

Reject hand-edited files that violate the relationship, naming the bad key.
Do not repair them on load. The floor reserves time for the configured provider
chain; it does not guarantee that every task, repair and research call can use
its full allowance before the whole run ends.

Separate budgets allow a slow provider without making the whole process
unbounded. This replaces fixed task and run constants. The local prerequisite
change raises a shared task budget to five minutes and the run cap to twenty
minutes; fresh fallback allowances arrive with the configurable-limit PR.

First recorded 2026-10-30 during Admin page planning.
