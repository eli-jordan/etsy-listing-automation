# Interactive correction latency

The correction target is a changed material composite displayed below one second
following the final mask or covered-geometry edit. A local brush overlay does not
satisfy this target. Interactive previews use a 1024px longest edge, a transient
17 by 17 fit, WebP and artwork bounded to 3072px. Smaller native photos are not
upscaled, and non-square photos preserve their aspect ratio. Full-quality Preview and export
retain original artwork, photo dimensions, the 49 by 49 fit and accepted durable
generations. ADR-0053 records this separation.

## Reproduction and measurement

Run from the repository root in Cygwin zsh, using native Windows path arguments.
The fixture generator writes only to a new external directory. Its deterministic
2048px RGB scene and fixed normals, lighting and depth exercise real validation,
fitting, mask storage and generation publication without model inference.

```sh
uv run python scripts/create_marigold_latency_fixture.py C:/cygwin64/tmp/marigold-fixture-new
uv run python scripts/benchmark_marigold_edits.py C:/cygwin64/tmp/marigold-fixture-new C:/cygwin64/tmp/marigold-edits-new --interactive --during-rebuild --repeats 4 --threshold 1
```

The browser driver copies its source into a fresh output directory. It never
changes the source and refuses model selection or inference. Each timing starts
at the final pointer-up, waits for a changed decoded image fingerprint and two
animation frames, then verifies the sampled mask pixel where applicable. It
records HTTP responses, dimensions, hardware, package/browser versions, source
and code identity. Both masks and inward geometry moves run on one and two
placements. The default waits for durable publication between samples;
`--during-rebuild` starts the next edit after autosave has an active rebuild and
requires observed overlap for every placement/edit case. The report also records
whether the same job remained active before the gesture and after display.

The original larger-workspace run exposed 2.29-second edits when each selected
rebuild restarted catalog readiness requests for unrelated templates. The preview
then raced autosave, refused the superseded revision and needed a retry. Selected
job changes now leave unrelated catalog rows alone. Other job changes refresh
only their own rows. Progress checkpoints coalesce into status snapshots at most
once per 250ms; phase-only changes do not reload the catalog. Public-hook regressions demonstrated the failure and correction. A separate public preparation
regression protects small valid placements whose downsampled cloth area is below
100 pixels; only the interactive lighting sample threshold scales with area.

The browser transition also exposed a late autosave catalog refresh selecting
its old template after the user had moved on. The App regression fails on that
race and passes with selection-at-request fencing. This preserves the new user
selection without cancelling or changing the already-authorized save.

A pending-preview App regression also demonstrates that the original 800ms
idle save can supersede its own in-flight composite. Autosave now keeps that
minimum deadline but waits for the current request to settle before writing.
Explicit Save and preparation retain their revision checks. Validated evidence
reads live separately from job-owned prediction publication, preserving the
existing import restrictions.

The final CPU lane yields at existing phase checkpoints while the workspace has
an active interactive request. Cancellation and close intent are still checked;
no calibration or coordinator lock is held while waiting. An already executing
phase is not interrupted. This keeps full-quality numerical operations unchanged
while reserving the next CPU phases for the visible edit.

A lease regression also reproduced archive decompression holding the template
lock during unchanged-placement reuse. Reuse now captures inputs under that
lock, then acquires the existing generation lease before loading outside the
lock. A concurrent snapshot can proceed while the archive read is blocked.

Full-quality comparison against the preserved original implementation passed on
`folded-bay`, `folded-edge` and `multiple-validation`. Every visible numerical
field and bake sample matched exactly, and decoded full-photo composites matched.
The external `marigold-final-parity.json` records the fingerprints. PNG compression
level one deliberately changes encoded bytes and identity while remaining lossless.

## Historical 256px measurements, 2026-10-19

The earlier 256px sequential runs used the same implementation fingerprint
`125bcd3d72720b27ea7a69078f0a5c1e7c4002a67f536442b36a70626e7b4310`.
No tests or static checks ran concurrently. Each row contains four edits; each
source had 16 edits, including 14 with the same rebuild active before the gesture
and after composite display. Every measured edit in that earlier run passed the one-second target. Later
real-photo measurements reached 1.648 seconds, so this result was not a guarantee.
The preferred half-second target is not met consistently.

| Source | Placements | Edit | Median (s) | Maximum (s) |
| --- | --- | --- | ---: | ---: |
| Synthetic 2048px | 1 | mask | 0.350 | 0.416 |
| Synthetic 2048px | 1 | geometry | 0.423 | 0.531 |
| Synthetic 2048px | 2 | mask | 0.475 | 0.565 |
| Synthetic 2048px | 2 | geometry | 0.574 | 0.835 |
| Real photos, 4200 x 4800 artwork | 1 | mask | 0.432 | 0.448 |
| Real photos, 4200 x 4800 artwork | 1 | geometry | 0.475 | 0.566 |
| Real photos, 4200 x 4800 artwork | 2 | mask | 0.691 | 0.763 |
| Real photos, 4200 x 4800 artwork | 2 | geometry | 0.507 | 0.616 |

