# Etsy listing automation

This tool turns a print-on-demand design into a reviewable Etsy draft by way of
Printify. These are the terms the code and its reviews use for the seller's
workspace.

## Language

**Listing**:
One product for sale. Its identity is its directory name under `listings/`.
_Avoid_: product (Printify's word for the remote copy), item

**Listing document**:
A listing's `listing.yaml`, as written. It is edited only by reading it,
changing it and writing it back, all under the listing's lock.
_Avoid_: listing config, listing file

**Settled**:
What a save reports when the editor has stopped writing: no write is out, and
either the file holds every edit made before it was asked or an edit is still
held, with the reason. An edit is held until it is written, and is only ever
sent again by the next edit or flush.
_Avoid_: flushed, done (neither says whether the file holds the edit)

**Template position**:
A listing's own position for artwork on one mockup template, or one placement
within a template showing several garments. It changes the mockup only.
_Avoid_: print placement, template calibration, per-colour position

**Template state**:
What a mockup template's saved files amount to: absent (no `template.yaml` yet),
unreadable (one that will not load), needs repair (a calibration transaction
stands in the way) or loaded.
_Avoid_: calibration status, which the rail derives from a loaded config

**Label**:
Free-form text a seller tags a mockup template with, for finding it, such as
`shot:flat lay`. The text before a colon is its group. A label exists only while
a template holds it, and it never changes a render.
_Avoid_: tag, category

**Listing artifacts**:
Everything in the workspace keyed by a listing's name: its directory, render
cache, previews, market snapshot and cached proposal. They are moved and
removed together.
_Avoid_: listing files, caches (which names only some of them)

**Free name**:
A listing name that no directory under `listings/` holds. A directory holding
only a lockfile is not a listing, but its name is not free.
_Avoid_: available name, unused name

**Backup storage folder**:
The local restic repository the app backs the workspace up into, named by
`backup.repository`. The app never creates one by itself: one that is missing
stops backups until the seller creates or connects one.
_Avoid_: backup folder, repository (restic's word, and the code's)

**Destination**:
A folder the backup storage folder is copied to one way after each backup, such
as a folder in iCloud Drive. Each is a complete restic repository by itself.
The app creates one only at set-up or when Setup adds it. A destination the app
cannot reach is skipped and caught up later.
_Avoid_: mirror, sync target, remote

**Configured backup**:
The `backup:` block resolved on this machine for one backup operation: the
workspace, the backup storage folder, the destinations, the password and the
restic binary. It is resolved once per operation, and it is refused if any two
of those folders overlap. It decides which folders may be a new backup storage
folder or a restore target. It runs nothing itself.
_Avoid_: backup config, backup settings (the `backup:` block as written)

**Workspace ID**:
A random UUID in `backup.workspace_id` that names one workspace across
machines, hosts and folders. Every snapshot is tagged with it, and the
retention keeps and groups this workspace's snapshots by it alone. Set-up
writes it once, taking the one its repository's snapshots already carry when
there is exactly one; it travels with `settings.yaml`, so a restored workspace
keeps it, and it is never changed. The seller never edits it.
_Avoid_: host, machine ID, repository ID (restic's id for the repository)

**Restore target**:
The new or empty folder a snapshot is restored into, never the live workspace,
the backup storage folder, a destination or a folder inside one. It is checked
when the restore is asked for and again just before restic writes, against the
settings as they read then. Files already in it are never overwritten.
_Avoid_: restore destination (a destination is where backups are copied)

**Set-aside folder**:
The new folder beside a destination that a repair moves its changed and
unexpected files into: `<destination>-set-aside-<date>`, then `-2`, `-3`... when
that name is taken. The server names it, before the repair as well as after.
_Avoid_: quarantine, backup of the backup

**Stale**:
A revision-checked write refused because the file changed since the page read
it. Nothing was written; the page reloads before trying again. Every other
refusal is **refused**, with the server's reason and the fields it names.
_Avoid_: conflict (the server's word for a folder that holds files)
