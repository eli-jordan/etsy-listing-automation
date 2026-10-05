# Native runtime validation

Measured 2026-10-05 on native Windows, NVIDIA RTX 3070, 8192 MiB VRAM and driver
616.92. This is PR2's runtime evidence under ADR-0053. It establishes package,
protocol and lifecycle execution. It does not establish garment-map quality,
full-resolution rendering or the feature's remaining colour/multiple gates.

## Installation and actual model calls

Production Runtime.setup installed an independent Python 3.12.14 environment
from the embedded complete 33-package uv.lock. Torch is 2.8.0+cu128; the direct
model packages and three checkpoint revisions match the approved plan. Setup
verified Hugging Face LFS SHA-256 or Git blob hashes, recorded local SHA-256 and
size descriptors, ran all roles through JSON-lines v1, validated the numeric
archives and rechecked the relocated installation before activating it. The
complete successful setup took 200.987 seconds with previously downloaded weights.
That duration includes installing copied packages and deep capability verification.
It is not a fresh-network download benchmark.

The input was a synthetic 128 by 128 RGB image. Processing resolution stayed 768,
seed 2026, inference steps 10, ensemble size 3 and batch size 1. No lower quality
settings or CPU fallback were used. Normals, lighting and depth shapes were
respectively 1x128x128x3, 3x128x128x3 and 1x128x128x1. Readers checked checksums,
float32, finite values, normal lengths and lighting/depth ranges.

| Role | Load seconds | Inference seconds | GPU allocated bytes | GPU reserved bytes | Retained model bytes | Process RSS bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Normals | 0.810 | 11.366 | 2082369536 | 2732589056 | 2579928510 | 4254347264 |
| Lighting | 0.672 | 10.736 | 2083338240 | 2717908992 | 2580020686 | 4571533312 |
| Depth | 0.643 | 9.361 | 2082066432 | 2717908992 | 2579928510 | 4807835648 |

The worker retains one pipeline, limited to 4 GiB of model tensors. The measured
resident tensors were about 2.40 GiB. Peak process RSS reached 4.48 GiB, so the
model-tensor budget is explicitly not a total-process RAM guarantee. Active
components use model CPU offload; role changes release the previous pipeline.
These measurements exclude numerical fitting, composition and CPU overlap.

## Warm reuse, cancellation and idle exit

A second production run retained a depth pipeline while exercising the protocol.
Its first call took 8.650 seconds. Cancellation during the next call returned
accepted valid evidence after 5.106 seconds with cancelled=true. The checksum and
array passed the ordinary reader. A subsequent explicit retry took 4.848 seconds
and reported warm_reuse=true. Cancellation kept the process and pipeline warm.
An explicit same-engine update during this worker's lifetime retained its original
engine and installation selection. No additional model call was queued internally.

The real default idle timeout was exercised, not shortened for the measurement.
The worker exited after 301.162 seconds, observed at one-second polling intervals.
Controlled subprocess tests separately show automatic replacement on the next
call, active-call completion on cancellation, refusal of concurrent calls,
unsafe-path rejection, independent stderr draining and watchdog failure without
publishing a partial artifact.

## Capability polling and host integration

First deep inspection took 25.349 seconds. Five subsequent inspections in the
same process took 25.9-30.2 milliseconds. Worker handshake took 6.405 seconds.
The report cache lasts five minutes and is bound to the installation manifest,
distribution files, weights and installed package metadata sizes/modification
times. Changed state forces verification; package inventory must equal the full
lock, including refusal of unlocked extras. A fresh worker handshake checks
actual CUDA and engine capability independently of this cache.

The coordinator and server must run deep inspection on a background executor or
at startup outside the event loop. HTTP polling should reuse the process cache.
A cache miss or expiry can still cost tens of seconds; it must not block the
async server thread. Status never downloads packages or weights.

## Failures found and resolved

An interrupted, unactivated stage contained incomplete package metadata. It was
not selected. Explicit repair staged another immutable installation and retained
verified downloads. Setup failure preserves the prior current pointer; a damaged
same-engine installation is repaired under a new installation ID rather than
replacing files selected by an active job. Tests also cover failure after rename
and a successful later retry while the earlier current installation stays usable.

The initial real protocol run stalled loading SciPy's native BLAS module from
Diffusers' lazy pipeline imports after the control reader started. Persisted
native stack traces identified scipy.linalg.blas/_fblas creation. Direct model
execution on the main thread succeeded. Resolving all pipeline dependencies on
the model thread before the handshake and reader startup removed the stall, and
all three production protocol calls then passed. Controlled model boundaries
require main-thread startup so protocol tests retain that ordering constraint.
Diagnostics drain immediately in bounded chunks; startup exits include stderr.
Forced Windows shutdown targets the owned subprocess tree.

## Operational limits and remaining release checks

Engine 1.0.0 accepts 1-10 steps and 1-3 ensemble members. The measured maximum
settings are the default 10/3. Images have a safety cap of 4096 pixels per axis
and 16,777,216 pixels total; numeric archives have a 640 MiB bound checked before
allocation. These caps constrain resources. This run did not validate every
allowed image size, aspect ratio or setting combination.

The inference watchdog is a defensive 900-second ceiling and forced shutdown
allows 15 seconds before termination. They are not latency promises. The native
small-input call measurements and controlled watchdog tests do not establish
full-resolution driver-failure or shutdown deadlines. PR7 still must validate
large real crops, total RAM/VRAM under CPU overlap, responsive cancellation and
watchdog/shutdown bounds on the supported machine. No production quality claim
comes from this synthetic smoke.

Local raw logs and numeric evidence remain outside Git. The committed table is
copied from the production installation manifest and lifecycle report; no weights,
photographs, secrets or user-workspace configuration entered the repository.
