Clickable Backup prototype: Backup nested under Settings, a storage diagram, warnings on every page, and restore with progress. v4, 2026-11-23.

Built from the agreed [workspace backup spec](../../../../../docs/features/workspace-backup-20261123/spec.md).
Settings gains Backup after AI and Template rendering, with two pages nested beneath it: Status and history, and Setup. v1 to v3 are on the archive board.

Every frame mounts one stateful prototype at a different starting point, so all of it clicks in place:
Set up backups → form (tick the password checkbox) → Create runs the first backup → Back up now → Restore… → Restore to this folder → Keep working → Show → Done.
A failing backup puts a banner on every other page and a dot on Admin; Open Backup leads to the page's own warning, and Try again clears both. Frame 12 shows changed or unexpected files in iCloud Drive; Repair sets them aside.
The prototype draws its own app shell (see _layout.tsx), because a failing backup changes the shell too.
