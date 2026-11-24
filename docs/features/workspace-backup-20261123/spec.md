# Workspace backup

Status: agreed in a design interview on 2026-11-23, with the UI approved the
same day. Implemented as a stacked PR series ([plan](plan.md)), awaiting
merge; the seller then migrates by hand with the
[migration guide](../../guides/migrate-the-workspace-out-of-icloud.md). This
specification owns the requirements under the
[documentation authority rules](../../README.md#documentation-authority).
[ADR-0060](../../adr/0060-back-up-the-workspace-with-restic-from-the-app.md)
records why the design uses restic, runs inside the app and keeps the
repository on local disk. The [interactions document](interactions.md) covers
the UI and the [plan](plan.md) the delivery.

## Outcome

The workspace moves out of iCloud Drive to a plain local folder. The app backs
it up every 12 hours into a deduplicated, encrypted restic repository on local
disk. It then copies that repository one way into one or more destination
folders, starting with a folder in iCloud Drive. Storage and uploads grow only
with what changes, not with the size of the workspace.

Background: in November 2026 iCloud Drive for Windows renamed files the app had
just replaced (`state.lock.json` became `state.lock 2.json`), because their
earlier versions were still waiting to upload. A listing that was live on Etsy
then read as a draft with no Etsy ID. A workspace no sync service writes to
cannot be damaged that way.

## Scope and decisions

| Area | Agreed behaviour |
| --- | --- |
| Workspace location | `C:\Users\Admin\naturally-inked-studio-workspace` on the current PC, selected through `ETSY_LISTINGS_ROOT`. No sync service watches it. |
| Contents | The whole workspace, including `.cache`. Only temporary files are left out (see *Backup run*). |
| Tool | restic, called as a subprocess with `--json` output. |
| restic binary | The app downloads one pinned release for the OS, checks it against a SHA-256 checksum stored in the code, and keeps it under `~/.etsy-listings/restic/`. A setting can name another binary instead. |
| Repository | A local restic repository, for example `C:\Users\Admin\naturally-inked-studio-backups`. The UI calls it the **backup storage folder**. |
| Destinations | An ordered list of folders the repository is copied to. One at first: a folder in iCloud Drive. A NAS can be added later without a redesign. |
| Scheduling | A job inside the server. A backup is due `interval_hours` after the last successful one: 12 by default, and the UI offers 4, 6, 12, 24 or 48. The server checks on start-up, so an overdue backup runs straight away. No OS scheduler is involved. Nothing runs while the app is closed. |
| Manual run | A "Back up now" action in the UI and a `backup run` CLI command. |
| Consistency | Pause the server's background jobs for the whole `restic backup` step. Jobs submitted meanwhile are queued, not refused. |
| Retention | Every snapshot from the last 7 days, the latest snapshot of each of the last 4 weeks, and the latest of each of the last 3 months. |
| Pruning | `forget` after every backup. `prune` once a week. |
| Verification | A weekly `check` of the local repository. A monthly check of each destination that hashes a 5% sample of its files, without restic. |
| Failures | Shown as a warning in the UI: on the Backup page, and as a banner on every other page with a dot on Admin. No OS notifications. |
| Restore | Pick a snapshot in the UI and restore it into a new folder, never over the live workspace. Progress shows while it runs, and the seller can keep working. |
| UI | Backup under Admin › Settings, after AI and Template rendering, with two pages nested beneath it: *Status and history* and *Setup*. |
| Configuration | A `backup:` block in the workspace `settings.yaml`. The password goes in the workspace `.env`. |
| Platforms | Windows now and Linux later, with the same code path. |

## Configuration

`settings.yaml` gains an optional `backup:` block. When the block is absent,
backups are off and the UI says so.

```yaml
backup:
  repository: C:\Users\Admin\naturally-inked-studio-backups
  destinations:
    - C:\Users\Admin\iCloudDrive\naturally-inked-studio-backups
  interval_hours: 12
  retention:
    keep_within_days: 7
    weekly: 4
    monthly: 3
  # restic_binary: /usr/bin/restic   # optional: use this instead of the pinned download
```

The repository password is the `.env` key `ETSY_LISTINGS_BACKUP_PASSWORD`. The
app passes it to restic only in that subprocess's environment, as
`RESTIC_PASSWORD`, never on the command line or in a log. The seller keeps a
copy in a password manager, because the `.env` inside a backup is encrypted with
that same password.

`backup.workspace_id` is the **workspace ID**, a random UUID. Set-up writes
it, and `backup init` or the first run write one when a hand-written block
has none. Setup does not show it. Because it is in `settings.yaml`, a copied,
moved or restored workspace keeps it, and an ID already there is never
changed.

A workspace without one takes the ID its repository's snapshots already
carry, so their schedule carries on: after set-up connects a destination's
backup, after `backup init` connects one, and on the first run after
Create or Connect a new repository. The snapshots are read without restic's
lock, and untagged ones, from before workspace IDs, are not counted. With no
tagged snapshots it is a new ID. With snapshots of several workspaces it is
a new ID too, and set-up, `backup init` and the run's history say: "This
backup holds snapshots from more than one workspace, so this workspace
starts its own retention."

The paths are specific to one machine, yet `settings.yaml` travels with the
workspace when it is restored somewhere else. See *Missing repository* for how
the app treats stale paths.

## Set-up

Set-up, from the Backup page or `backup init`, first looks in each
destination. If none holds a restic repository, it creates a new one in the
backup storage folder, as before.

If a destination already holds a backup, set-up connects it instead of
creating one. A typical case is a new computer whose iCloud Drive already
holds the backups. Connecting works as *Connect an existing repository*
does: the copy is copied one way into a staging folder beside the backup
storage folder, the password must open it and `restic check` must pass, and
only then does it take the storage folder's name. The settings and the
password are saved after that. The next scheduled backup adds to the
connected repository, and its first copy back finds every file the
destination already has, so nothing there is replaced or deleted.

Several destinations may hold copies of the same repository, with the same
`config`. Set-up connects the first one that holds every file the others
hold and passes the check, and says which. A copy that is still syncing is
never the one connected: the copy back would delete what it lacks from the
fuller copies.

Set-up refuses, and writes nothing, when:
- the password does not open the destination's backup (the error is on the
  password field);
