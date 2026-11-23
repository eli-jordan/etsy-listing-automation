# ADR-0059: Back up the workspace with restic from the app

Status: accepted. First recorded 2026-11-23.

The workspace no longer lives in a sync folder. In November 2026, iCloud Drive
for Windows renamed lockfiles that the app had replaced (temp file, then rename)
while their earlier versions were still waiting to upload. A live listing then
read as a draft. Atomic replacement is correct for local disks, so the fix is
to keep sync clients away from files the app writes. The workspace lives on
local disk, and a backup brings the data to the cloud.

**Why restic.**
- Repeated full zips would store and upload about 20 GB every 12 hours, even
  though the images rarely change. restic deduplicates, encrypts, and keeps the
  agreed retention (everything for 7 days, then weekly, then monthly) with no
  code of ours.
- restic writes each repository file once, under a name derived from its
  content, and never changes it afterwards. kopia was rejected because it
  rewrites fixed-name files, such as `kopia.maintenance`, by renaming a new
  file over the old one. That is the pattern iCloud already mangled.
- Hard-link snapshots in the style of Time Machine save no space in a sync
  folder, and they produce thousands of small files.

**Why the repository stays on local disk.** Users who kept restic repositories
in Box Drive and Dropbox folders report conflicted copies and missing packs.
Pruning, which deletes and rewrites many files, carries most of the risk. The
app therefore backs up and prunes locally, then copies the repository one way
into each destination. The copy only ever adds files under names that did not
exist, or deletes them. Nothing at a destination is replaced, so a sync client
never has two versions of one name to reconcile.

**Why it runs inside the app.** Starting from the server lifespan works the same
on Windows and Linux, without Task Scheduler or cron. It also lets the backup
pause the server's background jobs for a consistent snapshot. Nothing runs while
the app is closed, but nothing changes then either. CLI runs are not coordinated.
Volume Shadow Copy (VSS) was rejected because it needs elevation and exists
only on Windows.

The [specification](../features/workspace-backup-20261123/spec.md) owns the run
sequence, the copy rules, retention, warnings and the migration.
