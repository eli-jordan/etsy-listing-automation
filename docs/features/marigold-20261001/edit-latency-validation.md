# Interactive correction latency, 2026-10-19

The correction target is a changed material composite displayed below one second
following the final mask or covered-geometry edit. A local brush overlay does not
satisfy this target. Interactive previews use a 256px longest edge, a transient
17 by 17 fit, WebP and artwork bounded to 512px. Full-quality Preview and export
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

## Accepted measurements

The final sequential runs used the same implementation fingerprint
`125bcd3d72720b27ea7a69078f0a5c1e7c4002a67f536442b36a70626e7b4310`.
No tests or static checks ran concurrently. Each row contains four edits; each
source had 16 edits, including 14 with the same rebuild active before the gesture
and after composite display. Every measured edit passed the one-second target.
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

## Correctness and verification

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