- a destination holds restic's folders but no `config`, as a sync client
  that is still downloading leaves it;
- two destinations hold different repositories;
- two copies of the same repository each lack files the other has;
- the backup storage folder is not new or empty.

A new repository needs a password of at least 12 characters. An existing one
only needs the password it was made with.

## Backup run

One run, from the scheduler or from "Back up now":

1. **Wait for quiet.** Wait until no deploy run (plan or apply), AI run, AI
   batch-queue dispatch, Prepare job or scene-warming pass is in progress.
2. **Pause.** Stop those runners from starting new work. A submission during
   the pause is accepted, held, and reported as `waiting for backup`.
3. **Back up.** Run `restic backup` on the live workspace root, tagged
   `workspace:<id>` with the workspace ID (*Configuration*). Leave out the
   temporary names the app's own writers use: `*.tmp`, plus the patterns
   `core/workspace/atomic.py` and the other temp-then-rename writers create.
4. **Resume.** Release held jobs in the order they were submitted. Jobs resume
   whether the backup succeeded or failed.
5. **Forget.** Apply the retention with `restic forget`. restic counts the
   current week and month as one of each, so 4 past weeks and 3 past months
   become `--keep-within 7d --keep-weekly 5 --keep-monthly 4`. It runs with
   `--tag workspace:<id> --group-by tags`: only this workspace's snapshots,
   as one group, whatever host or folder made them, so the old ones age out
   after the PC is renamed or the workspace moves (ADR-0061). Other
   workspaces' snapshots and untagged ones, such as a backup made by hand,
   are never forgotten. `prune` is repository-wide.
6. **Weekly.** If 7 days have passed since the last prune, run `restic prune`,
   then `restic check` on the local repository.
7. **Copy** the repository to each destination (see *Copy to destinations*).
8. **Monthly.** If 30 days have passed since a destination was last checked,
   check it by reading a 5% sample of its files (see *Checking a
   destination*).

Steps 5 to 8 run after the jobs resume. restic's own repository lock keeps
two runs from overlapping.

Edits made in the editor, batch creation, calibration saves and other request
handlers are **not** paused. Neither is a `plan` or `apply` started from the
CLI in another process. A snapshot therefore reflects a single moment for
background jobs only.
- **An edit that replaces one file** (temp file, then rename) appears in the
  snapshot either before or after the edit, never half written.
- **Writes that change several files** can appear half done, such as
  confirming a batch or committing a calibration.
- **A few writers rewrite files in place**, so the snapshot may hold a partly
  written copy. They are the Printify catalog cache, Prepare work files,
  re-uploaded test designs and the derived `.npy` maps. Converting them to
  temp-then-rename is optional hardening and not required by this spec.

## Pausing jobs

The three coordinators the server lifespan starts can stop today but cannot
resume (`server/api/app.py`): `Deployments`, `AiCoordinator` with its batch
queue, and `Preparations`, along with the scene warmer. Backup needs a shared
gate that each coordinator checks before it starts work:

