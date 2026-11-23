# Workspace backup implementation plan

Written 2026-11-23 from the [specification](spec.md) and the
[interactions document](interactions.md). Status: in progress as a stacked PR
series. This plan owns the delivery sequence. The spec owns requirements and
the interactions document owns UI behaviour, so cite their sections rather
than restating them.
[ADR-0059](../../adr/0059-back-up-the-workspace-with-restic-from-the-app.md)
records the design choices.

The clickable source is the **Admin · Workspace backup** board
([`src/ui/design/scenes/workspace-backup/`](../../../src/ui/design/scenes/workspace-backup/)).
Keep the frames fixture-driven and copy markup and styles into production
components. Screenshots for comparison are in [`screenshots/`](screenshots/).

## Decisions

| Id | Decision |
|---|---|
| P0 | Every delegate runs on `claudeAgent` `claude-opus-5-5` at medium effort, whatever the PR's difficulty. Fall back down the skill's table only when Claude has no headroom. |
| P1 | Split: the job gate; restic and configuration; the backup run; the copy; the server scheduler and status API; the Backup UI; restore; the missing repository and the migration guide. The gate comes first because it changes the deploy, AI and Prepare coordinators, which is the riskiest work and needs nothing else. The copy is separate from the run because its rules (spec, *Copy to destinations*) need their own tests. |
| P2 | Never touch the live workspace or the seller's real backup folders. Tests use `tests/fixtures/workspace/` copied to `tmp_path`, with repositories and destinations under `tmp_path`. Per-user state takes a `home` parameter, as `core/preparation/runtime.py` `Runtime` does, so no test writes to the real `~/.etsy-listings`. |
| P3 | Tests that need restic itself are marked `restic`. They use the pinned binary, found through the `restic_binary` setting or the `ETSY_LISTINGS_RESTIC_BINARY` environment variable. CI downloads and caches the pinned release once per run. Locally they run when the binary is present and skip otherwise. Everything else uses a fake runner that replays recorded `--json` lines. |
| P4 | "Waiting for backup" is a flag on items that are already queued: `waiting_for_backup: true` on deploy run summaries, batch rows and Prepare job responses. It is never persisted. Manual AI runs never queue today (`AiCoordinator.start_run` starts a thread at once), so they gain a `queued` phase carrying the same flag. |
| P5 | `backup` is an optional field on `Settings` (`backup: BackupSettings \| None = None`), without the `_absent_is_empty` coercion, so an absent block means off. `Settings` refuses unknown keys, so no workspace can hold a `backup:` block before PR 2 lands. |
| P6 | restic runs through a new streaming runner, not `core/ai/process.py` `run_managed`. That runner takes no environment, buffers stdout to the end, and needs input text. The new runner uses `subprocess.Popen` with line-buffered stdout, as `core/preparation/worker_client.py` does. It passes `RESTIC_PASSWORD` only in the child's environment, and kills the process tree on cancel. |
| P7 | The seller migrates the real workspace by hand after the last PR merges, following the guide PR 8 writes (spec, *Migration*). No agent runs a migration or a backup against real folders. |
| P8 | The stack base is a new branch from `main` that holds only this feature's docs and mockups. This worktree's branch also has unrelated uncommitted fixes, which must not go in. |

## Delivery sequence

Commit the spec, ADR-0059, the interactions document, the screenshots, the
`workspace-backup` scenes (live and `-v1` to `-v3`), the two boards, the
manifest and this plan as documentation before implementation. That commit is
the stack base. Record it and each PR link here when execution starts. Each PR
is based on the preceding tip.

| PR | Title | Difficulty | Branch | Link |
|---|---|---|---|---|
| 0 | Stack base: docs and mockups | — | `feat/workspace-backup` | |
| 1 | A pause gate for background jobs | hard | `feat/backup-1-gate` | |
| 2 | restic and the backup settings | standard | `feat/backup-2-restic` | |
| 3 | The backup run | hard | `feat/backup-3-run` | |
| 4 | Copying to destinations | hard | `feat/backup-4-copy` | |
| 5 | Scheduler and status API | hard | `feat/backup-5-server` | |
| 6 | Backup in Admin › Settings, with warnings | standard | `feat/backup-6-ui` | |
| 7 | Restore | standard | `feat/backup-7-restore` | |
| 8 | Missing repository and the migration guide | standard | `feat/backup-8-finish` | |

Size: aim for under about 1,500 changed lines per PR, not counting the
regenerated OpenAPI and client files and lockfiles. A PR that cannot fit splits
at a seam the orchestrator agrees, not mid-feature.

### PR 1 — A pause gate for background jobs

Spec: *Pausing jobs*, *Backup run* steps 1, 2 and 4. Decision P4.

Scope:

- A `JobGate` in `core/application/`, because Import Linter keeps core free of
  server imports and the gate is shared by every coordinator. It has `pause()`,
  `resume()`, `paused`, and `wait_idle()` with no timeout. `wait_idle` reports
  which job it is waiting for, so status can name it. `stop()` overrides it.
- Gate each place a unit of work starts:
  - `RunExecutor._loop` in `core/application/deploy/executor.py`: do not
    dequeue while paused.
  - `AiCoordinator.start_run` in `core/application/ai/coordinator.py`: while
    paused, record the run as `queued` and hold it. Release held runs in
    submission order on resume.
  - `BatchQueue.dispatch` and `_claim` in `core/application/ai/batch_queue.py`.
  - `Preparations._schedule` and `_dispatch` in
    `core/application/preparation/coordinator.py`.
  - `SceneWarmer._loop` in `core/application/scene_warming.py`.
- `wait_idle` counts what each coordinator already knows:
  - `Deployments.busy()`,
  - `BatchQueue._running()` and running manual AI runs,
  - `running` Prepare jobs,
  - the warmer's current pass (`wait_idle` exists there).
- Keep `RunExecutor._execute`'s `ai.yield_to_deploy(...)` working: pausing
  stops new intake first, then waits, so a deploy already waiting on AI still
  finishes.
- Construct the gate in `create_app` in `server/api/app.py`, pass it to all
  four coordinators, and put it on `app.state` with a typed reader in
  `server/api/app_state.py`.
- Add `waiting_for_backup` to `PlanRunSummary`, `ApplyRunSummary`,
  `AiRunSummary`, `BatchRow` and `PreparationJobResponse` in
  `server/api/schemas.py`. Add `"queued"` to `AiRunPhase` in
  `core/application/ai/events.py`. Regenerate `docs/openapi.json` and the
  client.
- Where the UI shows these states today, show "Waiting for backup" when the
  flag is set: the deploy run view, AI runs, the batch summary, and Prepare
  status. The UI must handle a manual AI run that starts `queued`.
- Update `docs/architecture.md`, *Server lifecycle, runs, AI and batch
  creation*.

Exit when:

- behaviour tests, one per coordinator, prove that nothing starts while the
  gate is paused, that work submitted meanwhile is accepted and reports
  `waiting_for_backup`, and that resume releases it in submission order;
- a test proves `wait_idle` returns only after an in-flight deploy, AI run,
  batch row, Prepare job and warming pass have each finished, and names what it
  waits for;
- a test proves a deploy waiting in `yield_to_deploy` for an AI run completes
  while the gate is pausing, without deadlock;
- a test proves shutdown during a pause stops cleanly and drops held work, as
  it drops queued work today;
- with no pause ever requested, existing deploy, AI, batch and Prepare tests
  pass unchanged;
- vitest covers the "Waiting for backup" label on each page that shows it;
- shared gates pass, including the e2e workflow (this PR touches the deploy
  path).

Deviations recorded during implementation:

- `wait_idle` counts admission tickets the gate hands out, not each
  coordinator's own state (`Deployments.busy()`, `BatchQueue._running()`,
  running Prepare jobs). Checking a coordinator's state and then starting work
  leaves a window where a backup sees nothing in flight while a job is about
  to begin. Taking the ticket under the gate's lock closes that window.
  `Deployments.busy()` also counts queued runs, which a pause holds, so a wait
  for it would never end.
- A Prepare job between its GPU and CPU steps (`cpu_queued`) holds no
  ticket. A backup can therefore snapshot its work files mid-job, which the
  spec already accepts for Prepare work files.
- Fixed in its own commit: two AI runs whose listings share a design raced on
  `ai/viewable.py`'s `{name}.{pid}.tmp`. The partial name is now
  `{name}.{pid}.{thread}.tmp`, which PR 3's exclude list must match.

### PR 2 — restic and the backup settings

Spec: *Configuration*, *Scope and decisions* (restic binary, Repository),
*Open questions* (the restic version). Decisions P3, P5, P6.

Scope:

- `BackupSettings` and `RetentionSettings` in `core/config/settings.py`, as
  `backup: BackupSettings | None = None` (P5): `repository`, `destinations`,
  `interval_hours` (one of 4, 6, 12, 24, 48), `retention` (`keep_within_days`,
  `weekly`, `monthly`, each at least 1), `restic_binary`.
- `ETSY_LISTINGS_BACKUP_PASSWORD` in `Secrets` (`core/config/secrets.py`) and
  in `credentials.stored`. Make `scaffold.write_env_value` write atomically
  through `core/workspace/atomic.py`, because `.env` will hold the only copy of
  the password on this machine.
- A per-user directory helper for `~/.etsy-listings`, taking `home`, used by
  the restic installer and later by `backup-state.json`.
- The restic installer: pin the newest release that is at least two weeks old,
  with its SHA-256 for Windows amd64 and Linux amd64. Download, check the
  digest, then unpack into a staging directory and rename it into place, as
  `Runtime._install` does. Protect it with an Import Linter contract, as
  `preparation.installation` is protected.
