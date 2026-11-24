# Moving the workspace out of iCloud Drive

A one-off move of the workspace from iCloud Drive to a plain local folder,
with backups from then on (see the
[workspace-backup spec](../features/workspace-backup-20261123/spec.md),
*Migration*). Do it by hand, in one sitting, with the app closed throughout
steps 1 to 4. Allow time for the first backup: it reads the whole workspace,
about 20 GB, and copies it to iCloud Drive.

The commands are for PowerShell on Windows, run from the repository's folder.
Set these three paths first, changing them if your folders differ:

```powershell
$old = "C:\Users\Admin\iCloudDrive\naturally-inked-studio-workspace"
$new = "C:\Users\Admin\naturally-inked-studio-workspace"
$backups = "C:\Users\Admin\naturally-inked-studio-backups"
```

## 1. Stop the app

Close the terminal that runs `etsy-listings ui`, or press Ctrl+C in it. Make
sure no other `etsy-listings` command is running.

## 2. Copy the workspace and check the copy

iCloud only copies files it has downloaded. In File Explorer, right-click the
old workspace folder and choose **Always keep on this device**, then wait
until every file shows a green tick.

Look for conflict copies, which iCloud names `<name> 2.<ext>`:

```powershell
Get-ChildItem -LiteralPath $old -Recurse -File -Force | Where-Object Name -match ' 2(\.|$)'
```

Compare each pair before deciding which version belongs in the new workspace.
Keep both versions in the old workspace. After copying and checking the file
counts, resolve the conflicts in the new folder. For `state.lock.json`, verify
that the version you keep has the listing's current Etsy and Printify IDs.

Copy everything, including hidden folders such as `.cache`:

```powershell
robocopy $old $new /E /COPY:DAT /DCOPY:DAT /R:2 /W:5
```

robocopy's summary at the end must show `0` in the **Failed** column. Then
compare the number of files and their total size. The two lines must match:

```powershell
function Measure-Folder($path) {
  Get-ChildItem -LiteralPath $path -Recurse -File -Force |
    Measure-Object -Property Length -Sum |
    Select-Object @{n = "Files"; e = { $_.Count }}, @{n = "Bytes"; e = { $_.Sum }}
}
Measure-Folder $old
Measure-Folder $new
```

## 3. Point the app at the new folder and add the backup settings

Set `ETSY_LISTINGS_ROOT` for your user, then open a new PowerShell window so it
takes effect, and set the three paths again:

```powershell
[Environment]::SetEnvironmentVariable("ETSY_LISTINGS_ROOT", $new, "User")
```

Add this block to `settings.yaml` in the new workspace:

```yaml
backup:
  repository: C:\Users\Admin\naturally-inked-studio-backups
  destinations:
    - C:\Users\Admin\iCloudDrive\naturally-inked-studio-backups
  interval_hours: 12
```

The backup storage folder must not exist yet, or must be empty. The password
goes into the workspace `.env` as `ETSY_LISTINGS_BACKUP_PASSWORD`. Either add
the line yourself, or let `backup init` ask for it in step 4 and write it.
Keep a copy in your password manager: the `.env` inside each backup is
encrypted with that same password.

## 4. Create the repository and make the first backup

While iCloud Drive is connected and syncing, create the empty destination
folder named in `backup.destinations`. The CLI skips a missing destination.
If that path already holds a backup, keep it: `init` connects to it instead
of creating a new repository. It uses the password in `.env`, or asks for
that backup's password, then copies the
backup into `$backups`, and prints `Connected to the backup in <folder>: N
snapshots`. The `run` that follows adds to it.

```powershell
uv run etsy-listings backup init
uv run etsy-listings backup run
uv run etsy-listings backup status
```

`init` downloads the pinned restic the first time. `run` backs up the whole
workspace, then copies the repository into iCloud Drive: it must end with
`Copied to C:\Users\Admin\iCloudDrive\naturally-inked-studio-backups.` and
no `Not copied` line. `status` must then show `Reachable: 1 snapshots`.

## 5. Start the app and check the workspace

```powershell
uv run etsy-listings ui
```

Check that:

- Listings shows each listing in its real state, with its Etsy ID where it has
  one: live listings read as live, not as drafts.
- Batches lists every batch.
- **Admin › Settings › Backup** says it backed up a few minutes ago, with no
  warning.

If something is wrong, stop the app, point `ETSY_LISTINGS_ROOT` back at `$old`,
and start it again. The old folder is untouched until step 6.

## 6. Retire the old folder

```powershell
Rename-Item -LiteralPath $old -NewName "naturally-inked-studio-workspace-old-2026-11"
```

After two weeks of successful backups (Backup's history shows them), delete the
renamed folder.

## Later: a new computer

Copy or let iCloud download the destination folder
(`naturally-inked-studio-backups` in iCloud Drive) and restore the workspace
from it, as [restoring a backup](restore-a-backup.md) describes under *When the
computer is gone*. Then open **Admin › Settings › Backup**. If backups are off there, choose
**Set up backups** and name the iCloud Drive folder as a destination, with
that backup's password: set-up connects it instead of creating a new
repository, and says so. Otherwise it reports
`Backup repository not found` because the old computer's backup storage
folder is not there. Choose **Connect an existing repository**, name the
iCloud Drive folder under **Copy from**, and a local folder under **Copy
into**. The app copies the repository to this computer, checks the password
opens it, and carries on backing up from there. **Create a new repository**
starts again with an empty repository instead.
