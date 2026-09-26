# AI SEO implementation plan

**Status:** proposed implementation plan. This document is based on the approved
[Listing SEO AI Mode interactions](ui-listing-seo-interactions.md) and the draft
`seo_prompt.md`. It is intentionally not an authority over [prd.md](prd.md): PRD
decision 4 and the AI-generation sections must be amended in PR 1 before any
implementation PR is merged.

## Outcome

AI Mode is a manual, local editing aid within a *saved* listing's Details tab.
It asks a locally authenticated coding-agent CLI for one complete SEO proposal,
then lets the seller accept individual title, tag, and description-lead choices.
The proposal itself is temporary browser state. Accepted values follow the
ordinary listing-editor autosave path; the model never writes `listing.yaml`, a
lockfile, `generated.yaml`, or a remote listing.

This is a single-user local feature. It runs the subscription-authenticated
Codex CLI first and Claude Code second; it does not require an OpenAI or
Anthropic API account. Codex supports ChatGPT subscription sign-in for local CLI
work and exposes `codex exec` for repeatable terminal workflows. API-key use is
the separate usage-priced route. See the official [Codex authentication
documentation](https://learn.chatgpt.com/docs/auth) and [Codex CLI
documentation](https://learn.chatgpt.com/docs/codex/cli). Claude Code's
headless mode similarly supports `claude -p` for local automation; see
[Claude Code headless mode](https://code.claude.com/docs/en/headless).

This design is not a hosted or multi-user model service. Such a service needs
provider APIs, account-specific rate limiting, durable job ownership, and a
different credentials boundary.

## Settled product and technical decisions

| Topic | Decision |
|---|---|
| Entry point | AI Mode stays visible in Listing Details and is disabled until the listing is saved with a selected design, a non-empty brief, `prompts/seo.md`, and at least one ready provider. The brief is editable in Listing Details. |
| Drafting on design attach | Attaching a design to a listing whose brief is empty drafts a brief from the artwork, writes it through the ordinary autosave path, and then starts one SEO request (PRD 68). The draft is requested from the design-strip's own pick handler, so it goes out immediately and needs no saved listing — `POST /api/ai/design-brief` takes the design path alone -- no listing name and no garment profile, since the brief prompt forbids describing the garment anyway. Only that transition starts it, only into an empty brief, and never again automatically after a failure. The chain belongs to the open editor: same request-scoped endpoints, same 60-second deadline per request, same abort-on-leave rule — there is still no server-side job, queue or proposal cache. |
| Brief prompt | `prompts/brief.md`, seeded by `setup` exactly as `prompts/seo.md` is, wrapped in the same delimited JSON context and response schema. A valid draft is one non-empty plain-text brief within a fixed length ceiling; there is no repair-specific handling beyond the one the shared orchestrator already gives every task. |
| Providers | The chain tries Codex, then Claude, then Grok. Grok is the local `grok` CLI (`--prompt-file`, `--json-schema`, read-only `--tools`). `--json-schema` is what makes the answer JSON: the adapter reads `structuredOutput`, the schema-valid object, not the model's `text`. A recognised unavailable failure falls through to the next. Each CLI uses its currently configured account model; there is no model picker or provider settings UI. |
| Provider process | Run in the real workspace with full coding-agent tools constrained to read-only mode, automatic non-interactive approval, no durable provider session, and access to all readable workspace files. This explicitly includes readable workspace secrets and caches. |
| Timeout and retries | The entire request, including a repair and provider fallback, has a 60-second deadline. A malformed response gets one repair attempt from the same provider. Only recognised provider-unavailable, authentication-quota, or rate-limit failures fall through to Claude. Other failures show **Try again**. |
| Concurrent requests | One request may run for each listing concurrently. A second request for the same listing is refused while its first request is active. There is no durable queue or job record. |
| Cancellation | The browser aborts a request when its editor is left or its connection closes; the backend terminates that subprocess tree. The loading state also exposes Cancel. No cancelled proposal is retained. |
| Prompt | `prompts/seo.md` is plain seller-editable instruction text. The application appends delimited JSON context and a JSON response schema; it does not support placeholders or executable prompt code. `setup` seeds the default only when the file is absent, never overwriting seller content. |
| Proposal | Exactly three titles, twenty unique ranked tags, three description leads, seven phrase rationales, warnings, and observed OCR text. The first thirteen tags are **Best 13**. OCR is disclosed in the proposal, not saved as design data. |
| Validation | Normalize harmless formatting, then enforce Etsy title/tag limits, tag uniqueness, and the agreed hard affiliation/content checks before the UI sees a proposal. Trademark findings are warnings, not a hard refusal. |
| Proposal persistence | Store unresolved proposals only in browser local storage, scoped to the workspace and listing, for one day. Never store them server-side or in a workspace file. Editor changes to submitted generation inputs make a proposal stale; accepted values remain ordinary seller edits. |
| Description model | `etsy.description` has a required `lead` and may contain exactly one sibling content source: `text` or `ref`. The final description is composed once and consumed everywhere. |
| Common copy | `description.ref` is a portable POSIX workspace reference such as `common-copy/comfort-colors.md`; it may resolve only beneath `common-copy/`. The Markdown file has `title` and `targets` front matter, optional `summary`, and must target `description`. |
| Legacy copy | Remove `<generate>` from the listing schema. Convert it to empty ordinary editable values. Convert a legacy scalar description to `description.text` unchanged with an empty lead; do not guess the opening paragraph. There is no runtime migration or compatibility reader. |
| Conversion scope | Convert tracked repository listing fixtures and only the explicitly identified desktop `try-workspace`. Enumerate exact target files before writing; never discover-and-rewrite arbitrary workspaces. |

## Target listing representation

```yaml
etsy:
  title: ""
  tags: []
  description:
    lead: ""
    ref: common-copy/comfort-colors.md
```

Or, for listing-specific text:

```yaml
etsy:
  description:
    lead: A relaxed heavyweight tee for the trail and the coffee stop after it.
    text: |
      Printed to order on a Comfort Colors 1717 shirt.
```

`lead` may be empty while a listing is being edited, but deployment is blocked
until it is non-empty. `text` or `ref` is optional, but never both. The shared
composer preserves a text-only legacy conversion, joins a non-empty lead and
resolved text with exactly one blank line, and supplies the same concrete string
to Printify, Etsy, snapshots, diffs, and validation.

## Runtime design

```text
Listing Details AI Mode
        |
        | POST proposal, request-scoped
        v
SEO API ── readiness ── prompt + provider checks
        |
        v
SEO service ── typed request / deadline / cancellation
        |
        +── Codex CLI adapter ── recognised availability failure ──+
        |                                                       |
        +── Claude CLI adapter <────────────────────────────────+
        |
        v
proposal normalisation + hard validation
        |
        v
browser-local proposal drawers ── seller selection ── normal autosave
```

### Provider adapters

`ai/providers.py` exposes a narrow provider protocol, for example:

```python
class AiProvider(Protocol):
    def readiness(self) -> ProviderReadiness: ...
    def generate(self, task: ProviderTask, deadline: Deadline) -> RawProviderResult: ...
```

A `ProviderTask` is assembled prompt text, a response schema, and the design
image — everything a CLI invocation needs and nothing about *which* AI feature
asked for it. That is what lets brief drafting and SEO generation share one
adapter, one fallback order, one repair rule and one deadline instead of
growing a second copy of each (PRD 68). Assembling the task from a seller's
prompt file is the caller's job, so an adapter no longer reads `prompts/seo.md`
and no longer reports a missing one as *provider* unreadiness — a prompt file
is a property of the request, not of the CLI.

The orchestration service owns retry classification, fallback order, the shared
deadline, and conversion from raw output to `SeoProposal`. An adapter owns only
its CLI invocation, structured-output parsing, process lifetime, and provider
specific error classification. It must not edit a listing or implement SEO
validation.

The Codex adapter uses a non-interactive `codex exec` invocation with its
read-only sandbox, ephemeral/no-session mode, structured output schema, and
the design image. The Claude adapter uses the corresponding `claude -p`, JSON
schema, no-session-persistence, and read-only non-interactive controls supported
by the installed version. Exact arguments are covered by subprocess contract
tests. If a CLI cannot provide the requested read-only restriction, it is not
ready; the feature must not silently launch a writable process.

No durable provider transcript, request history, model result cache, or
diagnostic log is created by this feature. Standard provider CLI authentication
state remains the provider's own responsibility.

### Proposal and stale-state rules

The request snapshots precisely the saved listing inputs: listing brief,
selected design identity/content hash, garment context, and relevant editable
listing values. The server captures the snapshot before generation and returns
it with the proposal; the browser stores both under an opaque workspace-root
identity and listing name. Changes to those editor inputs stale unresolved
choices; prompt-file edits, unrelated workspace edits, and changes in other
listings do not. A stale proposal remains visible but cannot be selected until
regenerated.

Accepting a title or lead replaces that normal editor field. Tag candidates
toggle into and out of the normal tag collection, respecting its thirteen-tag
limit; **Accept best 13** replaces the collection with ranks 1–13. Closing or
rejecting a drawer does not undo prior accepted values.

### Description and common-copy boundaries

`workspace` owns all layout and file access:

- `Workspace.common_copy_dir()` returns `common-copy/`.
- `Workspace.common_copy_file(ref)` verifies the portable reference, rejects
  traversal, and resolves only under `common-copy/`.
- `Workspace.load_common_copy(ref)` parses front matter and returns the Markdown
  text plus metadata.

Configuration owns structure and pure composition. A single shared resolver
loads a configured `ref` through `Workspace`, then calls a pure
`compose_description(lead, text)` helper. No stage, API serializer, or UI
handler may independently concatenate, parse, or path-resolve description text.

## Implementation PR sequence

Each estimate includes implementation, directly related tests, and documentation
in that PR. Generated OpenAPI output is reviewed with its originating PR and
the total remains below 3,000 changed lines.

### PR 1 — `docs: replace generated SEO lifecycle with AI Mode`

**Target: about 1,200 lines.**

1. Amend PRD decision 4, the AI-generation section, workspace tree, examples,
   phase table, and deployment gates to remove `generated.yaml`, `<generate>`,
   and `Generate()`.
2. Amend `docs/implementation-plan.md` to remove the Generate stage and old A9
   review decision, replacing them with the browser-only proposal lifecycle.
3. Update `docs/ui-listing-seo-interactions.md` for saved-listing-only entry,
   visible-disabled behavior, cancellation, provider fallback, the final
   description model, and direct conversion.
4. Keep the repository-root `seo_prompt.md` as the drafting source only; it is
   not a runtime workspace file.

**Validation:** documentation review against the settled decisions above. No
runtime behavior changes land in this PR.

### PR 2 — `feat(description): add lead and common-copy bodies`

**Target: about 2,700 lines.**

1. Replace `EtsyListingConfig.description: str` with a strict `lead` plus
   `text`/`ref` model;
   remove the `<generate>` literal from title, tags, and description types.
2. Add common-copy layout accessors, Markdown front-matter loading, ref
   validation, and the one shared composition path.
3. Route local validation, Printify product desired documents, Publish, Etsy
   listing desired documents, snapshots, lockfile comparisons, and API schemas
   through composed description text.
4. Change Details-tab data contracts and minimal editor controls to preserve the
   structured value while keeping the app buildable between PRs.
5. Make setup create an empty `common-copy/` directory.
6. Convert every tracked repository fixture `listing.yaml`. Before changing the
   desktop workspace, resolve and list the exact `try-workspace` files; if it is
   unavailable, report that target rather than touching another workspace.

**Validation:** config-model, composer, ref traversal, malformed-front-matter,
deployment-gate, stage-diff, API, and frontend serialization tests.

### PR 3 — `feat(ai): define SEO proposal contracts and seed prompts`

**Target: about 2,300 lines.**

1. Create `ai/` request, proposal, rationale, warning, validation, and
   readiness models.
2. Package the default `seo.md`, updated from the draft to require the complete
   proposal contract.
3. Add the setup seed operation: create `prompts/seo.md` if absent; otherwise
   warn and retain the seller's file exactly.
4. Build the delimited JSON context and response schema around the plain prompt.
5. Normalize and hard-validate proposal output before any UI response, including
   exact counts, Etsy limits, uniqueness, affiliation checks, and trademark
   warnings.
6. Define fake providers and contract fixtures; no real CLI call is needed in
   unit or CI tests.

**Validation:** valid and invalid proposal fixtures, one repairable response,
hard validation failures, warning-only trademark cases, and default prompt
provisioning tests.

### PR 4 — `feat(ai): add local Codex and Claude runners`

**Target: about 2,900 lines.**

1. Add Codex and Claude adapter implementations behind `SeoProvider`.
2. Add provider readiness checks for executable, authentication, read-only
   capability, and required prompt. Readiness needs no speculative quota check.
3. Implement the Codex → Claude chain, recognised availability classification,
   one same-provider output repair, and one 60-second request deadline.
4. Launch subprocesses in the real workspace, with the agreed readable scope,
   no session persistence, automatic tool approval inside read-only mode, and
   default configured CLI model.
5. Add process-tree cleanup for timeouts, cancellation, and request disconnects.

**Validation:** exact-argv subprocess tests, readiness tests, fallback matrix,
deadline budget tests, process cleanup tests, and a local manual smoke test with
the logged-in Codex CLI. CI remains fake-provider-only.

**Known limitation:** both adapters' readiness checks (`_check_read_only_capability`
in `ai/codex.py` and `ai/claude.py`) only confirm that the installed CLI's own
`--help` text advertises the read-only/sandbox flags this feature depends on --
not that a live invocation actually honours them. This is the same "no
speculative quota check" tradeoff item 2 above already accepts for
authentication: readiness stays a local, fast, static check rather than one
that spends a real generation call to verify behaviour. A CLI that advertises
a flag in `--help` but silently ignores it at runtime would still be reported
ready.

### PR 5 — `feat(ui-api): expose SEO readiness and proposals`

**Target: about 2,600 lines.**

1. Add a saved-listing readiness endpoint and a request-scoped proposal endpoint.
2. Permit concurrent active requests for different listings; reject a second
   request for the same listing.
3. Detect client disconnects, terminate the matching provider process, and
   return no retained result.
4. Return only validated proposal payloads, input snapshot data, expiry metadata,
   and user-facing errors.
5. Keep this outside `ui/runs`: it creates no run, SQLite record, lockfile,
   workspace output, or server-side proposal cache.
6. Regenerate the typed TypeScript client from OpenAPI.

**Validation:** API tests for saved-only access, hidden readiness, concurrent
listing behavior, timeout/cancellation, fallback errors, and no-write behavior.

### PR 6 — `feat(ui): add structured Description editing`

**Target: about 2,700 lines.**

1. Complete the Details-tab Description UI: lead editor, inline text editor,
   common-copy selector, metadata display, and visible invalid-reference issues.
2. Preserve the exact structured document in ordinary autosave operations.
3. Render the composed description where the existing UI previews copy, without
   duplicating the server-side composition rule.
4. Add frontend tests for content-source switching, missing references, lead-required
   deployment state, and autosave failure behavior.

### PR 7 — `feat(ui): add Listing Details AI Mode`

**Target: about 2,950 lines.**

1. Add the always-visible AI Mode control and accessible loading, Cancel,
   failure, and Try again states.
2. Add title, tag, and lead drawers with the approved independent acceptance
   behavior; expose warnings, rationale, and observed OCR as disclosures.
3. Keep unresolved proposals in browser local storage for one day, scoped to
   workspace/listing. Restore current proposals after refresh and discard expired
   ones.
4. Apply stale state only to unresolved choices whose submitted editor inputs
   changed; regenerate without altering accepted fields.
5. Use the normal editor autosave path for every accepted choice.

**Validation:** Vitest coverage for local-storage expiry, stale state, drawer
focus, tag limit/toggling, Best 13 replacement, error handling, and accessibility
attributes.

### PR 8 — `test: verify AI SEO browser workflow`

**Target: about 2,200 lines.**

1. Add browser tests using fake providers for a saved-listing request through
   independent title, tags, and lead acceptance.
2. Cover unavailable AI Mode, missing prompt, stale proposal, cancellation,
   malformed provider output, fallback, one-day expiration, and common-copy
   description deployment composition.
3. Verify that generation itself changes no listing field, no lockfile, and no
   remote state.
4. Run `./scripts/check.sh`, frontend coverage, and the browser marker suite.
5. Add concise operator documentation for CLI sign-in, prompt customization,
   common-copy files, provider limits, and the deliberate real-workspace read
   scope.

## Acceptance criteria

- A saved listing with a design, brief, prompt, and one ready CLI can request a
  proposal without an API account.
- No request mutates workspace listing data, engine state, or remote services.
- A seller can accept title, tags, and lead independently, and each accepted
  value is saved through the normal editor path.
- A Printify/Etsy plan uses exactly the same composed description the editor
  displays.
- Existing scalar descriptions are directly represented as inline `text`;
  no migration code or legacy compatibility branch remains.
- The feature is unavailable rather than writable when a provider cannot meet
  the requested read-only execution boundary.
- All code and test PRs remain below 3,000 changed lines and pass the existing
  Python, frontend, and browser quality gates.