- The streaming restic runner (P6): run a subcommand with `--json`, yield
  parsed lines, map exit codes and stderr to typed errors (wrong password, not
  a repository, locked), and support cancel.
- A `backup` Typer group in `cli/`, mirroring `cli/marigold.py`, with the
  workspace option from `cli/options.py`. Commands: `init` (create the
  repository; ask for and store the password when `.env` has none),
  `snapshots`, and `status` (configuration and repository reachability for
  now). Path arguments go through `to_native_path`. Update the command list in
  the `cli/app.py` docstring.

Exit when:

- tests prove an absent `backup:` block means off, a full block loads, and
  invalid intervals and retention are refused with readable messages;
- tests prove the installer refuses a digest mismatch, leaves no half-installed
  directory, and installs nothing under the real home directory;
- tests with the fake runner cover each error mapping and cancel. `restic`
  tests prove `init` and `snapshots` work against a repository in `tmp_path`
  (P3);
- a test proves the password never appears in the command line, logs or error
  messages;
- CLI surface tests in `tests/cli/behaviour/test_cli_surface.py` list the new
  group;
- shared gates pass.

Deviations recorded during implementation:

- The pin is restic 0.19.1 (published 2026-07-05), because 0.20.0 was four
  days old. Its digests come from the release's `SHA256SUMS`, and the Windows
  zip was downloaded and checked against it. Only the archive is checked, at
  install. The unpacked binary is not hashed again on each run.
- `ETSY_LISTINGS_RESTIC_BINARY` wins over the `restic_binary` setting, as the
  process environment wins over `.env` for credentials. CI can then point
  every test at its download whatever a fixture's settings say.
- Creating, opening and reporting on a workspace's repository is a new
  module, `core/application/backup_repository.py`, which the plan did not
  name. It joins the settings, the password and the binary, so `core/backup`
  knows no workspace and PR 3 and PR 5 reuse it.
- `backup init` already refuses a password under 12 characters and a folder
  that holds files. The plan put those refusals in PR 5 and PR 8. It stores a
  new password before `restic init` runs, and asks for it twice through
  `cli/prompts.py` in plain text, like every other credential (a cygwin pty
  cannot hide input).
- `status` reads snapshots with `--no-lock`, so it answers while a backup
  holds the lock. It exits 1 when the repository does not open.
- Stopping restic does not use a Job Object. restic runs in its own process
  group (a new session on POSIX, `CREATE_NEW_PROCESS_GROUP` on Windows) and
  gets an interrupt first (`SIGINT`, `CTRL_BREAK_EVENT`) so it can drop its
  lock. After five seconds the group is killed (`killpg`, `taskkill /T /F`).
  restic starts no child processes for a local repository.
- `repository`, `destinations` and `restic_binary` go through
  `to_native_path` when `settings.yaml` is parsed, not where they are used.
  On Windows a `Path` already reads `/cygdrive/c/...` as `\cygdrive\c\...`
  on the current drive. PR 7's restore target is a CLI argument and must go
  through `to_native_path` too.
- `write_env_value` now writes bytes, so `.env` keeps LF endings on Windows,
  where `write_text` used to write CRLF. `tests/cli/behaviour/test_auth.py`'s
  ordering spy also records `Path.replace`, because `.env` now arrives by a
  rename.
- Tests marked `restic` skip locally when `ETSY_LISTINGS_RESTIC_BINARY` is
  unset. Every CI python leg installs the pin through
  `scripts/install_restic.py`, which runs the app's own installer so the
  digests live only in `core/backup/binary.py`. It caches the download by
  version and sets `ETSY_LISTINGS_REQUIRE_EVERY_LAYER`, so a missing binary
  fails instead of skipping.
- Exit code 11 is proved against real restic: a `restic key passwd` waiting
  on stdin holds the exclusive lock while `snapshots` runs.
- The size is about 2,450 lines, over the 1,500 aim. About 1,150 of them are
  source and docs, and the rest are tests. The orchestrator accepted it
  unsplit.

### PR 3 — The backup run

Spec: *Backup run*, *Status and warnings* (the state file), *CLI* (`run`,
`check`). Decision P3.

Scope:

- A backup operation in `core/application/` that runs the spec's steps 3, 5
  and 6. With a `JobGate` it also runs steps 1, 2 and 4: the server passes one,
  the CLI does not (spec, *CLI*).
- The exclude list for the app's own temporary files:
  - `.{name}.*.tmp` (`core/workspace/atomic.py`, render, scene cache),
  - `{name}.{uuid}.tmp` (market snapshot and cache),
  - `{name}.{pid}.tmp` (`ai/viewable.py`),
  - `{name}.tmp` (Etsy tokens, `engine/lock.py`),
  - the Marigold worker's `.{name}.{uuid}` prediction temporaries,
  - `uploads/incoming.png`,
  - the map `staging/` directory and `calibration-transaction/`.

  Each pattern carries a comment naming its writer, and a test pins the list
  to the writers.
