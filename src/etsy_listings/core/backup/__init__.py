"""Workspace backup with restic (features/workspace-backup-20261123/spec.md,
ADR-0059).

Public modules, imported directly, with nothing re-exported here:

- ``binary`` -- `ResticBinaries`: which restic to run (the
  ``ETSY_LISTINGS_RESTIC_BINARY`` variable, the ``restic_binary`` setting, or
  the pinned release) and installing that release under ``~/.etsy-listings``.
- ``repository`` -- `Repository`: one restic repository's operations in the
  backup's terms (init, snapshots, back up, forget, prune, check, restore,
  verify the password), their figures and summaries, and restic's outcomes
  as typed errors. The seam the application modules use.
- ``destinations`` -- copying the repository one way to a destination
  folder, the monthly sample check and repair, with plain file operations
  and no restic.
- ``state`` -- `BackupStateStore`: ``backup-state.json`` (last prune and
  check) and the run history ``backup-history.jsonl`` in ``~/.etsy-listings``.

Opening and creating a workspace's configured repository, which joins the
settings, the password and the binary, is
``core.application.backup_repository``'s.

Implementation only, each enforced by an Import Linter contract:

- ``installation`` (download, digest check, unpack), reached through
  ``binary`` alone.
- ``restic`` -- `Restic`, the real `Repository`: argv, ``--json`` lines,
  exit codes, cancel and the process group. Reached through
  ``core.application.backup_repository`` alone.
"""
