# ADR-0056: Configure AI providers per workspace

Status: accepted, implementation planned in the
[Admin page plan](../features/admin-page-20261030/plan.md).

Store the fallback chain as one ordered `ai.providers` list in `settings.yaml`.
Each entry names a provider and optionally specifies `enabled`, `model` and
`effort`. List order is execution order. Omitted providers are off, enabled
defaults to true, and at least one entry must be enabled. Reject duplicate or
unknown names and unknown keys at load, naming the bad configuration path.

With no AI block, preserve Codex, Claude and Grok in that order using account
defaults. An omitted model or effort passes no corresponding flag. Explicit
choices apply to every task for that provider. Capture the chain when a run
starts so a settings edit cannot change an active fallback or repair sequence.

A single list keeps order and configuration together. A separate order list and
provider map could disagree after a hand edit. The UI shows omitted providers
as disabled rows, and enables them through the same validated document update.

Attempt model discovery on server startup, cache it for 30 minutes and support
explicit Refresh. Codex and Grok discovery use their installed CLIs; Claude
uses a curated pinned-id list. Discovery is advisory. A saved model or effort
that disappears remains stored, visible with a warning and passed on the next
run. A CLI rejection of that choice permits fallback rather than rewriting the
seller's preference. Discovery failure retains saved values and Account default.

This supersedes the fixed provider order and "use the account's configured
model" restriction in the AI SEO implementation plan. Account default remains
an explicit option. It does not change ADR-0003's proposal/acceptance boundary,
read-only provider tools, cancellation or noninteractive execution. There are
no per-task model overrides, service-tier controls or credential editors.

First recorded 2026-10-30 during Admin page planning.