- Retention: forget with `--keep-within {days}d --keep-weekly {weeks+1}
  --keep-monthly {months+1}` (spec, step 5).
- Weekly prune, then check. `backup-state.json` in the per-user directory
  records prune and check times. The last successful backup comes from
  `restic snapshots --json`, not from the state file.
- Progress events from restic's `--json` status lines, enough for the UI's
  running line: files checked out of the total, then the step.
- CLI `run` and `check`.

Exit when:

- `restic` tests back up a fixture workspace in `tmp_path` and restore it
  byte for byte, prove every exclude pattern leaves its file out, and prove the
  forget flags keep the snapshots the spec's retention describes over a
  simulated month of runs (snapshot times can be set with `--time`);
- fake-runner tests prove that with a gate, jobs resume whether the backup
  succeeds or fails, and that steps 5 and 6 run after resume;
- a test proves prune and check run only when 7 days have passed;
- shared gates pass.

Deviations recorded during implementation:

- The exclude list differs from the plan's, after checking each writer.
  `*.tmp` covers four of the plan's patterns. `ai/viewable.py` now writes
  `{name}.{pid}.{thread}.tmp` (PR 1). The Marigold worker's temporaries are
  `.{name}.npz.{uuid}`, so the pattern is `.*.npz.*`. Template renderer
  folders are `_renderer/`, so the map and calibration patterns are
  `_renderer/maps/staging` and `_renderer/calibration-transaction`. Three
  writers the plan did not list are added: the position-fit staging
  directory `.cache/position-fits/.{key}-{uuid}`, a mockup photo between its
  two renames (`.{slug}.renaming.png`), and a dropped ZIP while it is read
  (`.cache/staging/*/upload.zip`).
- The writer pin is a source check per writer: the test reads each writer's
  module and asserts the expression that names its temporary is still
  there. The `restic` test then backs up a sample of each name.
- The run is a `BackupRunner` object with `run()` and `check()`, so PR 5's
  coordinator holds one value, not six arguments.
- A failed weekly check fails the run (`failed_step: "checking"`), keeping
  the snapshot id. A run that cannot open the repository, such as one with
  no password, is recorded as failed at `"starting"`. Backups switched off
  are not a run and record nothing.
- restic's exit code 3, a snapshot made without some unreadable files,
  counts as a successful run, with each such file as a warning.
- The run history is `~/.etsy-listings/backup-history.jsonl`, one JSON
  object per run, oldest first. Each object holds `repository`,
  `started_at`, `finished_at`, `outcome` (`succeeded`, `failed` or
  `stopped`), `snapshot_id`, `failed_step`, `message` and `warnings`.
  `backup-state.json` names its repository, and a different repository starts
  with empty state.
- The retention test spans four months of runs rather than one, because a
  month cannot show the monthly rule. It checks restic's result against the
  spec's wording, not against restic's flags.
- `backup run` and `backup check` take no `--json`. PR 5's API reads the
  history file directly.
- Handed to PR 7: the weekly prune fails the run when another restic holds
  the repository lock, as a restore does. PR 7 must make the prune wait for
  a running restore (spec, *Restore*).

### PR 4 — Copying to destinations

Spec: *Copy to destinations*, *Changed and unexpected files*, *Checking a
destination*, *Backup run* steps 7 and 8.

Scope:

- A copy module in `core/` with no restic dependency. It lists in read order,
  sorts destination files into present, changed, expired and unexpected, copies
  in write order through temporary names with a streaming SHA-256 check, then
  deletes expired files in reverse order and cleans up its own temporaries.
  It never overwrites a file and never deletes an unexpected one.
- An unreachable destination is skipped and reported. The local backup still
  counts as successful.
- Repair: move changed and unexpected files to
  `<destination>-set-aside-<date>`, then copy again.
- The monthly sample check: hash a random 5% of a destination's files against
  their names and compare `config` byte for byte. It writes nothing to the
  destination.
- Per-destination state in `backup-state.json`: last successful copy, last
  check, and the changed and unexpected files found.
- Wire the copy and the monthly check into the backup run from PR 3.

Exit when:

- tests prove the write and delete orders, and that a copy interrupted at any
  file leaves a destination `restic -r` can still open (a `restic` test);
- a test simulates a prune between the listing and the copy and proves the
  destination never holds an index pointing to a missing pack;
- tests prove a size change stops the copy and reports the file, that an
  `x 2` conflict copy is reported and kept while copying continues, and that a
  same-size content change is caught by the sample check;
- tests prove repair sets files aside, deletes nothing, and leaves a complete
  destination;
- a test proves the copy, the sample check and repair never replace a file
  that exists at the destination, by checking file identity before and after;
- shared gates pass.

Deviations recorded during implementation:

