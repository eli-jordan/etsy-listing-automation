# Integrated native validation

Measured 2026-10-08 on native Windows using the production engine 1.0.0,
`Runtime.worker`, `Preparations`, durable `Artifacts` and the CPU scene renderer.
This is PR7's release evidence under ADR-0053. Independent UI/API review and the
stack's final CI/e2e gates remain separate requirements. No production readiness
claim follows from the measurements below.

## Inputs and reproducibility

The RTX 3070 has 8192 MiB VRAM, driver 616.92. The machine has about 16 GiB
physical RAM. The runtime retains the pinned CUDA 12.8/Python 3.12.14 installation
validated in [PR2](runtime-validation.md). All default-quality calls use 10 steps,
3 ensemble members, batch size 1, processing resolution 768 and seed 2026.

Two supplied 33-photo packs were read without modification. Bay, Ivory and Black
were copied from each pack into an isolated temporary workspace. Every photo is
2048 by 2048. Existing external YAML was read as experimental calibration input;
new files use the current format. The original pack, photos and design were never
rewritten. There are no photographs, weights, credentials or generated maps in Git.

Bay is the first photo by the production ordinal ordering. Its maps are compared
with independently prepared Ivory/Black maps on each target's own background.
Independent maps are an experimental comparison, not physical ground truth or a
production per-colour override. Independently prepared single templates remain
in the external workspace for incompatible photos.

Opaque white, saturated magenta, one-pixel lines/fine text, translucent shapes and
the supplied real artwork were rendered at original photo resolution. The full
matrix has 60 PNGs using default estimated lighting. Another 12 white-ink images
compare photographic lighting. Original-resolution files and 1:1 crops were
visually inspected. The local `review.html` links each original PNG.

From the repo root in Cygwin zsh, reproduce the complete serial run with native
Windows path arguments:

```sh
env -u ETSY_LISTINGS_ROOT uv run python scripts/run_marigold_validation.py \
  C:/Users/Admin/Desktop/try-workspace \
  C:/cygwin64/tmp/marigold-validation-new
```

The output must be a new directory outside both the source workspace and repo.
The driver gives every subprocess a 30-minute ceiling and kills only its owned
process tree on timeout or interruption. The native watchdog deliberately adds
15 minutes and the idle test five minutes. Failed stages stop the run and leave
prior evidence. Each stage can be rerun separately against its external output;
preparation stages that create templates require a fresh run.

Raw evidence for this measurement is under
`C:/cygwin64/tmp/marigold-pr07-native-07`: measurements, comparison, lifecycle,
multiple, scenes, watchdog and shutdown JSON; copied workspace; rendered PNGs.
The scripts target production modules. They do not import the prototype.

## Shared-colour quality

Sharing is unsuitable for the fence pack's changed-fold photos. White ink on
Black acquires a visible pale-green cast with Bay's estimated-lighting maps and
uses Bay's fold placement. Independent preparation follows Black's stronger
vertical folds and is substantially more neutral. Photographic lighting removes
that particular chromatic cast but retains the reference fold/shading pattern;
it does not establish compatibility. Ivory has a different silhouette and folds
as well. Split these photos into independently prepared templates and review the
resulting listing images. Matching dimensions never certify a colour pack.

The tested folded print area is much flatter and shows smaller mapping changes.
Its fine lines and real artwork remain legible in the inspected copies, and
transparent regions preserve the selected background. That is evidence for these
three photos and this calibration only. It does not approve all 33 colours or
regions outside the tested placement. White artwork on Ivory also has naturally
low contrast; artwork selection remains part of listing review.

The following distances compare model-derived material coordinates over pixels
visible in both maps, scaled by placement width. They are disagreement measures,
not garment reconstruction error. There is no numerical quality cutoff.

| Target with Bay shared maps | Mean photo-pixel disagreement | 95th percentile | Maximum |
| --- | ---: | ---: | ---: |
| Folded Bay | 0.00 | 0.00 | 0.00 |
| Folded Ivory | 0.38 | 0.73 | 0.83 |
| Folded Black | 0.97 | 2.02 | 2.79 |
| Fence Bay | 0.00 | 0.00 | 0.00 |
| Fence Ivory | 2.29 | 4.34 | 7.04 |
| Fence Black | 5.95 | 14.27 | 23.07 |

