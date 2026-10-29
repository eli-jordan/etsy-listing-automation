---
name: ingest-mockup-templates
description: Import exported mockup photos into a workspace, or replace an existing template's photos, using the ingestion script.
disable-model-invocation: true
---

# Ingest mockup templates

Use `scripts/ingest_mockup_templates.py` to turn exported base photos and Text
overlays into a colour-matrix photo set. Invoke this skill explicitly with
`$ingest-mockup-templates` or `/ingest-mockup-templates`.

## Resolve the source and destination

Find the requested ZIP or exported directory. For a Downloads request, inspect
the user's Downloads folder, matching scene names and obvious spelling variants.
Compare dates and contents when older exports have similar names. Reuse an
explicit source or workspace from the conversation; otherwise find the workspace
by its `shop.yaml`. The repository is not the user-data workspace. Ask only when
the source, workspace, or replacement target remains ambiguous.

For a new template, follow the workspace's naming convention and the user's scene
name. Use a safe directory slug under `mockup-templates/`. A garment prefix such
as `cc1717-` is appropriate when the existing templates establish it. An existing
destination requires a replacement request or clarification before overwriting.

For replacement, inspect the existing photos and `template.yaml` first. Preserve
the template directory's identity and the current photo filenames. The filename
prefix can differ from the directory name, and configured photo exceptions can
also matter. ADR-0004 explains photo resolution. Renaming a directory can break
garment-profile `preview_template`, listing `media`, and `variation_images` refs;
renaming templates or rewriting those refs is separate work.

## Stage and inspect

Read the script and its `--help` from the current checkout before running it.
Run commands in Cygwin zsh from the repository root. Set `input_path` to the
resolved source and `photo_prefix` to the intended output prefix, then stage the
results outside the destination:

```sh
stage_dir=$(mktemp -d)
uv run python scripts/ingest_mockup_templates.py \
  "$input_path" \
  --output-dir "$(cygpath -w "$stage_dir")" \
  --prefix "$photo_prefix"
```

Windows-native Python needs native paths for general filesystem operations.
Use quoted Windows paths or `cygpath -w`; this script also accepts `/cygdrive/`
paths through its own converter. Cygwin `/c/` paths are not a supported shortcut.

The export pairs `{design} - {colour}.png` with
`{design} - {colour} - Text.png`. The script composites Text over the base,
skips Source Image references, and writes `{prefix}-{colour-slug}.png`.
Missing partners, unequal pair dimensions, or duplicate inputs are refusals.
Report the full failure and leave the destination alone; use a corrected export
for the retry. Copying unpaired photos or inventing overlays requires a separate
user instruction.

Check for output-name collisions before ingestion when an export contains
multiple design groups: different pairs with the same colour can overwrite the
same output filename. After staging, require a nonempty output and reconcile its
filenames and count with the export's valid pairs. The examples had 33 colours;
that is not a requirement for every template. Open a representative composite
to check the scene and overlay, especially when internal export names look stale.

## Install the photos

For a new template, create the resolved destination and copy the verified staged
PNGs there. Verify the installed file set and bytes against staging. The script
does not create `template.yaml`, choose a renderer, calibrate a print area, or
prepare maps. Report that setup as outstanding rather than inventing settings.

For replacement, compare staged and existing filenames and dimensions. Resolve
any ambiguous filename mapping before copying. Back up every photo being replaced
to a uniquely named directory outside `mockup-templates/`, recording its original
relative path. Then copy the intended photos and verify their bytes. Leave
old-only photos in place unless their removal was requested. Preserve
`template.yaml`, `_renderer/`, and any other renderer settings or calibration
files; do not reset them as part of ingestion.

Equal dimensions do not prove equal framing. Report any changed framing or
dimensions and the need to review calibration. Photo changes can invalidate
Marigold preparation and masks, even if saved settings remain present; follow
the calibrator's current readiness and recovery flow rather than claiming that
preserving settings makes a replacement render-ready.

Finish with the source used, installed directory, verified colour count and
filename prefix. For replacement, include the backup path and whether settings
were preserved. State outstanding calibration or preparation work. Clean up only
the staging files created by this run; retain the backup for the user.

## Examples

- `$ingest-mockup-templates ingest woman holding a bag from Downloads into try-workspace`
  creates a new photo set using the workspace's naming convention.
- `$ingest-mockup-templates ingest folded with hat and leaf and replace the existing template's images`
  preserves the existing photo prefix even if it differs from the folder name.
- An export with 11 base photos and no Text overlays is refused. A later corrected
  export can be retried without changing the destination or bypassing pairing.

These workflows come from [Load comfort colors shirt mockup](t3-thread://v1/180d157d-f493-44c2-993d-d0f4e905dff4).
