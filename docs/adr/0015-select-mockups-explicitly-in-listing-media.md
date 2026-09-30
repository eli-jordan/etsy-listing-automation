# ADR-0015: Select mockups explicitly in listing media

Status: accepted.

A listing's media entries explicitly name any existing mockup template; there is no garment-profile registry, implicit default or bare-colour shorthand. Mockups are local buyer-facing assets, so restricting them through a production profile coupled unrelated concerns. A profile may name one colour-matrix `preview_template` to help the editor judge colours, but it does not select media or decide what renders.

First recorded 2026-09-03 in [commit f8b2138](https://github.com/eli-jordan/etsy-listing-automation/commit/f8b2138bd89aeff1616043f45da8c276cb4cfc33).
