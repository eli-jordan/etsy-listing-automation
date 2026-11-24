# Restoring a backup

A restore writes one backup of the workspace into a new folder. It never
writes over the live workspace. See the
[workspace-backup spec](../features/workspace-backup-20261123/spec.md),
*Restore*.

## From the app

1. Open **Admin › Settings › Backup**.
2. Choose **Restore…** in the status panel for the newest backup, or
   **Restore…** on a row of the history for that one.
3. Check the folder under **Restore into**. It must be new or empty, and it
   must not be the live workspace.
4. Choose **Restore to this folder**. **Keep working** closes the dialog, and
   the progress stays in the status panel.

When it finishes, either copy the files you need back into the workspace, or
set `ETSY_LISTINGS_ROOT` to the restored folder and restart the app.

**Stop restore**, or closing the app, leaves the files restored so far in the
folder. Delete that folder before restoring into it again.

## From a terminal

```sh
etsy-listings backup snapshots
etsy-listings backup restore latest D:/restored-workspace
```

`restore` takes a snapshot id, the start of one, or `latest`. It refuses the
same folders the app does.

## When the computer is gone

The app is not needed. Install [restic](https://restic.net/) and restore from a
destination, such as the iCloud Drive copy:

```sh
restic -r <destination> restore latest --target <folder>
```

restic asks for the backup password, which is in your password manager. It
writes the backed-up folder under its full original path inside `<folder>`,
for example `<folder>/C/Users/Admin/naturally-inked-studio-workspace`. Set
`ETSY_LISTINGS_ROOT` to that inner folder.

On Windows, restic 0.19.1 then ends with `Fatal: There were 1 errors`: it
cannot set the timestamp of the restored `C\Users` folder. The files are all
restored. To avoid the error, and to get the workspace straight into
`<folder>`, name the backed-up folder after a colon, as the app does:

```sh
restic -r <destination> restore latest:/C/Users/Admin/naturally-inked-studio-workspace --target <folder>
```

A destination that iCloud is still syncing may be missing recent files. Let
the sync finish first, or run `restic -r <destination> check` to see whether
the copy is complete.
