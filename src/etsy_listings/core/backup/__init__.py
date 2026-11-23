"""Workspace backup with restic (features/workspace-backup-20261123/spec.md,
ADR-0059).

Public modules, imported directly, with nothing re-exported here:

- ``binary`` -- `ResticBinaries`: which restic to run (the
  ``ETSY_LISTINGS_RESTIC_BINARY`` variable, the ``restic_binary`` setting, or
  the pinned release) and installing that release under ``~/.etsy-listings``.
- ``restic`` -- `Restic`: one repository's commands, streamed as parsed
  ``--json`` lines, with restic's exit codes as typed errors and cancel.
- ``state`` -- `BackupStateStore`: ``backup-state.json`` (last prune and
  check) and the run history ``backup-history.jsonl`` in ``~/.etsy-listings``.

Opening and creating a workspace's configured repository, which joins the
settings, the password and the binary, is
``core.application.backup_repository``'s.

``installation`` is implementation only (download, digest check, unpack),
reached through ``binary`` alone; an Import Linter contract enforces it.
"""
