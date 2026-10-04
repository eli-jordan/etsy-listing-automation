# Marigold research and prototypes

Dated evidence from mockup-realism experiments through 2026-10-03. Current
requirements live in the [feature spec](../../features/marigold-20261001/spec.md),
[plan](../../features/marigold-20261001/plan.md) and
[interactions](../../features/marigold-20261001/interactions.md).
Experiments do not override those documents or establish release readiness.

| Record | Contents |
| --- | --- |
| [Marigold trial](mockup-marigold-trial.md) | Native Windows feasibility, pinned models and measured findings. |
| [Performance data](marigold-performance.json) | CPU preparation/rendering and map-storage measurements. |
| [Original handoff](mockup-marigold-handoff.md) | Historical brief, including superseded WSL and calibration suggestions. |
| [Classical trial](mockup-classical-surface-trial.md) | Earlier approach and synthetic checks. |
| [Realism research](mockup-realism-research.md) | Source-backed mapping and appearance survey. |
| [Model feasibility](mockup-prototype-model-feasibility.md) | Availability investigation. |
| [Algorithmic options](mockup-algorithmic-options.md) | Classical alternatives and limitations. |
| [Prototype scope](mockup-realism-prototype-scope.md) | Historical experimental scope. |
| [Prototype files](prototype/) | Throwaway viewers, worker, checks and supporting modules. |

Run commands from the repo root in Cygwin zsh using the trial's updated paths.
Code runs on native Windows and imports the current `etsy_listings.core` modules.
Photos, weights, maps and rendered output stay outside the repo. Old statements
about what was untested describe the date of that record; consult the trial for
later results and the feature spec for remaining quality gates.