- The copy module is `core/backup/destinations.py`. It imports nothing from
  `restic.py`. `BackupRunner` gains `repair(destination)` for PR 5's
  endpoint, and `backup run` prints each copy's outcome. The CLI has no
  repair command, because the spec's *CLI* lists none.
- A copy never creates its destination. A missing destination folder is
  unreachable ("Folder not found", as frame `04-failing` shows), even when
  its parent exists. If iCloud is signed out, `iCloudDrive\` can still be
  there, and creating the folder would copy about 20 GB into a folder
  nothing syncs while reporting the copy up to date. Only set-up creates a
  destination folder: PR 5 calls `create_destination`, which makes the
  folder when its parent exists and refuses with `DestinationNotFoundError`
  otherwise.
- A local file whose contents no longer match its name gets its own outcome,
  `damaged`. The run fails at `copying`, `last_check` records the failure as
  the spec asks, and no further destination is copied. No copy runs after a
  failed weekly `restic check` either.
- Each run's history entry gains `copies`: each destination's outcome
  (`copied`, `unreachable`, `changed`, `damaged`, `failed` or `stopped`) with
  its message. An unreachable or changed destination leaves the run
  `succeeded`.
- `backup-state.json` gains `destinations`, keyed by the path as
  `settings.yaml` gives it. Each holds `last_copy`, `problem` (why the
  latest copy did not finish), `last_check`, `changed` and `unexpected`. A
  change the sample check finds keeps its size, so a later copy cannot see
  it by listing. The state keeps it, the next copy treats it as changed, and
  only a repair clears it.
- The monthly sample check runs only after a copy to that destination
  finishes, and only once 30 days have passed since its last check. It
  samples files that both folders hold, rounding 5% up to at least one file.
  `config` is always compared.
- The copy's temporaries are `<name>.copying-<8 hex>`. `locks/` and restic's
  own `-tmp-` names at a destination are neither expired nor unexpected,
  because restic writes them itself when it opens a destination, say to
  restore from it.
- An empty or foreign local folder (no `config`) is refused before the
  destination is listed. A wrong repository path would otherwise make every
  destination file look expired, and the copy would delete them.
- On POSIX, a hard link gives a file its name, because `rename` would
  replace an existing file. A filesystem without hard links falls back to
  checking for the name, then renaming. Windows' rename refuses an existing
  name.
- Repair puts files in a new folder each time: `-set-aside-<date>`, then
  `-2`, `-3` and so on the same day. The date is the local date.
- The copy reports no per-file progress yet, only the step and the
  destination. PR 5 can add a count from `CopyHooks.observe` if the UI
  needs one for the first, full copy.
- The interrupted-copy `restic` test starts from a complete earlier copy.
  An interruption before the first copy has written `config` and a key
  cannot leave a repository restic opens.

### PR 5 — Scheduler and status API

Spec: *Scope and decisions* (Scheduling, Manual run, Failures), *Status and
warnings*, *Configuration*. Interactions: *What the production implementation
must finish*.

Scope:

- A backup coordinator started and stopped in the `create_app` lifespan. It
  owns the gate's pause during runs. A backup is due `interval_hours` after the
  last success, and the coordinator checks on start-up.
- Endpoints under `/api/backup`:
  - `GET` status, the single source for every warning (spec, *Status and
    warnings*): last success, next due, the running step and the job it waits
    for, the repository's check result, and per destination the last copy, the
    last check, and the changed and unexpected files. Shape it from the
    prototype's fixtures.
  - `GET` the history of runs.
  - `POST` run now.
  - `POST` set up: write the block and the password, init, then start the
    first backup.
  - `POST` repair for one destination.
- Run history lives in the per-user directory beside the state file, with one
  entry per run. Snapshots come from restic.
- Setup edits go through the Admin settings revision check: add the `backup.*`
  keys to `EDITABLE_KEYS` in `core/application/workspace_settings.py`, with
  `sequence_keys` for destinations.
- Regenerate `docs/openapi.json` and the client. Update `docs/architecture.md`
  and add **Backup storage folder** and **Destination** to `CONTEXT.md`.

Exit when:

- tests drive the scheduler with a fake clock: due after the interval from the
  last success, overdue at start-up, nothing while a run is in progress, and a
  changed interval taking effect on the next check;
- server behaviour tests cover each endpoint, including set-up refusing a
  non-empty folder and a password under 12 characters, and a Setup save
  keeping the comments in `settings.yaml` (ADR-0055);
- a test proves each warning condition in the spec appears in the status, and
  clears when the problem does;
- shared gates pass, including the e2e workflow (this PR changes the server
  lifespan).

Deviations recorded during implementation:

- The coordinator runs one backup operation at a time: a run or a repair,
  and later PR 7's restore steps that conflict. A second one gets
  `BackupBusyError`, a 409. Repair answers when it ends, holding that slot,
  rather than running as a job with its own status.
- A failed run is tried again an hour after it ended (`RETRY_AFTER`), not
  at every check. A locked or unreadable repository would otherwise add a
  failed run to the history every five minutes. A run stopped by shutdown
  does not count, so the next start-up backs up at once.
- The scheduler checks every five minutes, and each check runs
  `restic snapshots --no-lock`. Status reads a cached copy, which is read
  again after each operation and whenever a run has finished since. A
  folder without restic's `config` stops the schedule and reports
  `repository_missing`, without running restic.
- Status has six warning kinds: `off`, `repository_missing`, `stale`,
  `failed`, `behind` and `changed`. Every kind except `off` has
  `banner: true`. A missing repository hides the other warnings. A run
  stopped by shutdown raises none. "More than 24 hours behind" counts from
  the oldest snapshot the destination has not had yet.
- The history endpoint returns each run with `kept_as`: `recent`,
  `weekly`, `monthly`, or null once its snapshot is forgotten. It follows
  the spec's wording, not restic's own forget output. Each run now also
  records restic's `data_added`, for the history's Added column.
- Copy progress counts files, not bytes. `CopyHooks` gains `planned(n)`,
  the number of files a destination lacks, and the running line counts
  copied files against it. Packs are about 16 MB, so files move steadily
  enough.
- Destinations are plain paths, so `sequence_keys` alone could not keep
  their comments: a replaced path took the old path's comment. The YAML
  editor gains an `ITSELF` identity, so each path is known by its value.
- Set-up is `POST /api/backup/setup`. It writes the whole block through
  the settings revision check (`edit_settings(editable=("backup",))`). It
  is refused once backups are set up. It creates the destination folders,
  as does a Setup save that adds one, through PR 4's `create_destination`,
  and each must be inside a folder that exists. A run never creates one:
  a destination folder that is missing is reported as "Folder not found".
  The refusals now carry categories: backups off and a
  folder that holds files are conflicts (409), and a short password is
  refused (422).
- `create_app` gains `backup: BackupEnvironment`, which holds `home`, the
  restic launcher and the clock, for tests (P2, P3).
- Handed to PR 7: the history lists only runs the app recorded. A snapshot
  made by hand with restic has no entry there, so PR 7's restore list must
  read restic's own snapshot list.
- Size: about 1,880 changed lines without the generated files, about 1,050
  of code and docs and 800 of tests, over the 1,500 aim. Accepted unsplit.

### PR 6 — Backup in Admin › Settings, with warnings

Interactions: *Where Backup lives*, *Status and history*, *Set up and Setup*,
*Warnings*, *Changed and unexpected files*. Frames 01, 02, 03, 04, 07, 08, 11
and 12.

Scope:

- Extend `Section`, `SETTINGS` and `Nav` in `src/ui/src/pages/admin/AdminPage.tsx`
  with Backup and its two nested pages. Put the section in the URL
  (`/admin?section=backup`) and keep today's sections working.
- Production components from `_parts.tsx` and `_prototype.tsx`, as the
  interactions document's table says: status panel, storage diagram, history,
  the set-up and Setup form, the banners, and the repair dialog.
- An API module `src/ui/src/api/backup.ts`, and a status hook the shell and
  the page share. It polls faster while a run is in progress.
- The banner and the Admin dot in `src/ui/src/shell/AppShell.tsx`: the banner
  above `<Outlet/>` when not on `/admin`, and the dot in the Admin `NavLink`.

Exit when:

- vitest covers every input in *Set up and Setup*, each warning's banner and
  action, the nav item's states, and the shell banner showing and hiding by
  route;
- a browser test sets up backups against a real server on a fixture workspace
  (with `restic` available) and sees the first backup appear in the history;
- mockup-vs-app screenshots for frames 01, 02, 03, 04, 07, 08, 11 and 12 are in
  the PR;
- shared gates pass.

Deviations recorded during implementation:

- The address is `/admin?section=<s>` with `s` one of `defaults`, `ai`,
  `rendering` and `backup`; Connected shops is bare `/admin`. Setup adds
  `&page=setup`. Before set-up the Backup item itself is current.
- `BackupStatusProvider` in the shell is the one poll: every 30 s, every
  2 s while `running` is set, none while the tab is hidden, and a read on
  showing it again. Relative times count from when the status was read.
- Set-up runs after the settings save queue drains, naming its revision,
  then reloads `settings.yaml`. Setup saves only the changed `backup_*`
  keys through the same queue; a conflict uses the existing reload banner.
- Restore… is left out of the status panel and the history (PR 7), so the
  history has no actions column.
- No Choose… button or "Empty folder · N GB free" hint: the API has no
  folder picker or folder inspection. The hint says the folder must be
  empty or new, and set-up's refusal shows under the form.
- The diagram's workspace box shows no folder name or size, and the storage
  box counts backups rather than bytes: the status carries neither.
- Destinations are named from their path: "iCloud Drive" for a path with
  iCloud in it, else the folder's name.
- Relative times use the editor's `timeAgo` ("2 hrs ago").
- The retryable warnings (`stale`, `failed`, `behind`) share one banner with
  one Try again, disabled while a run is in progress. A missing repository
  shows its message with no action (PR 8). Each destination with changed
  files has its own banner.
- The repair dialog's "Set aside in" is worked out in the browser as
  `<folder>-set-aside-<today>`; the note after it names the folder the
  server used.
- The brief highlight goes to the newest run that finished after the page
  opened. A forgotten snapshot's row reads "No longer kept".
- The mockup stylesheet moved to `src/ui/src/pages/admin/backup/backup.css`
  and the live scene imports it from there (design promotion rule).
- Size: about 2,600 changed lines, 830 of them tests, over the 1,500
  target; accepted at review without a split.
- Set-up's stale revision is told from its other conflicts by the HTTP
  status (412 against 409), as `saveSettings` already does; both bodies
  are `kind: "conflict"`, so no new field was needed.
- Backups off leaves out the mockup's "Already have backups…" note until
  Connect exists (PR 8). A destination's pill names its problem when the
  reason is short ("Folder not found"), else says "Not copied".
- The app screenshots come from a scratch script that serves `create_app`
  with a `BackupEnvironment` (temp home, the test suite's by-command fake
  restic) and seeded state, captured with Playwright's Chromium at
  1280 × 800: the CLI cannot take a fake restic or a temp home.

### PR 7 — Restore

Spec: *Restore*, *CLI* (`restore`). Interactions: *Restore*. Frames 05, 06,
09 and 10.

Scope:

- A restore job on the backup coordinator, one at a time, with progress from
  `restic restore --json` and the time left estimated from the rate. It
  refuses the live workspace and any non-empty folder. Stop ends the job and
  leaves the partly restored files.
- Endpoints: start, status (included in the backup status), and stop.
- CLI `restore <snapshot> <target>` with the same refusals.
- The UI: restore dialog, restoring dialog, the strip in the status panel, and
  the restored dialog.
- In `docs/guides/`, the disaster restore with no app:
  `restic -r <destination> restore latest --target <folder>`.

Exit when:

- a `restic` test restores a snapshot made in PR 3's test and compares it byte
  for byte;
- tests prove both refusals, stop part way, that a scheduled backup can run
  during a restore, and that a weekly prune waits for it;
- vitest covers closing and reopening the progress, finishing with the dialog
  open or closed, and stopping;
- mockup-vs-app screenshots for frames 05, 06, 09 and 10 are in the PR;
- shared gates pass.

Deviations recorded during implementation:

- A restore has a slot of its own on `BackupCoordinator`, beside PR 5's
  backup slot, so backups and repairs run during it. The coordinator keeps
  the latest restore in memory only. A restart forgets it, as it stops it.
- The prune does not wait inside the run. A backup during a restore skips
  `forget`, `prune` and `check`, which take restic's exclusive lock, and the
  next run after the restore does them, because `last_prune` is unchanged.
  The restore passes `--retry-lock 1h`, so one started during a prune waits
  for the lock. A forget that starts in the moment before a restore takes its
  lock still fails that run, which is retried an hour later.
- The restore writes `<id>:<folder>`, the backed-up folder only, so the target
  is the workspace itself. A hand-made snapshot of several folders restores
  whole. `core/application/backup_restore.py` turns `C:\x` into `/C/x`, and
  `tests/support/restic.py`'s `snapshot_path` does the same for tests, which
  PR 3's restic test now uses so it works on Linux.
- Refusals: the live workspace, a folder inside it, the repository or a folder
  inside it, a folder that holds files, and a relative path (422). An unknown
  snapshot is a 404.
- `GET /api/backup/snapshots` lists restic's snapshots, newest first, with the
  workspace path the dialog refuses and builds its default folder from
  (`<workspace>-restore-<short id>`).
- The time left is worked out from restic's `seconds_elapsed` and
  `percent_done`. Before a restore starts there is no rate, so the dialog's
  Takes row gives no figure.
- No Choose… button, as in PR 6. The Restored dialog's file count is
  restic's `files_restored`.
- History rows offer Restore… only while their snapshot is kept.
- The disaster guide is `docs/guides/restore-a-backup.md`. restic 0.19.1 on
  Windows exits 1 after a whole-snapshot restore (it cannot set the timestamp
  of `C\Users`), so the guide also gives the `latest:/C/...` form.
- Finish: the app screenshots come from a scratch server on PR 5's
  `BackupEnvironment`, with seeded history under a temp home and a fake
  restic whose restore progress a test file steps through, captured with
  Playwright at 1280×800. No browser test was added: PR 7's exit conditions
  name none, and Vitest covers the flow.
- Size: about 1,800 changed lines without generated files, accepted over the
  1,500 target rather than split.

### PR 8 — Missing repository and the migration guide

Spec: *Missing repository*, *Migration*. Decision P7.

Scope:

- When the repository is missing or is not a restic repository, backups stop
  and status says so. The Backup page offers Create a new repository and
  Connect an existing repository. Connect copies the chosen repository to
  local disk first, using PR 4's copy code, then checks the password.
- A migration guide in `docs/guides/`: the spec's six steps, with the exact
  commands and how to check file counts and sizes.
- Update `docs/README.md`, the features table and the spec's status line.

Exit when:

- tests prove a missing or foreign repository stops backups and raises the
  warning, that create refuses a non-empty folder, and that connect copies then
  opens a repository made in a `restic` test;
- vitest covers both actions and their errors;
- shared gates pass.

Deviations recorded during implementation:

- Two endpoints: `POST /api/backup/repository` (create) and
  `POST /api/backup/connect`. Both are refused (409) while the configured
  folder holds restic's `config`, and both take the local folder, prefilled
  with `backup.repository`. A different folder is written to
  `backup.repository` through the settings revision check
  (`editable=("backup.repository",)`), because a workspace restored onto
  another machine names a folder from the old one. Refusals use set-up's
  shape: 409 for a folder that holds files, 412 for a stale revision, 422
  for a missing, short or wrong password or a source that is not a
  repository.
- The password in `.env` (or the environment) wins; the request's is read
  only when none is stored, and stored only once the repository is there.
  The status gains `repository.password_stored` so the dialog asks only
  when it must. The page offers no override for a stored password.
- Connect copies with PR 4's `copy_repository`, the source as the
  "repository" and a staging folder `<folder>.connecting-<hex>` as the
  "destination", so the source is only read. restic runs
  `snapshots --no-lock` on the staging copy; only then is it renamed to the
  target and are `settings.yaml` and `.env` written. A wrong password or a
  failed copy deletes the staging folder, so the next attempt copies again
  from the start. The revision is checked before copying as well as by the
  save, so a stale page does not waste a 20 GB copy; a save that loses a race
  in the moment after the rename leaves the repository in place under the
  new folder with `settings.yaml` unchanged.
- Connect answers when it ends, holding the backup slot as a repair does
  (`RunningBackup.operation` gains `connect`). Create starts the first
  backup, as set-up does; connect wakes the scheduler, which backs up when
  the copied snapshots say it is due.
- Create is refused (409) while any configured destination holds a
  repository's copy (`config`, `keys/` or `data/`), naming it, with
  `connect_from` in the refusal so the dialog offers **Connect this copy
  instead**, prefilled. Otherwise the copy's `config` would read as changed,
  a repair would set it aside, and the next copy would delete every old pack,
  index and snapshot as expired (found in review).
- Repair refuses (409, `ForeignCopyError`) whenever `config` is among a
  destination's changed files, and moves nothing. Telling another
  repository's `config` from a damaged one needs the password, so it does
  not try. The message says to connect that folder, or move it aside and
  leave an empty folder, or change the destination in Setup.
- A stored password that does not open the copy is refused with a message
  naming the `.env` file and `ETSY_LISTINGS_BACKUP_PASSWORD`, and saying to
  delete the line to be asked instead.
- "Foreign" means a folder without restic's `config`, PR 5's test. A folder
  with a `config` that is not restic's reads as present, and restic's error
  shows as the repository's problem.
- No Choose… button, as in PRs 6 and 7. The migration guide is
  `docs/guides/migrate-the-workspace-out-of-icloud.md`, written for
  PowerShell (robocopy, and `Get-ChildItem | Measure-Object` for file counts
  and sizes), with a section on connecting from a new computer.

## Shared gates

| Gate | Exit condition |
|---|---|
| G1 | Test-first for production behaviour (`tdd` skill). Fakes for workflows. No new real-shop e2e cases: backup sends nothing to Etsy or Printify. |
| G2 | `uv run poe check` from the repository root in Cygwin zsh. Python and frontend keep their 85% branch floors. Do not lower gates or exclude new code. |
| G3 | `npm run test:design` from `src/ui`. UI PRs build the SPA and run the relevant `pytest -m browser` cases. Mockup frames stay fixture-driven. |
| G4 | After API shape changes, regenerate `docs/openapi.json` and the typed client in the same commit. Core stays free of server and CLI imports, and Import Linter passes. |
| G5 | UI PRs compare against the frames and the interactions document: keyboard, focus, and saving and error states. The app's stylesheets have no dark theme, so compare in light only. |
| G6 | No local e2e. After green CI, run the GitHub e2e workflow (`gh workflow run e2e --ref <branch>`), one run at a time, and record its URL. Never use the live workspace (P2). |
| G7 | Update affected docs (spec, architecture, guides, `CONTEXT.md`) in the PR that owns the change. Record deviations here, under the PR. |
