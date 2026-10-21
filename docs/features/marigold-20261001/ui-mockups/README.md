# Marigold UI mockups

Read the [UI interaction companion](../interactions.md) for each control's behavior,
differences from the current frontend, and references to the mock components and styles.

Advanced inference uses the selected dialog layout. Its launcher is inside Renderer and appears only for Marigold. See the [final dialog](inference-settings.png); the [earlier alternatives](inference/README.md) remain archived.

Design-box visibility uses option A with just the icon and switch, plus a tooltip. The [five earlier alternatives](box-controls/README.md) remain available for reference.

Option D is selected and integrated throughout the workflow. The floating dock uses **Mask** and **Unmask**. Transparent red shows excluded regions: **Red = hidden print**.

These Marver frames add the agreed controls to the current mockup-template
workbench. They retain the app's stylesheet, sidebar, template rail,
Calibrate/Preview tabs and actual draggable corner editor. They use fixture state;
they do not save templates, call a workspace API, prepare maps or implement the
production integration.

| Screenshot | State |
| --- | --- |
| [Placement and masks](edit.png) | Renderer choice, Prepare template, placement/mask tools and lighting/detail controls. |
| [Preparing](preparing.png) | Current preparation step, elapsed time, Cancel and the waiting template. |
| [Full-quality preview](preview.png) | Ready maps, the existing colour gallery, explicit Re-render and full-size viewing. |
| [Saved changes](outdated.png) | Maps ready after the automatic CPU rebuild; the existing red Re-render button marks the previous renders as stale. |
| [Multiple placements](multiple.png) | One scene with two placements; maps must finish for both before it is Ready. |
| [Failure recovery](failed.png) | Actionable error, Retry and retained authoring controls. |
| [Editing the visible mask](mask-editing.png) | Selected floating dock, Mask / Unmask brushes, red exclusions and placement box reference. |
| [Realism field help](realism-help.png) | Plain field labels with a clicked information icon showing its explanation. |
| [Advanced Marigold Settings](inference-settings.png) | Custom inference settings, matching information cards and Reset to defaults. |

The placement box positions the design; the mask hides parts of it. Edit mask automatically reveals the red overlay and floating brushes. Mask hides print; Unmask restores it. Done or Escape returns to placement and hides the overlay. There is no separate mask-visibility control. The bottom brush toolbar’s three-dot menu contains Undo brush stroke and Reset mask. Reset mask leaves placement and appearance settings unchanged.

Mask contours and brush changes are illustrative fixture geometry. They do not demonstrate model output. Realism help remains available through each field's information icon.

Preparation displays the current sequential prototype order: surface direction
(normals), garment lighting, depth, then map building. The three model predictions
are independent; map building consumes them. Concurrent GPU inference has not been
benchmarked. The previous workflow is retained as marigold-v3 on the archive board. The [round-two alternatives](controls-round-2/README.md) remain historical reference.

The photos and artwork are existing repository design fixtures. The mockup
preview is illustrative and does not demonstrate newly computed Marigold output.
The gallery shows the two available fixture colours; the remaining tiles are
omitted from the mockup.
Screenshots are 2560 × 2200 pixels, showing a 1280-pixel-wide editor with enough
vertical space to inspect all controls.

From `src/ui`, run `npx marver dev` and open the printed
URL. Select the **Marigold Mockup Templates** board; start on **placement & masks**.
Press P for play mode. Preparation, Cancel, Retry and Prepare again link fixture
frames; tabs, sliders, mask tools, search/filtering and placement handles work in
memory. The adjacent note links the ready, saved-changes and failure snapshots.

The frame sources are in
[`design/scenes/marigold/`](../../../../src/ui/design/scenes/marigold)
and the board in
[`design/boards/marigold.json`](../../../../src/ui/design/boards/marigold.json).
Nothing in production imports the design files.

For native Windows screenshot capture, set `MARVER_CHROME` to an installed Chrome
binary before starting Marver. In this session, native Chrome capture needed the
server outside the restricted process sandbox. No WSL or browser installation
was needed.

Reviewed every exported state visually, checked the editor at mobile, tablet,
laptop and monitor widths, and type-checked the new scene with its imported app
components. Marver's dark canvas setting inherits the app's existing light
stylesheet. A full keyboard walkthrough and production preparation flow were
not tested; this is a visual fixture prototype.