- `wait_idle()`: returns when no run is queued or in flight in any coordinator.
- `pause()` and `resume()`: while paused, submissions are accepted and held.
  Each held item reports a `waiting_for_backup` state the UI can show.
- `stop()` at shutdown still overrides everything. Shutdown during a pause ends
  the backup and drops held submissions, as it drops queued ones today.

`wait_idle` has no timeout. Each 10 minutes it is still waiting, the backup
status says the backup is waiting for a named job.

## Copy to destinations

Each destination ends up a complete restic repository that `restic -r <dest>`
can open by itself. The copy never replaces or edits an existing file.

1. **List the local repository in restic's read order**: `snapshots/`, then
   `index/`, then `data/`, then `keys/` and `config`. Do this once, before
   copying anything. Skip `locks/` and restic's temporary names (`*-tmp-*`).
   restic's design document says reading follows the reverse of writing.
   Listing in that order means every pack that a listed snapshot or index
   needs was already on disk when `data/` was listed, even if a restic command
   from the CLI was writing at the same time.
2. **List the destination** the same way, and sort each of its files into one
   of these groups:
   - *Present*: the name and size match a local file.
   - *Changed*: the name matches a local file but the size differs. For
     `config`, any difference in its bytes counts.
   - *Expired*: a valid restic name that the local repository no longer has.
     The weekly forget and prune produce these.
   - *Unexpected*: a name restic would never write, other than the copy's own
     temporary names. An iCloud conflict copy such as `a3f9…e1 2` is the
     likely case.
3. **Changed files stop the copy** to that destination and raise a warning
   (see *Changed and unexpected files*). Nothing more is written there until
   the seller repairs it.
4. **Copy what the destination lacks**, in write order: `config` and `keys/`,
   then `data/`, then `index/`, then `snapshots/`. Write each file under a
   temporary name in its target folder, flush it, then rename it to its final
   name. Hash each file as it streams. Every name except `config` is the
   SHA-256 of the file's contents, so a mismatch means the local file is
   damaged. That stops the copy and raises the same warning as a failed check.
5. **Delete expired files** in the reverse of the copy order: `snapshots/`,
   then `index/`, then `data/`. restic's rule is that a pack is removed from
   the index that names it before the pack itself is deleted. Never delete an
   unexpected file.
6. **Delete the copy's own temporary files** that an interrupted copy left
   behind.

If a concurrent prune deletes a listed pack before it is copied, the copy of
that destination fails, says so, and catches up on the next run.

The order guarantee holds for the destination folder on this computer. A sync
client such as iCloud for Windows uploads in its own order, so the cloud's copy
can briefly hold a snapshot whose packs are still uploading. It is complete
once the client finishes, and older snapshots stay readable meanwhile.

### Changed and unexpected files

restic never changes a file after writing it, so a changed or unexpected file
in a destination means something else wrote there: the sync client, another
program, or a person. The app reports it and never overwrites it.

- **Changed files** raise a warning naming each file with its expected and
  actual size, and stop copying to that destination (step 3).
- **Unexpected files** raise a warning naming each file. Copying continues,
  because adding new files cannot make them worse.
- **Content changes that keep the size** are caught by the monthly check (see
  *Checking a destination*).