Bay's shared and independent default renders match byte for byte for all five
artworks. The original folded quad sits below the pendant, so it cannot establish
foreground exclusion quality. The extra foreground trial shifts it upward by
300 photo pixels so white ink actually crosses the chain and pendant.

## End-to-end latency

Submission through durable complete map publication took the following time.
Each role uses real pinned models. These are cached-weight measurements, not
fresh-network installation benchmarks.

| Case | Seconds |
| --- | ---: |
| Folded Bay | 99.23 |
| Folded Ivory | 86.22 |
| Folded Black | 76.87 |
| Fence Bay | 83.18 |
| Fence Ivory | 127.26 |
| Fence Black | 68.80 |

The Fence Ivory case includes a roughly 52-second deep runtime cache refresh.
First inspection took 52.78 seconds. Status therefore needs the existing host
executor offload; a cache miss is substantial startup work, not warm polling.

Across the 60 original-resolution default renders, CPU composition took
2.08-5.14 seconds, median 2.49. PNG encoding took 1.01-1.64 seconds, median 1.38.
The real artwork is 4200 by 4800; the diagnostics are 512 by 512. These timings
exclude HTTP transfer and browser display. Closing the already idle coordinator
after the six preparations took 2.91 seconds.

## Native lifecycle, memory and practical limits

Native lifecycle measurements are recorded separately from visual quality.
The 4096-axis/16 Mi-pixel inference bound and artifact generation limits are
allocation safety caps, not guarantees that every aspect ratio or placement set
is equally fast or visually suitable. A 4 GiB model-tensor budget is not a total
worker-process RAM guarantee.

The worker watchdog uses the actual 900-second deadline. A native worker is
identified by its unique cache command and verified Windows launcher/child chain,
then its backend is deliberately suspended after a real progress event. This
models a hung process. It is not a physical CUDA driver-failure experiment.
The separate shutdown experiment measures the actual 15-second grace period
before the owned process tree is forcibly stopped.

`Preparations.close()` has a different contract. It requests graceful shutdown,
waits for active GPU/CPU phases to finish and retains resumable records. The
worker's 15-second grace starts only when worker close is reached; it is not a
15-second bound on total server shutdown. A hanging active model call first
relies on the 900-second inference watchdog.

## Release gates

| Gate | Evidence and current status |
| --- | --- |
| G1 | Production-native measurements and full-resolution comparisons are recorded here. 79 Photo warp/Marigold golden, listing, coordinator and protocol checks pass. Photo warp bytes are unchanged. |
| G2 | BUILD checks pass: 1462 unit cases, five platform skips; 17 integrated frontend cases; ruff formatting/lint, mypy, Prettier, ESLint and TypeScript. The recovered full check at `08e2a6ac` passed 3206 Python tests with seven skips and 95.61% coverage; frontend passed 1027 tests across 81 files with 89.23% branch coverage. The earlier dedicated browser rerun passed all 113 cases. Final propagated owner fixes still require final gates. |
| G3 | No HTTP contract changes or new production dependencies. No user data, secrets or weights enter Git. Existing CPU rendering import boundaries are retained. |
| G4 | Parent owns PR creation, CI and exclusive real-shop e2e dispatch during FINISH. No remote shop writes or dispatch occur in this BUILD. |
| G5 | Independent Chrome/UI and API review verified the flows below. Final Escape/loading recheck and recovery-defect verification remain pending; foreground image quality limits remain explicit. |

## Completed lifecycle and resource measurements

The 4 GiB loaded-model tensor budget does **not** bound worker RAM. At the
4096-by-4096 cap, Windows measured a peak working set of 7,333,765,120 bytes
(6.83 GiB) and peak commit of 12,865,855,488 bytes (11.98 GiB). The separate
CPU host peaked at 1.33 GiB working set and 1.64 GiB commit in the overlapping
render trial. A 16 GiB machine may page; these are measured costs, not a promise
that the advertised maximum placement set fits comfortably.

