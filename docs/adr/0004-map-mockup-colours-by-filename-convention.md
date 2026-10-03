# ADR-0004: Map mockup colours by filename convention

Status: accepted.

A colour-matrix photo is named by the slugified Printify colour, with a sparse exceptions file for names the convention cannot express. A shared vendor prefix is accepted only when exactly one filename ends in the known slug's hyphen segments; ambiguity is refused. This avoids maintaining a full colour mapping table. Multiple and single templates use `scene.png`; callers obtain the resolved photo from `Workspace` rather than reproducing the convention.

First recorded 2026-09-03 in [commit 086df20](https://github.com/eli-jordan/etsy-listing-automation/commit/086df2096d7b293ccbad394c9891b661a9a194b9).