Both warnings follow *Status and warnings*: on the Backup page, with a banner
on every other page. The Backup page offers **Repair the iCloud Drive copy**
(the destination's name). After the seller confirms, it moves the changed and
unexpected files to a sibling folder named `<destination>-set-aside-<date>`,
deleting nothing, then runs the copy again. The destination is then whole and
the seller can inspect what was set aside.

### Checking a destination

The monthly check of a destination does not run restic against it. The app
reads a random 5% of the destination's files and checks each file's SHA-256
against its name, and checks `config` against the local copy byte for byte.
Any mismatch is a changed file. This writes nothing to the destination, not
even a restic lock, and it needs no password. The destination's structure is
the local repository's, which the weekly `restic check` already covers. If
iCloud has evicted the sampled files, reading them downloads them.

This holds through `prune`. restic's design document says every repository
file is "only written once and never modified afterwards". It names each file
after the SHA-256 hash of its contents. The one exception is `config`, which is
written once by `init`. A prune that repacks writes new pack files, adds a new
index, deletes the old index, and only then deletes the old packs. The next
copy sees that as new files to add, then old files to delete. The only cost is
upload size: the week's prune can send repacked data, up to roughly the unused
share `--max-unused` allows (5% of the repository by default). If `config`
ever changed (`restic migrate` rewrites it), step 2 would report it as changed
rather than overwrite it.

If a destination is unreachable (the folder is missing, or the drive or share
is offline), skip it and report it. The local backup counts as successful. The
next run catches the destination up.

The copy is plain Python file operations, so a NAS mounted as a folder works
unchanged. A later NAS destination may instead use restic's `rest-server` with
`restic copy`. That would be a second destination type, outside this spec.

## Status and warnings

Machine-local state, such as each destination's last successful copy and the
last prune and check times, lives in `~/.etsy-listings/backup-state.json`,
outside the workspace. Each run's outcome, including failed runs that made no
snapshot, is appended to a run history beside it. The time of the last
successful backup comes from `restic snapshots --json`, not from these files.

The UI shows:
- the last successful backup and when the next one is due
- whether a backup is running, waiting for jobs to finish, or has jobs paused
- each destination's last successful copy and its last check

The page also draws the data's path as three boxes: workspace, backup storage
folder, then each destination, with the backup and copy steps between them.

It shows a warning when:
- the last successful backup is more than 24 hours old
- the last backup or check failed (with restic's message)
- a destination is more than 24 hours behind the local repository
- a destination holds changed or unexpected files
- backups are switched off, or the repository is missing

A warning shows on the Backup page. Every warning except *switched off* also
puts a dot on the Admin link in the app sidebar and a one-line banner with an
*Open Backup* button at the top of every other page. Both stay until the
problem clears. There is no dismiss, because this feature exists to stop
backups from failing unnoticed.

## Missing repository

The app never creates a repository by itself. If `backup.repository` does not
exist or is not a restic repository, backups stop. The UI says `Backup
repository not found at <path>` and offers two actions:
- **Create a new repository** at a path the seller confirms.
- **Connect an existing repository**, for example a destination copy restored
  onto a new machine. Connecting copies that repository to local disk first,
  so the destination stays a one-way copy.

Both take a local folder that is new or empty, prefilled with
`backup.repository`, and save it there when it differs. The password in `.env`
is used when there is one; otherwise the seller gives it. Connect saves
nothing until restic has opened the local copy with that password. Create is
refused while a destination already holds a repository's copy, and offers
Connect with that folder instead (first-time set-up connects it by itself,
see *Set-up*), because a new repository would lead a repair
and the next copy to delete the old backups there. For the same reason, Repair
refuses a destination whose `config` differs from the local one.

## Restore

The UI lists the snapshots with their time, size and the files that changed. A
restore writes the chosen snapshot into a new folder the seller names, and
refuses an existing non-empty folder or the live workspace. The seller then
points `ETSY_LISTINGS_ROOT` at the restored folder or copies files back by hand.

A whole-workspace restore reads about 20 GB from local disk and takes minutes,
so it runs as a server job, one at a time:
- Progress comes from the `restic restore --json` status lines: percent done,
  and bytes and files restored out of the total. The app estimates the time
  left from the rate so far.
- The restore dialog shows that progress. *Keep working* closes the dialog and
  moves the progress to the Backup page's status panel, where *Show* reopens
  it. When the restore ends, the panel says where the files are.
- Scheduled backups keep running during a restore, because backup and restore
  both take shared restic locks. A weekly prune waits until the restore ends.
- *Stop restore* ends the job and leaves the files restored so far in the
  folder. The seller deletes them before restoring there again. Closing the
  app stops a restore the same way.

The disaster case, when the PC is gone, needs no app. The guide documents the
command `restic -r <destination> restore latest --target <folder>`. The UI
restores whole snapshots only. It does not restore single files.

## CLI

`etsy-listings backup` with these subcommands: `init` (create a repository,
or connect the one a destination already holds and print which),
`run`, `status`, `snapshots`, `restore <snapshot> <target>`, and `check`.
The CLI does not coordinate with a running server. `run` is meant for when the
app is stopped, which is the case during the migration. restic's repository
lock still keeps two processes from using the repository at the same time.

## Migration

A one-off procedure, written up in the
[migration guide](../../guides/migrate-the-workspace-out-of-icloud.md):

1. Stop the app.
2. Copy the workspace from iCloud Drive to the local folder, and check the
   number of files and their total size.
3. Point `ETSY_LISTINGS_ROOT` at the local folder. Add the `backup:` block and
   the password.
4. Run `backup init`, then `backup run`. This first backup is the full 20 GB
   and includes the first copy to iCloud.
5. Start the app. Check that listings show their real states and the batches
   page lists every batch.
6. Rename the old iCloud folder to
   `naturally-inked-studio-workspace-old-2026-11`. After two weeks of
   successful backups, delete it.

## Open questions

- **The restic version and its checksum.** Pin a release at least two weeks old
  when this is implemented.

The [interactions document](interactions.md) owns the Backup section's UI
behaviour, and the [implementation plan](plan.md) owns the delivery order.