| Native measurement | Actual result |
| --- | --- |
| 2048 depth first call / warm call | 16.63 / 7.00 seconds end to end; 7.99 / 5.17 seconds inference |
| 4096 normals / lighting / depth | 19.87 / 36.60 / 15.90 seconds end to end |
| Maximum current RSS reported by cap calls | 6,783,303,680 bytes during lighting; distinct from Windows peak working set |
| Loaded tensors | About 2.40 GiB, one pipeline at a time |
| Peak CUDA allocated / reserved | About 1.94 / 2.56 GiB; excludes desktop and driver allocations |
| 4097-axis refusal | 0.0074 seconds before inference |
| Warm-call cancellation | Intent recorded in 0.12 ms; active call returned 5.85 seconds later with validated evidence |
| Default idle timeout | After an unshortened 305.04-second wait, next call was cold (20.11 seconds) |
| Actual 900-second watchdog | Suspended backend returned after 899.93 seconds; total call 906.66 seconds including startup |
| Actual forced worker close | 15.072 seconds; inference thread finished, no final or partial result remained |
| Minimum 1-step/1-ensemble depth | 2.20 seconds inference; steps 0/11 and ensemble 0/4 refused |

The watchdog suspension is a controlled process hang, not a real CUDA driver
fault. Both watchdog and forced-close runs cleaned their owned native process
trees. Normal final worker close took 0.81 seconds. Active coordinator close in
the colour-matrix trial took 6.26 seconds, saved the completed normals evidence
and left a queued resumable record. A new coordinator resumed and completed it.
That successful graceful case establishes no fixed host shutdown deadline.

## Multiple placements and evidence reuse

The constructed multiple template contains two overlapping prints on one copied
real shirt, not a photographed scene of two different garments. Both stable IDs
(`inner-magenta`, `outer-white`) were prepared with real models. Cancelling after
normals retained one crop and valid prediction. Retry completed both placements
using one covering crop and its three predictions. The entire cancel/retry trial
took 128.62 seconds; cancel intent persisted in 2.62 ms and terminal cancellation
arrived 12.07 seconds later. Polls during the initial preparation took at most
0.76 ms; HTTP and polling during CPU fitting were not measured by that sample.

Distinct white and magenta artwork rendered at full resolution. Reversing layer
order changed 226,576 pixels. Composition took 3.94 seconds alone and 4.64 seconds
while a separate real depth call ran (17.72 seconds end to end). The renderer host
has no Torch installation or loaded Torch module. OpenCV and NumPy OpenBLAS used
10 threads each on this machine; the isolated model worker sets Torch to four.
There is no enforced combined host-library thread budget. Other CPU sizes and
simultaneous large placement sets remain unvalidated.

The saved 40% expanded evidence rectangle covered the original and a 60% inner
quad. Translating the original by one photo pixel failed full-margin coverage.
This confirms conservative reuse; it does not justify reducing the margin.
The initial measurement exposed a late-refusal bug: aggregate 2 GiB validation
ran only after CPU map construction. Actual 2048-by-2048 descriptors contain
14 four-byte channels (56 bytes per pixel), or 234,881,024 bytes per placement.
Ten require 2,348,810,240 bytes, exceeding the 2,147,483,648-byte cap. This was
a concrete code-path finding, not an observed OOM; an unsafe near-OOM run was
avoided. The owning PR3/PR4 fixes now preflight this retained-generation size
before submission, runtime inspection, recovery and execution. Public-interface
regressions cover early refusal without allocating the oversized generation.
Publication retains its final validation. The fix does not guarantee comfortable
RAM use for every accepted placement set. Native measurements above are preserved
and were not rerun for this deterministic budget check.

## Foreground and colour-matrix verdict

Four additional real preparations completed: shifted folded colour matrix
113.74 seconds, independent shifted Ivory 86.43, independent shifted Black
80.84, and fence colour matrix 138.48 including graceful close/resume. Sixty
additional full-resolution shared/independent diagnostic renders are preserved.

