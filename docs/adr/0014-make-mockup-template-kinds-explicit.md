# ADR-0014: Make mockup template kinds explicit

Status: accepted.

A mockup template is exactly one of `colour-matrix`, `multiple` or `single`, represented as a discriminated union. The kinds distinguish a per-colour photo set, a scene with several garment placements, and a single placement with its own artwork. Keeping the shapes separate makes their filename and placement rules checkable instead of allowing mixed configurations whose meaning depends on the renderer.

First recorded 2026-09-03 in [commit f8b2138](https://github.com/eli-jordan/etsy-listing-automation/commit/f8b2138bd89aeff1616043f45da8c276cb4cfc33).

## Accepted extension, not yet implemented

[ADR-0053](0053-prepare-durable-mockup-maps-before-rendering.md) records the
Marigold extension. Its feature spec defines the new renderer configuration and
durable maps; the implementation remains Photo warp until that plan ships.