The host was Windows 10 build 19045, Intel Family 6 Model 165 with 10 logical
processors, Python 3.12.14, NumPy 2.5.2, OpenCV 4.10.0 (10 threads), Pillow 10.4.0
and Chromium 151.0.7922.34. Initial image display took 1.26/1.84 seconds for the
synthetic scenes and 2.36/1.90 seconds for the real scenes; these warmup costs are
outside the correction timings and are not a startup result.

Raw rows, responses, identities and summaries remain outside Git in
`C:/cygwin64/tmp/marigold-accepted-synthetic/measurements.json` and
`C:/cygwin64/tmp/marigold-accepted-real/measurements.json`. Real source photos were
corroborated against the prepared native-07 copy before testing; all benchmark
writes used fresh copies. No photography, model weights or workspace data enter
the commit.

## Historical verification, 2026-10-19

The full default backend run passed 3,223 tests with seven skips and 94.82%
branch coverage before the final cooperative scheduling and lock-scope changes.
The later hermetic run passed 3,110 tests and reached 95.13% coverage; its two
root-discovery failures came from an inherited `ETSY_LISTINGS_ROOT` and both
passed when rerun with that variable cleared. The final scheduling/API checks
passed 61 tests, and the final artifact/lease/file-version checks passed 48.
Full frontend verification passed 1,040 tests in 81 files with 89.48% branch
coverage. Frontend lint, type checking and production build passed, as did Ruff,
Windows/Linux mypy (219 source files) and all 11 import contracts.

Standards and spec reviews were completed. Their findings on readiness retries,
small-placement lighting, active-rebuild measurement, autosave fencing and
selection races were addressed. Final lock-scope review found no remaining lease
race. Full-quality numerical and decoded-composite parity remains exact on the
three real scenes described above.

## 1024px revision, 2026-10-20

User feedback rejected the earlier 256px frame as too blurry. The editor now
rasterizes at a 1024px longest edge using artwork sampled from up to 3072px.
The transient 17 by 17 field fit stays coarse. The renderer never enlarges a
completed 256px frame or a 512px artwork print to satisfy the resolution check.
ADR-0053 and the feature amendment were committed before implementation.

The new HTTP detail test uses deterministic 4200 by 4800 artwork with fine black
lines and text. It compares both regions with an independently rendered,
downsampled full-quality reference. Contrast must exceed 180 and mean absolute
error must stay below 35. The square frame measured line/text contrast of
189.31/214.31 and error of 14.34/4.68. The non-square 1024 by 910 frame measured
183.81/208.68 and 15.99/5.14. A negative control using the old 512px artwork cap
failed at 151.1 contrast, even with the 1024px output. A numerical regression
also protects OpenCV's pixel-centre correspondence when scaling the transient
field and placement coordinates.

An exact byte-to-linear lookup and bounded reuse of premultiplied artwork remove
repeated conversion work. The host counts those arrays within its existing
384 MiB cache budget and verifies the file token around decoding. Repeated file
replacement refuses rather than mixing pixels and linear samples from different
versions. The pure renderer retains uncached buffers for only the current layer.
A regression covers eight separately allocated placement sources.

Template reads still open the current UTF-8 document under the existing locks.
Only parsing is cached, by exact contents, for up to 64 documents of at most
64 KiB each. Every caller gets a deep model copy. Tests protect mutable placement
lists, external edits with unchanged size and mtime, oversized documents and
path-specific validation errors.

Full-quality Preview and export keep their source artwork and numerical path.
Comparison against 696b7ba on `folded-bay` and `multiple-validation`, using the
actual artwork, produced identical 2048 by 2048 decoded pixels, encoded PNG hashes
and identities. Every byte transfer lookup value matched the previous arithmetic.
The evidence is in `full-quality-parity2/parity.json` under the external review
directory. `folded-edge` in this source is Photo warp and was not part of this
Marigold parity comparison.

The screenshot assertion now checks the existing responsive toolbar at both
1440px and 1280px. The test design picker shares the tabs row at 1440px and wraps
to an aligned second row at 1280px. Every control must remain inside the toolbar,
and the header height remains below 65px. The shared Photo warp canvas width is
unchanged.

### Measurements and remaining constraint

All runs below used fresh external output directories and the same inputs.
Synthetic and real-photo cases each cover masks and covered geometry on one and
two placements, with four edits per case. The artwork is 4200 by 4800. Final
actual-artwork runs additionally select `duke-java-developer` and cover geometry
on both scenes. No tests or builds ran during these measurements.

