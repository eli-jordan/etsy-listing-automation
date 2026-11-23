### How step 2, Copy, works

The backup storage folder is a restic repository. A backup never rewrites its files. It only **adds new ones**, each named after a hash of its contents:

- `data/` holds encrypted pack files of about 16 MB each.
- `index/` and `snapshots/` hold small files.

After each backup the app compares the two folders and copies only the files the destination lacks. Usually that is a handful of new packs, tens of MB.

```mermaid
flowchart LR
  W[Workspace] -->|restic backup| R[Backup storage folder]
  R -->|copy new files| I[iCloud Drive folder]
  I -->|iCloud for Windows| C((iCloud))
```

- Each file is written under a temporary name and then renamed into place. A file that already exists is never replaced, so iCloud never sees a conflict and never makes a "name 2" copy.
- Order: `data`, then `index`, then `snapshots`. A destination never lists a backup before its data has arrived.
- After a weekly clean-up, the app deletes the files the storage folder no longer has.
- iCloud for Windows uploads the new files on its own schedule. The app only writes to the local iCloud Drive folder.

The destination ends up a complete repository. If this PC is lost, `restic -r <iCloud folder> restore latest` works on any computer.