The shifted quad actually crosses the chain and pendant. Visual inspection of
opaque-white Bay and independently prepared Black shows incomplete foreground
protection and visible ink/lighting contamination around the chain. Bay's pendant
also becomes washed out. The automatic proposal therefore fails approval for
this region: correct the mask and review it before using the template. The
experiment leaves the proposal unchanged so the failure remains inspectable.
Original placement below the pendant is a different, less demanding region.

Neither the fence colour matrix nor the foreground proposal passes a blanket
quality gate. Independent maps are useful comparison evidence, not photographic
ground truth. All 33 photos, every aspect ratio, real two-garment scenes, maximum
32 placements, browser display latency and low-memory machines remain outside
these measurements. Recorded local coverage and browser gates pass. Final propagated-fix gates, CI,
real-shop e2e and the remaining independent rechecks are required before delivery.

## Independent integrated UI/API review

The stack orchestrator reviewed the production server in Chrome using the
isolated workspace, without remote shop credentials. Full-quality previews were
observed for single (1/1), multiple (two placements, 1/1) and colour matrix (3/3).
The selected white test design appeared in every multiple placement. The full-size
viewer advanced with Next and closed with Escape. Photo warp to Marigold restored
Ready and reused existing maps. Maximum inference settings were visibly 10/3.

Actual canvas dragging painted a visible mask stroke; Undo removed it and Done
exited the brush. Multiple-placement Reset restored the automatic mask visually.
The transient paint jobs followed by Undo/Reset were superseded during fitting
and reused the prior completed generation: they were not completed rebuilds.
The separate explicit foreground correction job completed in 99.57 seconds with
CPU-only rebuild and no GPU inference. Save and exact retry both returned 200
with the same ETag. The corrected full-resolution PNG returned 200 in 10.22
seconds. It restored the pendant and manually brushed chain segment, but a broad
brush exposed a garment halo and an unbrushed second chain remained affected.
This proves correction controls work; it neither approves automatic occlusion
nor certifies the hand-edited mask for production.

Independent API smoke checks returned the eleven-template catalog in 0.093
seconds (200), multiple configuration with an ETag in 0.157 seconds (200), missing
preparation in 0.015 seconds (404), and invalid `jobs?limit=0` as 422. These are
warm local measurements, not a bound on deep runtime status or initial loading.
Evidence remains external under `parent-qa`, including `final-api-smoke.json`
and `foreground-after.png`; no real images enter Git.

Body-focused Escape while editing was found to violate the interaction contract
and reported to the editor owner. Its document-listener fix and initial catalog
loading state await independent recheck here. A separate intermittent photo-change
recovery failure is under owner investigation; final coverage and browser gates
must include the propagated resolution. Neither issue is silently marked passed.

## Isolated manual review workspace

Use `C:/cygwin64/tmp/marigold-pr07-native-07/workspace`. Its `shop.yaml` contains
only `etsy: {currency: USD}`; it has no shop/product IDs, `.env`, OAuth tokens or
listing documents. No remote credentials were copied. Remove credential overrides
from the server environment as well:

```sh
cd /cygdrive/c/Users/Admin/.t3/worktrees/etsy-listing-automation/marigold-pr07
env -u ETSY_LISTINGS_ROOT -u PRINTIFY_API_TOKEN -u ETSY_KEYSTRING   -u ETSY_SHARED_SECRET -u ANTHROPIC_API_KEY   uv run --no-sync etsy-listings ui   --root C:/cygwin64/tmp/marigold-pr07-native-07/workspace   --host 127.0.0.1 --port 8007
```

Prepared singles are `folded-bay`, `folded-ivory`, `folded-black`, `fence-bay`,
`fence-ivory`, `fence-black`, `folded-edge-ivory` and `folded-edge-black`.
Prepared colour matrices are `folded-edge` and `fence-colours`; their limitations
above are intentional review inputs. `multiple-validation` has both placements
prepared. Local design files are `white.png`, `saturated.png`, `fine.png`,
`transparent.png` and `real.png`. Full-resolution foreground evidence is outside
the workspace under `renders/folded-edge-*-white-*.png`; none is committed.
