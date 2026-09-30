# ADR-0039: Replan before applying a reviewed fingerprint

Status: accepted.

Fingerprint the serialised plan without snapshots and require a matching fresh plan before executing a reviewed UI apply. Executing a cached plan would miss remote changes and file edits after review; hashing only desired state would let newly appeared drift through. A changed fingerprint returns the new plan before any stage executes. The CLI and manual edits share the same files, so a browser-local lock cannot provide this guarantee.

First recorded 2026-09-17 in [commit c455e61](https://github.com/eli-jordan/etsy-listing-automation/commit/c455e616bc59c0340ab410d3c2b813bb61f466a3).

## Amendment: include stable execution inputs

The plan fingerprint also includes a stage's stable review-input digest when
its presentation can describe different execution inputs. Render supplies the
digest of design, template and photo bytes plus resolved scene recipes. Paths
and a generic reason alone cannot distinguish two edits made before the first
render, so replanning those fields was insufficient to protect reviewed pixels.

Stages expose that digest separately from display snapshots. The engine carries
it on the plan and includes it alongside changes, actions and drift. Preview
availability, CDN URLs and other transient display facts remain excluded;
finishing a preview does not change execution authority. A changed digest
requires a new review before any apply stage runs.
