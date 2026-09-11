# Architecture

Companion to [prd.md](prd.md) (*what*) and [implementation-plan.md](implementation-plan.md)
(*how*). This document describes the system as it exists today — after Phase 0
and Phase 1. It shows mechanism, not a restatement of the directory listing,
and it is kept in step with the code rather than with the plan.

## The eight modules

```mermaid
graph TD
    subgraph entry["Entry points — what a human drives"]
        CLI["<b>cli</b><br/>Typer commands<br/>+ plan rendering"]
        UI["<b>ui</b><br/>FastAPI + React<br/>calibrator"]
    end

    subgraph orchestration["Orchestration — what decides and executes"]
        ENGINE["<b>engine</b><br/>Stage pipeline, three-way diff,<br/>lockfile, plan / apply"]
        NEWCMD["<b>newcmd</b><br/>the <i>new</i> picker:<br/>catalog → garment profile + listing"]
    end

    subgraph tree["The data tree"]
        WORKSPACE["<b>workspace</b><br/>root discovery, layout,<br/>path safety, config loading"]
    end

    subgraph capabilities["Capabilities — no knowledge of the tree"]
        RENDER["<b>render</b><br/>pure passes,<br/>frozen RenderConfig"]
        CATALOG["<b>catalog</b><br/>Printify reference data<br/>protocol + cache + fake"]
        CONFIG["<b>config</b><br/>pydantic models, Money,<br/>slugification"]
    end

    CLI --> ENGINE
    CLI --> NEWCMD
    CLI --> UI
    CLI --> WORKSPACE
    UI --> RENDER
    UI --> WORKSPACE
    ENGINE --> RENDER
    ENGINE --> CATALOG
    ENGINE --> WORKSPACE
    NEWCMD --> CATALOG
    NEWCMD --> WORKSPACE
    WORKSPACE --> CONFIG
    WORKSPACE --> RENDER
    ENGINE --> CONFIG
    NEWCMD --> CONFIG
    CLI --> CONFIG
```

Dependencies point strictly downward; there are no cycles. `render`, `catalog`
and `config` know nothing about workspaces, listings or each other, which is
what makes them testable in isolation — and what lets `render` be pure.

`workspace` depends on both `config` and `render` for the same reason: it knows
where every file lives, and asks whichever module owns a file's *shape* to
parse it. `shop.yaml`, `listing.yaml` and the pricing plans are `config`'s;
`template.yaml` is `render`'s, because it is render geometry and render
settings from top to bottom. The arrow only ever points that way — `render`
still has no idea a workspace exists.

| Module | Owns | Deliberately does *not* |
|---|---|---|
| `cli` | Typer commands; turning a `Plan` / `RunReport` into terminal text | Compare state, run a batch, or know the directory layout |
| `ui` | The calibrator's HTTP API and its React front end | Contain a second execution path — it calls the same renderer |
| `engine` | Stage protocol, the three-way diff, the lockfile and its hashing, and the shape of a run over N listings | Format output, or talk HTTP directly |
| `newcmd` | Turning a catalog choice into a garment profile + listing stub | Prompt (that is a thin questionary shell over pure logic) |
| `workspace` | Where every file lives, path safety, loading config | Know what a render or a Printify product is |
| `render` | warp → displace → shade → export, and derived maps | Any I/O, globals or clock (A7) |
| `catalog` | Printify blueprint/provider/variant reads, TTL cache, name→id | Anything shop-scoped or authenticated |
| `config` | `shop.yaml` / garment profile / listing models, `Money`, slugs | Know where those files are on disk |

`etsy_listings/connections.py` sits across from the table rather than in it:
it is the one place that knows how to *build* the clients the table's modules
hold — the transports, the Etsy token store, and the `RunContext` a run is
given. Four callers each assembled a signed-in Etsy client themselves (`cli`,
`setup`, `auth`, and the e2e fixtures), which made "which credential is
resolved when" four answers instead of one. It resolves none of them eagerly:
a workspace that has only ever rendered mockups still plans.

