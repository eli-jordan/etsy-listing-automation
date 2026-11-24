History: v3 of the Backup prototype (Backup as its own top-level Admin section). Superseded by v4 on 2026-11-23.

Built from the agreed [workspace backup spec](../../../../../docs/features/workspace-backup-20261123/spec.md).
Admin gains a third section, Backup, after Shop and Settings, with two subsections: Status and history, and Settings. v1 (static) and v2 (Backup under Settings) are on the archive board.

Every frame mounts one stateful prototype at a different starting point, so all of it clicks in place:
Set up backups → form (tick the password checkbox) → Create runs the first backup → Back up now → Restore… → Restore to this folder → Keep working → Show → Done.
A failing backup puts a banner on every other page and a dot on Admin; Open Backup leads to the page's own warning, and Try again clears both.
The prototype draws its own app shell (see _layout.tsx), because a failing backup changes the shell too.
