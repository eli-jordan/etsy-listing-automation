"""Workspace backup with restic (ADR-0060): which restic runs, one
repository's operations, the one-way copy to destination folders, and this
machine's backup records.

Nothing is re-exported; import the public modules directly. Withheld, each by
an Import Linter contract: ``installation``, reached through ``binary`` alone,
and ``restic``, the real ``Repository``, reached through
``core.application.backup_repository`` alone, which also opens a workspace's
configured repository.
"""
