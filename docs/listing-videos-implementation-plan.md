# Listing videos implementation plan

**Status:** proposed. Builds [PRD 71 and 72](prd.md) and
[phase-3-etsy.md decision 9](phase-3-etsy.md#9-videos-are-placed-by-attach-order--prd-71).
Like the other implementation plans, it is not an authority: where it disagrees
with those, they win and this document is wrong.

## Outcome

A listing's `media:` is its Etsy gallery, videos included. A seller can add up
to two `.mp4`/`.mov` files, taken from `common-media/` or from the listing's own
directory, and put them where they want: the featured video at position 2 and
the second anywhere after it. `plan` explains what will change and refuses a
video Etsy's help page would reject. `apply` uploads new bytes, re-attaches by
id when only the layout changed, and puts the swatches back after placing the
second video. Every path in `listing.yaml` uses two roots: no prefix for the
workspace root, and `./` for the listing's own directory.

The UI changes are small and reuse the approved prototype: `<video>` tiles
inline in the one reel, slot 2 labelled Featured, and a single file list
grouped *This listing* / *Shared*. There is no separate design pass.

## Settled decisions this plan builds

| Topic | Decision | Source |
|---|---|---|
| Where videos live | Entries in `media:`, which is the gallery in order. Position 1 is an image. Any video puts one at position 2. At most 2 videos and 20 images | PRD 71 |
| Refs | No prefix is the workspace root and `./` is the listing directory. Subdirectories are allowed and `..` is refused. Covers `design:`, `pricing_plan:` and `media:` | PRD 72 |
| Migration | `scripts/migrate_workspace_refs.py`, then `../` is refused and the error names the script. Shared images re-upload once | PRD 72 |
| File types | Images `.png`, `.jpg`, `.jpeg`. Videos `.mp4`, `.mov` | PRD 71 |
| Video gate | Block anything that is over 100 MB, outside 3–15 s, has a shorter side under 500 px, or has no decodable video stream. No aspect rule. Audio produces a note, not a warning | PRD 71 |
| Probe library | PyAV, pinned `av>=15`. It only reads metadata and never produces bytes that get hashed, so a floor pin is enough | grilling |
| Stage | `etsy_videos`, after `etsy_media`, with its own applied model and `remote.etsy_video_ids`, displayed under "Etsy media" | PRD 71 |
| Placement | Sweep foreign videos → attach the featured one → cut `image_ids`, attach the second, restore → re-assert swatches | decision 9 |
| Drift | One of ours missing or `inactive` is re-uploaded. Hand-made position changes are invisible and accepted | PRD 71 |
| Daily budget | Not predicted. The client rewords Etsy's `400` into the per-listing daily limit | PRD 71 |

## PR sequence

Every PR targets the PR before it, stays under **3,000 changed lines** (insertions plus
deletions in `git diff --shortstat <base>...HEAD`, generated `docs/openapi.json`
and `src/api/schema.ts` included), and leaves the suite green on its own.

```
PR 1 refs ─► PR 2 media kinds + gate ─► PR 3 Etsy client ─► PR 4 stage ─► PR 5 API + locator ─► PR 6 reel + review
```

The stack is based on `t3code/support-listing-videos`, which carries the
documentation (PRD 71/72, decision 9 and this plan). PR 1 targets that branch
and each later PR targets the one before it.

### Definition of done — every PR

A PR is done only when all of these hold. The PR-specific conditions below are
added to this list, not substituted for it.

1. **Local suite green.** `./scripts/check.sh` exits 0. It covers ruff
   format/check, mypy strict, the full non-e2e pytest run, and the frontend's
   prettier/eslint/tsc/vitest.
2. **Coverage gates met.** The same script enforces **≥85% branch coverage**
   for Python (`fail_under`) and for the frontend (`npm run test:coverage`).
   The threshold is not lowered and no `# pragma: no cover` is added.
3. **Browser layer green locally.** `uv run pytest -m browser` passes, not
   skipped. That needs `uv run playwright install chromium` and a built
   `ui/frontend/dist`.
4. **PR created with green checks.** Opened with `gh pr create`, registered
   with this thread's `link_pull_request`, and every CI check on the PR is
   green: ruff, mypy and `pytest -m "not browser"` on **ubuntu and windows**,
   plus the frontend gate.
5. **e2e green on the branch.** Triggered with
   `gh workflow run e2e --ref <branch>`, watched with `gh run watch`, and the
   run URL pasted into the PR description. If it fails because
   `ETSY_TOKENS_JSON` is stale, run `etsy-listings auth etsy` locally, update
   the secret and re-run; that failure is not treated as a pass.
6. **Size.** `git diff --shortstat <base>...HEAD` totals under 3,000 lines. The
   number goes in the PR description.
7. **Decisions cited.** Commit messages and any code comment where a choice
   would look arbitrary cite PRD 71/72 or decision 9.

Local environment note (macOS behind the corporate proxy):
`UV_NATIVE_TLS=1 uv sync --python /opt/homebrew/bin/python3.13`, and
`SSL_CERT_FILE` pointing at a bundle containing the proxy's root for anything
that talks to Etsy or Printify.

---

### PR 1 — `feat(workspace): two-root refs for every listing path`

**Target: about 2,300 lines**, mostly fixture and test churn.

1. `Workspace.resolve_ref(ref, listing)` is the single interpreter:
   - no prefix → the root
   - `./` → the listing directory
   - subdirectories allowed on both
   - `..`, absolute paths and backslashes refused with a `ConfigLoadError`
   - it still goes through `resolve()`'s escape check (A8)

   A ref starting `../` is refused with a message naming
   `scripts/migrate_workspace_refs.py`.
2. Route every caller through it, replacing each
   `resolve(..., relative_to=listing_dir)`:
   - `placement.py`, `printify_product.py` (the pricing plan) and `etsy_media.py`
   - `ui/api/listings.py` (design paths, pricing plan) and `ui/api/seo.py`
   - `workspace.py`'s own design listing
3. Writers emit the new form:
   - `newcmd/interactive.py` writes `designs/{name}.png`, and the pricing plan
     it writes follows suit
   - `CommonMediaSummary.ref` becomes `common-media/x.png`
   - the frontend's `DesignSelect` stops prepending `../../`
4. `scripts/migrate_workspace_refs.py <workspace>`:
   - enumerates every `listings/*/listing.yaml` and prints the exact rewrites
     before touching anything
   - rewrites `design`, `pricing_plan` and file entries in `media` from
     `../../x` to `x` by editing those scalar values in the text, not by a
     YAML round trip. PyYAML is the only YAML dependency and would drop
     comments; a text edit keeps key order and comments without adding
     ruamel. The result is re-parsed and validated before an atomic
     `os.replace`
   - is idempotent
   - leaves the lockfile untouched (PRD 72's accepted re-upload)
5. Convert every tracked fixture (`tests/fixtures/workspace/...`), plus the
   Python and frontend tests that spell `../../`. Import paths are not affected.
6. Update `getting-started.md`, `multi-placement-rendering.md` and
   `phase-5-listings-ui.md`'s examples.
7. Run the script on `~/try-workspace` only after its dry-run output has been
   shown and confirmed. No other workspace is touched.

**Success conditions (added to the common list):**
- Unit tests for `resolve_ref` cover:
  - root and `./` resolution, including a nested `./shots/back.png`
  - `..` anywhere, `../../legacy` (the error must name the script), absolute
    paths, backslashes, and an empty ref
- Unit tests for the migration script cover: a rewrite, a second run that
  changes nothing, a file with nothing to migrate, and comments preserved.
- After migrating a copy of the fixture workspace, `plan` reports
  `render`, `printify_product` and `publish` unchanged, and `etsy_media`
  reports only the renamed shared refs. This is PRD 72's cost claim, pinned by
  a behaviour test.
- `grep -rn '\.\./\.\./' tests src --include='*.py' --include='*.ts*'` finds
  no listing refs; import paths are excluded.
- `~/try-workspace` has been migrated with the dry run confirmed, and a `plan`
  against it succeeds.

### PR 2 — `feat(config): media kinds, gallery rules and the video gate`

**Target: about 2,200 lines.** Everything local. No Etsy call.

1. `MediaEntry` classification, as a pure function in `config/media.py`:
   - a template entry is an image
   - a file ref is `image` or `video` by extension
   - an unknown extension is a model error
2. Gallery rules in `Listing._validate`, since they are malformed rather than
   incomplete (PRD 70):
   - position 1 is not a video
   - there are more than two videos, or more than 20 images
   - a listing that has a video does not have one at position 2

   `MAX_MEDIA_ENTRIES` becomes separate image and video caps.
3. Add `av>=15` to `pyproject.toml`. `workspace/video.py`:
   - `probe_video(path) -> VideoFacts | ProbeFailure`
   - `VideoFacts` holds size, duration, width, height and `has_audio`
   - PyAV errors never escape it
4. `WorkspaceFacts` gathers `VideoFacts` once per request, for the videos the
   listing names (AGENTS: a check reads the workspace through facts).
5. `listing_validation.check_videos`:
   - blocks: extension, over 100 MB, outside 3–15 s, shorter side under
     500 px, undecodable, no video stream
   - an `info` severity added to `Severity` for the audio note, rendered
     quietly by the issues banner and ignored by `gates.py`
6. `etsy_media` treats videos as outside its manifest:
   - ranks, `MediaChange`s, the ≤20 gate and the snapshot count images only
   - `.jpg`/`.jpeg` shared images upload like `.png`
7. `Workspace.common_media_files()` lists every allowed extension, recursively
   under `common-media/`. `common_media_file()` stops appending `.png`.
8. Test assets, added to `scripts/generate_test_assets.py` and committed:
   - a 3.2 s 512×512 H.264 clip, a few KB
   - a 2 s clip, a 400 px clip, and one with an audio track
   - a PNG renamed `.mp4`

   Generation is deterministic (fixed frames, no clock input).

**As built.** Where the implementation settled a detail differently:

| Item | Settled as | Why |
|---|---|---|
| 1 | Extensions match case-insensitively | A phone names its clips `IMG_1234.MOV` |
| 3 | `VideoFacts` and `ProbeFailure` are defined in `config/media.py`; `workspace/video.py` re-exports them | `check_videos` is pure and lives in `config`, which must not import `workspace` |
| 3 | The probe decodes one frame and refuses a container that is not FFmpeg's MP4/MOV demuxer | FFmpeg opens a PNG renamed `.mp4` as a one-frame video |
| 5 | `check_videos` has no extension rule of its own | `Listing` refuses an unknown extension on load, and the probe refuses contents that are not MP4/MOV, so a third copy could never fire |
| 6 | `etsy_media`'s count gate is removed, not narrowed to images | `Listing` refuses the same gallery on load |
| 7 | `CommonMediaSummary.name` is the path under `common-media/`; the picture routes take `{name:path}`; `/file` sends the image MIME type; the list stays images-only | The frontend addressed shared files by stem, which stops naming one file once `.png` is not appended. Videos join the list in PR 5, with `kind` |
| 8 | An audio-only `.mp4` is added | The "no video stream" block needs a file that has none |

**Success conditions (added to the common list):**
- Unit tests for classification and every gallery rule. Each blocked case
  and each valid layout (no video, one, two, second at the end) is its own
  test.
- A probe test for each generated asset, including the renamed PNG answered as
  `ProbeFailure` rather than raising.
- The validation tests show:
  - each block names the file and the documented limit
  - the audio note has `info` severity and does not block `plan`
- A behaviour test: a listing whose media includes a video `plan`s with
  `etsy_media` unchanged, so the video is not treated as an image.
- The ubuntu and windows CI jobs both install the `av` wheel without building
  it. Check the job logs.

### PR 3 — `feat(etsy): video client surface and a gallery-faithful fake`

**Target: about 1,800 lines.** Independent of PRs 1–2.

1. `models.ListingVideo` (`video_id`, `video_state`, `width`, `height`,
   `video_url`, `thumbnail_url`), and `Listing.videos`, where `null` becomes
   `()`.
2. `get_listing(include_videos=...)`. It composes `includes=Images,Videos`
   and never sends two `includes` parameters.
3. `upload_listing_video(file_name, contents)`,
   `attach_listing_video(video_id)` and `delete_listing_video(video_id)`:
   - every upload and attach sends `is_multi_video=true`
   - upload sends the `video/mp4` or `video/quicktime` content type
4. Error decoding:
   - a `400` whose text says "maximum number of videos" →
     `VideoBudgetExhaustedError(UserFacingError)`, whose message explains the
     10-per-listing-per-day limit
   - `409` → `VideoSlotsFullError`
   - the upload POST keeps the 429-only retry policy
5. The fake reproduces decision 9's measurements, because behaviour tests can
   only assert the gallery through it:
   - it models a gallery: the featured video is the one attached longest; a
     second video is anchored after *n* images at attach time; deleting the
     featured video promotes the other
   - `image_ids` detaching an image deletes that image's swatch link
   - it enforces 2 active videos and 10 associations per listing per 24 h,
     with an injectable clock
   - it keeps `inactive` videos in the lists
   - it exposes a read-only `gallery(listing_id)` for tests

**As built.** Where the implementation settled a detail differently:

| Item | Settled as | Why |
|---|---|---|
| 3 | Each call takes `shop_id` first, like every other write here; any extension but `.mp4`/`.mov` is a `ValueError` before sending, through one `video_content_type` the fake shares | The write paths are shop-scoped. A third type reaching the client is a caller's bug that would spend an association |
| 4 | Both errors subclass `EtsyApiError`, which gains an optional `message`; `status_code` and Etsy's own `error` text are kept | A caller catching `EtsyApiError` still catches them, and the re-wording does not lose what Etsy said |
| 5 | `image_ids` keeps a detached image restorable and refuses an id that is no image of the listing with Etsy's measured `400` | Decision 9's cut-and-restore brings detached images back; the old fake dropped them, and silently ignored a video id |
| 5 | What decision 9 did not measure — re-attaching an active video, attaching an id the shop never had, deleting one not on the listing, which refusal wins when both apply — is a `ValueError` naming the gap, or (the last) the full listing first | A stage that comes to rely on unmeasured behaviour finds out in a test |
| 5 | `seed_video(listing_id, video_state=...)` places a foreign or `inactive` video without spending budget; `video_uploads` and `video_attaches` record what was sent | PR 4's sweep and drift tests need both, and "no re-upload" is asserted on `video_uploads` |

**Success conditions (added to the common list):**
- `MockTransport` contract tests cover:
  - the multipart shape, with `is_multi_video=true` present on both upload and
    attach
  - `includes` composed once
  - the `400` → budget and `409` → full mappings, using the recon's real
    response texts
- Fake tests repeat each row of decision 9's "Where a video appears" table
  and must produce the same gallery.
- The fake test file has one subject (AGENTS).

### PR 4 — `feat(engine): the etsy_videos stage`

**Target: about 2,700 lines.**

1. `engine/stages/etsy_videos.py`, registered after `EtsyMedia()`:
   - `desired` reads the videos and the second video's anchor from `media:`
     and blocks through the PR 2 gates
   - `applied_model` is `AppliedEtsyVideos{videos: [{ref, hash,
     after_images?}]}`
   - `read_live` uses `include_videos` and splits the result into ours (by
     `etsy_video_ids`) and foreign
   - `plan` gives work on a ref, hash or anchor change, and drift for one of
     ours that is missing or `inactive`
   - `apply` follows decision 9's four steps, with `ctx.emit` progress for
     each upload, each attach and the cut
2. The swatch link helper moves out of `etsy_media` into a shared module,
   e.g. `stages/variation_links.py`, and both stages call it. That gives one
   rule and two callers.
3. A `group: str | None` attribute on the stage protocol, carried on
   `StagePlan`. The CLI's `format_plan` nests `etsy_videos` under "Etsy
   media", and the run events DTO carries `group` (the UI consumes it in
   PR 6). This follows the only-engine-diffs rule: the grouping is data the
   engine hands out, not something a reader infers from a name.
4. `EtsyVideosSnapshot` for the deploy review (A30), holding desired and live
   videos with their `thumbnail_url`.
5. An e2e extension to `test_phase3_publish_e2e.py`, in the same ordered
   sequence and on the draft it already creates. Add the featured and second
   videos, then:
   - apply; assert both are active and their ids are recorded
   - move the second video by one image and re-apply; assert the same
     `video_id`s (no re-upload) and swatch links intact
   - re-apply with no change and assert nothing is written

**Success conditions (added to the common list):**
- Behaviour tests against the PR 3 fake, each asserting the fake's
  `gallery()`:
  - first apply, and a second apply that writes nothing
  - swapping the videos with no upload
  - moving the second video
  - replacing a file's bytes
  - a foreign video swept and never triggering a run on its own
  - one of ours deleted outside, reported as drift and re-uploaded
  - swatches re-asserted after a cut
  - a crash between the cut and the restore, healed by the next run
  - the budget error surfacing as a `UserFacingError` and continuing the
    batch (PRD 16)
- A test that an `etsy_videos` failure leaves `etsy_media`'s ids recorded
  (A29), so images are not re-uploaded.
- The CLI plan output shows the videos under "Etsy media", pinned by a test.
- The e2e run in the common list includes the new video steps passing against
  the real API.

### PR 5 — `feat(ui-api): media files API and the grouped file locator`

**Target: about 2,400 lines.**

1. `Workspace.listing_media_files(name)`:
   - recursive, allowed extensions only, workspace-relative
   - never returns `listing.yaml`, `state.lock.json` or anything outside the
     listing directory
   - a security boundary: tested as one
2. Endpoints:
   - `GET /api/listings/{name}/media-files` for the *This listing* group
   - `GET /api/common-media`, returning `kind` and `ref`
   - `/file`, with the real MIME type through `FileResponse`, so HTTP Range
     works for `<video>` seeking
   - `/thumbnail` for images only; a video answers `415`, since the browser
     draws its own poster
3. `gen:api` regenerated. Its OpenAPI and TypeScript output count toward the
   size cap.
4. Frontend:
   - `media.ts` gains `mediaKind(entry)` and video picture URLs
   - `MediaLocator`'s "Images" mode becomes "Files": one list grouped *This
     listing · ./* and *Shared · common-media/*, with a muted
     `<video preload="metadata">` thumbnail, a duration badge and
     hover-to-play for videos
   - `mediaEdits` enforces the gallery rules for adding: position 1 stays an
     image, a first video lands at 2, a third video is refused, and images
     and videos have separate caps

**Success conditions (added to the common list):**
- API tests show:
  - path traversal in the listing name or file path is refused
  - `listing.yaml` and the lockfile are never listed
  - the MIME type is correct for each kind
  - a Range request answers `206`
  - a video thumbnail request answers `415`
- Vitest covers the grouped locator, video rows and every `mediaEdits` rule.
  Frontend coverage stays ≥85% branch.
- `npm run gen:api` produces no diff after commit, i.e. the checked-in client
  matches.

### PR 6 — `feat(ui): videos in the reel, preview and deploy review`

**Target: about 2,300 lines.**

1. `MediaReel`:
   - videos render inline as muted `<video>` tiles with a play badge
   - slot 2 is labelled **Featured · shown 2nd**
   - dragging keeps position 1 an image, and a move that would break a
     gallery rule snaps back
   - the header counts images and videos separately
2. `ImagesTab` preview and `Lightbox` use `<video controls>` for a video. Its
   issues show the audio note from PR 2.
3. The deploy review (`comparison.ts`, `ComparisonView`) shows the
   `etsy_videos` snapshot:
   - desired and live video tiles, the live ones from Etsy's `thumbnail_url`
   - New/Removed badges derived from the engine's changes, never diffed in the
     browser
   - the stage nested under "Etsy media" by its `group`
4. `STAGE_LABELS` gains `etsy_videos`. "Etsy images" is renamed "Etsy media".
5. A browser test, over the real SPA and FastAPI:
   - add a shared video and a listing-local video
   - drag the second one
   - wait for autosave
   - assert `listing.yaml`'s `media:` order on disk
   - assert the browser actually decoded the video: its `videoWidth` is the
     fixture's pixel width

**Success conditions (added to the common list):**
- Vitest covers the reel's drag rules, the Featured label and the preview
  switching between `<img>` and `<video>`. It also covers the review tiles
  and the grouped stage.
- The browser test passes locally and on `main`'s browser tier after merge.
- A manual check against `~/try-workspace`: add the size guide as the
  featured video, `apply`, and confirm the gallery in Shop Manager by eye.
  Record the result in the PR.

## Acceptance criteria for the whole feature

- A listing with two videos in `media:` produces that exact gallery on Etsy,
  confirmed once by eye in Shop Manager and continuously by the fake in the
  behaviour layer.
- Re-applying an unchanged listing makes no Etsy write. Reordering the videos
  re-uploads no bytes.
- Swatches are intact after every apply that moved a video.
- A video Etsy's help page would reject never reaches Etsy.
- No `listing.yaml` in the repository or in `~/try-workspace` contains
  `../`.
- Six PRs, each under 3,000 changed lines, each with green CI, green local
  gates and a green `workflow_dispatch` e2e run linked in its description.