Plus one leaf that is not a module: `etsy_listings/terminal.py` answers "can
this stream print that character?" for anything that decorates output. Both
`cli` (the `apply` swatches) and `newcmd` (the picker's local-garment-profile marker)
need it, and while it lived in `cli` the second of those was an import
pointing *up* through the layering — the one place the "no cycles" claim above
was not actually true. It depends on nothing but the standard library, so
anything may depend on it.

Each package's `__init__.py` states its own interface: what it exports, and
what it deliberately withholds. Those docstrings are the short version of this
table, kept next to the code.

Three boundaries carry most of the weight:

- **`workspace` is the only module that knows the tree's shape.** Everything
  else asks for "this listing's lockfile" rather than joining
  `listings/<name>/state.lock.json`. That is also what makes the UI safe:
  template names arriving from URLs are validated by the same rule that guards
  every other path (A8), not by a second check in the web layer. Reading a
  config file is part of that: `load_listing`, `load_garment_profile` and
  `load_template_config` are how the tree's files are opened, so no caller
  writes its own `yaml.safe_load(path.read_text(...))` against a path it
  assembled.
- **Only `engine` computes a diff.** `cli` and (later) `ui` consume `Plan` /
  `StagePlan` / `Change` objects and render them. Neither compares state, which
  is what guarantees the PRD's "one set of rules regardless of route". The same
  rule applies one level up, to the shape of a *run*: `plan_listings` and
  `apply_listings` own each lockfile's lifecycle and PRD 16's
  continue-on-error, and an entry point only formats the `RunReport` they
  return. Both of those lived in `cli/app.py` until they were lifted, which is
  why the rule is worth stating twice.
- **`render` is pure.** Arrays and frozen config in, an image out. The stage
  around it does the I/O. This is what makes both the input hash and the
  goldens meaningful.

## What `plan` and `apply` actually do

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli
    participant WS as workspace
    participant Engine as engine
    participant Stage as Stage (STAGES)
    participant Render as render
    participant Lock as state.lock.json

    User->>CLI: etsy-listings plan take-a-hike
    CLI->>WS: discover(--root / env / walk up)
    CLI->>Engine: plan_listings(ctx, names, STAGES)

    loop each listing, continue-on-error (PRD 16)
        Engine->>Lock: read (or start empty)
        Engine->>Engine: build_plan(ctx, listing, lock, STAGES)

        loop each stage, in pipeline order (A1)
            Engine->>Stage: desired(ctx, listing)
            Engine->>Lock: applied_for(stage.name)
            alt stage is not local
                Engine->>Stage: read_live(ctx, lock)
            end
            Engine->>Stage: plan(desired, applied, live) → StagePlan
        end

        Engine-->>CLI: on_planned(listing, PlannedRun)
        CLI->>User: format_plan(plan)
    end

    Engine-->>CLI: RunReport
    CLI->>User: exit 1 if report.failed

    Note over User,Lock: apply is the same walk, then the writes
    User->>CLI: etsy-listings apply take-a-hike
    CLI->>Engine: apply_listings(ctx, names, STAGES)
    Engine->>Engine: build_plan(...), then execute(ctx, planned, lock)
    Engine->>Stage: apply(...) — strictly sequential (A3)
    Stage->>Render: render(design, base, cfg) per colour
    Stage-->>Engine: StageApplyResult(applied, outputs)
    Engine->>Lock: write merged lockfile
```

Today `STAGES` is `[Render()]`. Adding `Generate`, `PrintifyProduct`,
`Publish`, `EtsyCopy` and `EtsyMedia` in later phases changes that list, not
this flow.

## The three-way comparison

Each stage's own `plan()` compares three states using the shared helpers in
`engine/change.py`:

```mermaid
graph LR
    D["<b>desired</b><br/>config files + rendered mockups"] --> Diff{"stage.plan()"}
    A["<b>last applied</b><br/>state.lock.json → applied.&lt;stage&gt;"] --> Diff
    L["<b>live</b><br/>Printify + Etsy<br/>(None for local stages)"] --> Diff
    Diff --> SP["StagePlan(will_run, changes, drift)"]

    D -. "≠ applied ⇒ a change you made" .- A
    A -. "≠ live ⇒ drift, someone edited outside the tool" .- L
```

`read_live()` returning `None` (`stage.local = True`) skips drift entirely, so
no stage has to special-case it. The render stage is local: there is no remote
mockup to drift from.

## Two hashes, doing different jobs

```mermaid
graph TD
    Design["design bytes"] --> IH
    Template["template.yaml + colour images"] --> IH
    Cfg["resolved RenderConfig per colour"] --> IH
    IH["<b>input_hash</b><br/>canonical_hash(applied subtree)"] --> Rerender{"re-render?"}

    Png[".cache/renders/*.png bytes"] --> OH["<b>outputs</b><br/>per-file content hash"]
    OH --> Reupload{"re-upload?<br/>(Phase 3)"}
```

Collapsing these into one hash breaks the case the PRD calls out: a Pillow or
OpenCV upgrade changes rendered bytes without changing any input, and those
images must re-upload. `applied_at`, `tool_version`, `remote` and absolute
paths never enter a hash; paths that do are workspace-relative and
forward-slashed, so a Windows machine and a Linux runner agree.

## The calibrator

```mermaid
graph LR
    Canvas["Calibrate tab<br/>quad handles + sliders"] -->|"POST /preview?scale=editor<br/>(debounced)"| API["ui/api"]
    Tab["Preview tab<br/><i>on demand</i>"] -->|"POST /preview?scale=full"| API
    API --> Cache["ui.api.imagecache<br/><i>decoded photo, design, maps</i>"]
    Cache --> RenderPipe["render.pipeline<br/><i>the same code apply runs</i>"]
    RenderPipe -->|WebP| Canvas
    RenderPipe -->|PNG| Tab
    Canvas -->|"PUT /config"| API
    API -->|writes| Yaml["mockup-templates/&lt;set&gt;/template.yaml"]
    Yaml -->|read by| Stage["engine render stage"]
```

The preview is the real renderer, not an approximation — that is the whole
point of calibrating in a browser. `template.yaml` is the artefact the
calibrator produces and the render stage consumes; nothing else passes between
them.

"Real renderer" is now structural rather than a claim maintained by hand. Both
routes ask `Workspace.scene_photo()` which photo a scene composites over and
what its derived maps cache under, and both composite through
`render_scene()`. The one thing the preview does differently is where its
geometry comes from — the unsaved boxes under the user's cursor, not the file
on disk — which is exactly the difference that makes it a preview.

### Two sizes, one pipeline

A drag emits a preview request every few frames, and at a real garment photo's
resolution each one re-decoded the mockup PNG and the design PNG from disk,
warped at full size, and PNG-encoded several megabytes — seconds of work per
frame, for an image about to be replaced. So the two things a preview is *for*
were separated:

| | Calibrate tab | Preview tab |
|---|---|---|
| Request | `?scale=editor` | `?scale=full` |
| Base | downscaled to `EDITOR_MAX_EDGE` (900px) | the photo's own size |
| Encoding | WebP, low effort | `encode_png`, as `apply` writes |
| When | debounced, one in flight at a time | on opening the tab, then only on Re-render |

Both run `render_scene()` over the same photo and derived maps. What differs
is how many pixels the server is asked to spend, which is why the fast one is
still honest: it is the output, at a size you can drag against.

The Preview tab renders itself on first sight and then holds still. A config
edit afterwards does not re-run it — a full-size set is minutes of work, and a
nudged box is not a request for it — but it must not silently become a picture
of geometry that has moved on either, so Re-render turns red. The panel stays
mounted behind the canvas rather than unmounting, or flicking between tabs
would throw the renders away and "there is none, so render" would fire on a
set that had just been rendered.

Two consequences worth knowing:

- **Bounding boxes stay in the photo's true pixel space.** `template.yaml`
  stores them there, so the endpoint scales them (and `displace.strength`,
  which is denominated in absolute pixels) onto the smaller canvas, and the
  client is *told* the true size in `TemplateSummary.width`/`height` rather
  than measuring the image it is drawing over. Measuring it would save every
  box a few times too small, with nothing on screen looking wrong.
- **`ui.api.imagecache` memoises what the loop re-reads** — the decoded photo
  at each size, the decoded design, and the derived maps — keyed on path and
  mtime, bounded by total bytes rather than entry count. It sits in `ui`, not
  in `render.io`: the render stage reads each file once per run and needs no
  cache, and giving it one would put mutable process state under the pure
  layer for nobody's benefit.

## Testing layers

| Layer | Answers |
|---|---|
| Unit | Does this function obey its contract? (`Money`, slugs, hashing, path safety) |
| Golden | Did the pixels change, and which pass changed them? |
| Behaviour | Does plan/apply do the right thing over time? (idempotency, re-render on change) |
| Browser | Do the React app, the API and the renderer work together? |
| Contract | *(Phase 2+)* Does the wire payload match what the API expects? |
| E2E | *(Phase 2+)* Does it work against the real Printify and Etsy? |

Reach for a fake to test behaviour and a cassette to test payload shape. The
browser layer exists because nothing below it can catch a wiring mistake
between three otherwise-tested pieces.