| Run | Samples | Median seconds | Maximum seconds | At or above 1 second |
| --- | ---: | ---: | ---: | ---: |
| Synthetic idle | 16 | 0.615 | 0.698 | 0 |
| Synthetic rebuild overlap | 16 | 0.691 | 1.065 | 2 |
| Real photos idle | 16 | 0.661 | 0.817 | 0 |
| Real photos rebuild overlap | 16 | 0.850 | 1.164 | 4 |
| Actual artwork idle | 8 | 0.632 | 0.664 | 0 |
| Actual artwork rebuild overlap | 8 | 0.749 | 1.796 | 1 |

Every displayed composite decoded at exactly 1024 by 1024. All 40 idle samples
passed. Seven of the 40 overlap-run samples missed the strict one-second target,
so this revision does not satisfy the latency requirement consistently. The
benchmark exits with failure for those runs. Overlap was observed at edit time
for 14/16 synthetic, 14/16 real-photo and 6/8 actual-artwork samples; the first
sample of each case starts without a previous rebuild. The same job remained
active through display for 14, 9 and 3 samples respectively. No samples were
excluded from the timing threshold.

The contemporaneous 256px baseline measured maxima of 0.602/0.798 seconds for
synthetic idle/overlap and 0.651/0.865 for real idle/overlap. Its real-overlap run
completed all 16 raw rows but stalled during teardown; the raw rows remain
available without a completed report. The first uncached 1024px iteration reached
1.260/2.082 and 1.199/1.630 seconds respectively. The final changes reduce those
costs while preserving the higher raster and artwork resolution.

A warm two-placement endpoint profile fell from 1.127 seconds in the first
1024px iteration to 0.504 seconds. The final profile attributes 0.214 seconds to
composition and 0.152 to fitting the edited placement. This excludes browser
display and other server requests. Slow overlap traces also include queued
revalidation, status work and an already executing durable phase. In the 1.796
second actual-artwork sample, durable flattening ran from approximately 0.006 to
1.690 seconds after the edit. The current shared CPU lane yields between phases;
it cannot preempt an executing numerical phase. Together with calibration and
status contention, that prevents a demonstrated subsecond bound on this host.
The preferred half-second target is also unmet. No resolution or threshold was
lowered to hide these tails.

The final implementation fingerprint is
`8814e4c911ce2b23f1770f4484cacc6528fcbfcd2d022b5838ea94ff9823089a`.
All raw rows, HTTP responses, phase checkpoints, native decoded PNGs and summaries
are under `C:/cygwin64/tmp/marigold-1024-review`. `final-summary.json` records every
miss and links each run by directory name. `source-identities.json` corroborates
real photos against the native-07 source. The original prepared workspace and
server on port 8007 were untouched.

Reproduce with a new output directory for each run. Use `synthetic-source` below
for synthetic cases or the read-only prepared real workspace for real cases.
Append `--during-rebuild` for contention and `--design duke-java-developer --edit
geometry` for actual-artwork cases.

```sh
unset ETSY_LISTINGS_ROOT
uv run python scripts/benchmark_marigold_edits.py C:/cygwin64/tmp/marigold-1024-review/synthetic-source C:/cygwin64/tmp/marigold-1024-repeat-new --interactive --repeats 4 --threshold 1 --artwork-size 4200 4800 --frontend-dist C:/cygwin64/tmp/marigold-1024-review/ui-dist-final
```

### Revision verification

Ruff formatting and lint pass. Mypy reports no issues across 219 source files,
and all 11 import contracts pass. The external production build succeeds.
Frontend formatting, lint and type checking pass, with 1,050 tests in 83 files
and 89.59% branch coverage. The full hermetic backend suite passed 3,126 tests
with seven skips and 95.24% coverage. All 120 browser tests passed against the
external new build, including the responsive screenshot assertion and nine
captured states. `backend-final.log`, `frontend-final.log`, `static-final.log`,
`ui-build-final.log` and `browser-final.log` retain these gates in the external
review directory.
The focused render/API/cache suite passed 51 tests before the full gates.

Both spec reviews found no mismatch. The first standards review identified
unbounded artwork buffer retention; the per-layer release and separate-source
memory regression resolve it. The second standards review found no remaining
findings. These reviews do not establish latency compliance; the failed overlap
measurements above remain authoritative.

## Limits

These are warm correction measurements on one Windows machine, not a startup
promise or a bound for every CPU, filesystem, artwork and placement configuration.
Initial photo/evidence decoding is recorded separately. Prediction-cache removal
still permits full-quality rendering from durable maps but refuses interactive
refitting until explicit preparation provides evidence again. Geometry outside
the complete conservative prediction margin also requires preparation. No GPU
starts implicitly. Large template counts, simultaneous jobs, rapid overlapping
saves and CPU load can change latency; the retained raw traces describe the cases
actually measured.
