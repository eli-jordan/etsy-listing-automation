# ADR-0060: Group backup retention by workspace ID

Status: accepted. First recorded 2026-11-24.

By default, restic's `forget` applies the retention to each group of snapshots
that share a host and a set of paths. The workspace's snapshots change group
whenever the PC is renamed, the workspace is restored onto another machine, or
its folder moves, as it did when it left iCloud Drive. The old group then never
gains a newer snapshot, so it never ages out. About 15 to 20 snapshots, and the
data only they hold, would be kept forever.

Instead, each workspace gets a **workspace ID**: a random UUID kept in
`settings.yaml` as `backup.workspace_id`. Every backup is tagged
`workspace:<id>`. `forget` runs with `--tag workspace:<id> --group-by tags`, so
it considers only this workspace's snapshots and applies one schedule to them,
whatever host or folder made them. Snapshots from other workspaces, and
untagged ones such as a backup made by hand, are never forgotten by it. `prune`
stays repository-wide. The restore list still shows every snapshot.

**Where the ID lives.** `settings.yaml` travels with the workspace: through a
copy, a move and a restore. A restored workspace therefore keeps its ID, and
its schedule continues. The `backup:` block is the one owner of backup
configuration, and it is written through the settings revision check like the
rest. Setup does not show the ID or let anyone edit it. A separate file was
rejected, because it would be one more file to restore and to keep in step with
the block.

**When it is made.** First-time set-up writes the ID with the rest of the
block. `backup init` and a backup run write one only when a hand-written block
has none. A workspace being set up has backups off, so it has no block and no
ID. It gets a new ID even when set-up connects a destination's existing
backup. The snapshots already in that backup belong to another workspace: they
keep their last schedule and are not adopted.

**Consequences.** Deleting the `backup:` block and setting up again makes a new
ID. The old ID's snapshots then stay until they are removed by hand. Snapshots
made before a workspace had an ID are untagged, and are kept too. All restic
arguments stay behind the `Repository` interface: `back_up` and `forget` take
the workspace ID.

See the [workspace-backup spec](../features/workspace-backup-20261123/spec.md),
*Backup run* step 5, and [ADR-0059](0059-back-up-the-workspace-with-restic-from-the-app.md).
