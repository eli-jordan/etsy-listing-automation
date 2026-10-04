# Marigold UI interactions

Companion to the [approved mockups](ui-mockups/README.md) and [integration spec](spec.md).
This describes the intended product interactions, their differences from the
current frontend in this checkout, and where to find their visual implementation.
The [technical design](plan.md) defines persistence,
worker and HTTP contracts. Labels in older screenshots may still say Existing
renderer; the production label is Photo warp.
The integration spec governs lifecycle and rendering behavior. These are throwaway
Marver frames: local interactions and linked snapshots are not a working backend.

## Source and style map

All links below refer to the live, selected mockups. Versioned scenes and earlier
control alternatives are historical, not implementation requirements.

| Reference | Responsibilities and useful selectors |
| --- | --- |
| [Mock screen: `_MarigoldScreen.tsx`](../../../src/ui/design/scenes/marigold/_MarigoldScreen.tsx) | `MarigoldScreen`, `prepSection`, `Status`, `Slider`, `FieldInfo`, `explanations`; workbench, preparation, placement, gallery and realism interactions. |
| [Screen styles: `_marigold.css`](../../../src/ui/design/scenes/marigold/_marigold.css) | `.mg-frame`, `.mg-status`, `.mg-progress`, `.mg-steps`, `.mg-queue`, `.mg-error`, `.mg-stage`, `.mg-mask-overlay`, `.mg-info`, `.mg-info-text`, `.mg-empty-preview`, `.mg-lightbox`. |
| [Mask controls: `_MaskToolbar.tsx`](../../../src/ui/design/scenes/marigold/_MaskToolbar.tsx) | `MaskToolbar`, `MaskBrushDock`, `MaskActions`; visibility switch, editing mode, brushes, size, undo and reset. |
| [Mask styles: `_mask-toolbar.css`](../../../src/ui/design/scenes/marigold/_mask-toolbar.css) | `.mg-maskbar`, `.mg-box-control`, `.mg-box-switch`, `.mg-mask-dock`, `.mg-mask-size`, `.mg-mask-menu`; selected brush, floating dock and menu presentation. |
| [Settings dialog: `_InferenceSettings.tsx`](../../../src/ui/design/scenes/marigold/_InferenceSettings.tsx) | `InferenceSettings`, `defaults`, `fields`; saved/draft values, help cards, reset, focus and dismissal. |
| [Dialog styles: `_inference.css`](../../../src/ui/design/scenes/marigold/_inference.css) | `.mi-launch`, `.mi-backdrop`, `.mi-dialog`, `.mi-sheet`, `.mi-dialog-body`, `.mi-field`, `.mi-info-card`, `.mi-info-highlight`, `.mi-reset`. Contains unused styles from earlier options; use the selected dialog only. |
| [Shared production stylesheet](../../../src/ui/src/index.css) | Existing `.app__preview-bar`, `.app__bar-field`, `.template-rail__*`, `.realism__*`, `.preview-grid__*`, `.btn-secondary` and `.btn-danger`. Reuse these rather than introducing another visual system. |
| [Fixtures](../../../src/ui/design/scenes/marigold/_fixtures.ts) and [board](../../../src/ui/design/boards/marigold.json) | Example photos, boxes and templates; frame navigation and board composition. |

## 1. Workbench, navigation and template selection

See [placement editor](ui-mockups/edit.png), [preparing](ui-mockups/preparing.png) and [ready preview](ui-mockups/preview.png).

Keep the application sidebar, template rail, template heading and Calibrate/Preview
tabs. Search filters templates by name; kind filters select Colour Matrix, Multiple
or Single. Selecting a template opens its editor. Add preparation status to the
template row, page heading and Renderer section, all derived from the same state.
The mock adds All / Needs maps / Ready filters and a preparation queue beneath the
template list. Preparing another template must not prevent browsing or editing.

The current rail is [TemplateRail](../../../src/ui/src/components/TemplateRail.tsx).
The mock's search/filter controls live in `MarigoldScreen`, using the existing
`template-rail__*` styles plus `.mg-rail-state` and `.mg-queue`.
Counts and queued entries in the mock are fixtures; production must derive them.
An existing-renderer template has no map-preparation requirement; it should not be
presented as broken merely because it has no Marigold maps.

There is no new template review or approval gate. Ready means its required maps
are current. Listing review remains the place to approve listing images.

## 2. Calibrate, Preview and the design selector

The selected design selector sits beside **Calibrate / Preview**, visible in both
views. Changing it changes the artwork used to inspect the template, not the
template's saved configuration or the prepared maps. Preserve the existing
bundled-design and uploaded-design capabilities when integrating this compact
selector; the mock's three fixed options are illustrative.

There is a baseline discrepancy worth preserving explicitly: this checkout's
[EditorShell](../../../src/ui/src/editors/EditorShell.tsx)
places [TestDesignPicker](../../../src/ui/src/components/TestDesignPicker.tsx)
in the right panel. The agreed design places it beside the tabs, matching the
user's requested application layout. Do not copy the old right-panel location.
The mock uses `.app__preview-bar` and `.app__bar-field` from the shared stylesheet.

**Calibrate** shows an immediate, simple artwork overlay for positioning and mask
editing. Dragging and slider changes must not wait for full Marigold rendering.
Its caption explains that folds and lighting are visible in Preview. The current
[usePreview](../../../src/ui/src/hooks/usePreview.ts) and
EditorShell use small server-rendered previews; the Marigold path changes this to
a fast placement overlay.

**Preview** remains the full-quality view. Preserve the current first-open render
behavior, then explicit **Re-render** after changes. Switching back and forth must
not discard completed previews or trigger another render by itself. A design
change also makes an existing result stale rather than silently regenerating it.
For Marigold, initial rendering is gated on current maps.

## 3. Renderer selection

Add a per-template **Renderer** dropdown: Photo warp or Marigold. Photo warp
preserves the current rendering behaviour in the new YAML format. Selecting
Marigold reveals Template maps, preparation actions and **Advanced settings**.
Selecting Photo warp hides those Marigold-specific controls and uses the
existing rendering controls and behavior. There is no silent renderer fallback.

Source: `prepSection` in the mock screen, styled by `.mg-preparation`, `.mg-row`
and `.mg-status`. `InferenceSettings` is mounted inside the Marigold conditional.
The mock demonstrates that conditional launcher, but does not implement complete
switching between the two renderers' editors; it leaves other Marigold controls
on screen. Production must retain the current editor for the existing renderer.

Persist selection as `renderer.type` and settings as `renderer.config`. The new
format replaces the old format outright. Keep the last saved inactive renderer
settings so switching back restores them. Switching never starts preparation.

## 4. Prepare template and readiness

| State / action | Intended interaction |
| --- | --- |
| Needs preparation | Show **Prepare template**. Authoring remains available; full-quality Marigold rendering is blocked. |
| Prepare template | Persist the required configuration and enqueue preparation explicitly. This is the action that authorizes model inference; opening Preview does not. |
| Queued | Show that the template is waiting, with Cancel available. One preparation job runs at a time. |
| Preparing | Show current step, elapsed time and progress through Surface direction, Garment lighting, Depth and Build maps. Show **Cancel preparation**. |
| Cancel preparation | Stop or dequeue the job. Keep valid completed work reusable; an incomplete preparation does not become Ready. |
| Ready | Current maps exist for all required placements. Enable full-quality rendering and offer **Prepare again**. No template approval action is required. |
| Failed | Show an actionable reason and **Retry preparation**. Retain editing controls and reuse valid completed work on retry. |
| Saved calibration requiring only a CPU rebuild | Automatically rebuild from cached predictions after save. Show the updating state; do not run model inference. |
| Missing predictions or changed inference settings | Mark preparation needed and wait for explicit Prepare template. |

See [preparing](ui-mockups/preparing.png), [failure](ui-mockups/failed.png) and [multiple placements](ui-mockups/multiple.png).
Source: `prepSection`, `Status`, `.mg-progress`, `.mg-steps`, `.mg-step--done`,
`.mg-step--active`, `.mg-error` and `.mg-queue`.

The displayed steps follow the prototype's sequential execution. The three model
predictions are independent, but map building consumes them. These screens do
not promise concurrent GPU inference or a preparation duration.

Closing the UI leaves server work running. On server restart, unfinished work
resumes, reusing completed valid work. These are integration requirements, not
behaviors demonstrated by the static queue and elapsed-time fixtures.

Colour-matrix templates prepare the fixed main/first photo once and share its
preparation across colours. Browsing colours never changes that reference.
There is no reference picker, per-colour preparation or exceptions UI. Incompatible
photos require separate templates. Single and multiple templates use their main
scene image. Multiple-placement scenes become Ready only when every placement
is prepared; a failed or stale required placement blocks the scene.

## 5. Placement and design-box visibility

Normal interaction is placement editing; there is no Move placement tool. Drag
the corners to reshape the quadrilateral, drag the box to move it and Shift-drag
to scale, retaining the existing
[QuadEditor](../../../src/ui/src/components/QuadEditor.tsx)
behavior. Multiple-placement scenes retain placement selection and individual boxes.

Above the photo, the bounding-box icon and switch replace the existing outline
checkbox. There is no visible text label. The tooltip says Show design box or
Hide design box; the accessible switch name is Show design box. Turning it off
hides box outlines and handles, not artwork and not the mask. This preference
does not alter maps or renders. The switch remains usable during mask editing.

Source: `MaskToolbar` and the `outlines` state passed into `QuadEditor` in the
mock screen. Styles: `.mg-box-control`, `.mg-box-switch` and the existing
`quad-editor__*` styles. See [editor](ui-mockups/edit.png) and [multiple-mask view](ui-mockups/multiple-mask.png).

## 6. Edit mask, brushes and recovery

This is new to the current editor. The placement box determines where the design
goes. The mask hides portions behind foreground objects, in gaps or outside the
cloth, including regions inside that box. It does not reshape folds.

1. **Edit mask** enters brush mode and automatically reveals transparent red
   exclusions. The toolbar displays **Red = hidden print**, and a floating dock
   appears at the bottom of the photo. Placement dragging is suspended.
2. **Mask** hides print in brushed areas. **Unmask** restores print in brushed
   areas. The selected brush is visibly active. Brush size changes the brush
   diameter; the mock shows an 8–80 px slider and numeric value.
3. The dock's **three-dot menu** contains **Undo brush stroke** and **Reset mask**.
   Undo removes the latest whole stroke and is disabled with no brush history.
   Reset returns to the automatically proposed mask, discarding manual mask edits.
   Neither action resets placement or print-realism settings.
4. **Done** or **Escape** exits brush mode, hides the red overlay and dock, and
   returns to ordinary placement editing. This retains mask edits; Done is not
   a separate approval step or a request to run inference.

There is no Use automatic cloth mask checkbox, separate Show mask checkbox,
mask-visibility eye button, or separate foreground-exclusion layer in this UI.
The automatic mask is the starting mask the user edits.

Save commits the configuration and flattened mask together. Automatic and edited
masks are durable template PNGs at locations derived by Workspace. No mask path
appears in YAML. Only multiple placements have explicit IDs. Mask coordinates
stay attached to the photo when the placement moves. Brush history is cached;
clearing cache loses historical Undo but preserves the saved mask and Reset.
Done and Escape retain draft strokes until the editor saves them.

See [mask editing](ui-mockups/mask-editing.png). Source: `MaskToolbar`, `MaskBrushDock`,
`MaskActions`; the screen's `strokes`, `brushHistory`, pointer handlers and SVG
mask. Styles: `.mg-maskbar`, `.mg-mask-legend`, `.mg-mask-dock`, `.mg-mask-menu`,
`.mg-stage--mask` and `.mg-mask-overlay`. Red transparency is also set directly
on the SVG in the screen component. The fixture contour and circular strokes
illustrate interaction, not inferred segmentation or a production brush engine.

## 7. Print realism and information icons

The existing [PrintRealismPanel](../../../src/ui/src/components/PrintRealismPanel.tsx)
offers Follow fabric wrinkles, Pick up garment shading, Natural/Rich/Airy shading
presets and raw displace/blend values. Keep that panel for Existing renderer.
For Marigold, use these controls instead:

| Field | Interaction and effect | Mock default |
| --- | --- | --- |
| Lighting source | Select Prepared garment lighting or Photo-based lighting. The former uses estimated lighting; the latter derives it from the photo's brightness. | Prepared garment lighting |
| Light & shadow strength | 0–100% slider; original artwork brightness through to full cloth shading. | 100% |
| Fabric texture | 0–100% slider; smooth through to more fine cloth detail. Does not reposition the design. | 25% |
| Print shine | 0–100% slider; matte through to brighter garment reflections. | 0% |
| Reset | Restore these four appearance defaults only. | — |

Click the small information icon beside a field title to reveal its explanation.
Click again or press Escape to close it. The mock displays one explanation at a
time. Slider feedback is immediate, but a changed full-quality image still requires
Re-render. Appearance changes alone do not justify new GPU inference.

See [field help](ui-mockups/realism-help.png). Source: `explanations`, `FieldInfo`, `Slider`
and the Print realism section in the mock screen. Styles combine existing
`.realism__*` with `.mg-field-title`, `.mg-info` and `.mg-info-text`.
Depth stays enabled internally. Corrective anchors, overlap patches and solver
tuning are not part of these normal authoring controls.

## 8. Advanced Marigold Settings

See [settings dialog](ui-mockups/inference-settings.png). The **Advanced settings** button
is inside Renderer and appears only for Marigold. It opens the centered
**Advanced Marigold Settings** dialog, with the template name above the title.

| Interaction | Behavior |
| --- | --- |
| Open | Copy saved values into a draft. Focus the first numeric input. |
| Inference steps | Edit `num_inference_steps`; default 10. More denoising steps cost time and may improve results. |
| Ensemble size | Edit `ensemble_size`; default 3. More predictions can reduce inconsistent estimates at additional cost. |
| Information icon | Highlight the matching information card. Both cards are visible in the selected layout; their headings exactly match the readable field labels. |
| Documentation link | Open the relevant official Marigold documentation section in a new tab. |
| Reset to defaults | Set the draft to 10 and 3. Apply only when Save settings is pressed. |
| Save settings | Save the draft and close. Changed values invalidate the corresponding preparation; require explicit preparation, without starting inference. |
| Close × or Escape | Close without applying draft changes. Return focus to Advanced settings. |
| Tab / Shift-Tab | Keep focus within the modal while open. |

There are no quality presets, resolution or seed fields. Internal resolution and
seed retain the prototype settings. The mock input attributes allow steps 1–50
and ensemble size 1–10; these are illustrative UI bounds, not a claim about model
limits or complete validation. Production needs integer validation before saving.

Source and styles: `InferenceSettings`, `defaults`, `fields`, `.mi-dialog-body`,
`.mi-fields`, `.mi-info-card`, `.mi-info-highlight`, `.mi-reset`. The mock keeps
saved values only in component memory and shows “preparation needed” on every
save. Production must compare effective values: saving unchanged values should
not invalidate current maps. Switching renderer currently unmounts this local
mock state; that is not a requirement to discard saved template settings.

## 9. Full-quality rendering, stale results and full-size viewing

Preserve [PreviewPanel](../../../src/ui/src/components/PreviewPanel.tsx)
and [Lightbox](../../../src/ui/src/components/Lightbox.tsx)
semantics: first open renders when allowed, progress counts reflect actual jobs,
tiles open large, and subsequent changes require explicit Re-render. Keep late
responses tied to the request that produced them so they cannot masquerade as
results for a newer configuration. Retain current full-size viewing and navigation
capabilities rather than replacing them with the mock's simplified overlay.

When rendered images are stale, use the existing **red Re-render button**
(`.btn-danger`), not a new stale-render banner. Previously rendered images remain
available for inspection until replaced. Ready maps and stale images can coexist:
the [saved-changes screenshot](ui-mockups/outdated.png) shows this after a CPU rebuild.

Missing, stale or failed required maps block new Marigold renders. Explain
“Prepare the template first” and offer preparation. Do not start inference just
because the user opened Preview or attempted a listing render. Listing preview
and deployment must enforce the same scene-level gate.

Source: the mock screen's `renderStale`, `preview-grid` branch and `fullImage`
state. Styles reuse `.preview-grid__*`, `.btn-secondary` and `.btn-danger`, with
`.mg-empty-preview` and `.mg-lightbox`. The mock's two tiles, 33/33 count and
artwork overlays are fixtures, not evidence of completed full-quality renders.

## 10. Save boundaries and mock limitations

Keep the application's save behavior; these mockups do not establish a new
autosave contract. Their “Saved a moment ago” header is static. Save calibration
through the real editor, then rebuild maps on CPU when cached predictions suffice.
If new inference is necessary, require explicit preparation. Mask Done exits a
tool; Print realism Reset changes appearance; Reset mask changes the mask; dialog
Reset changes the settings draft. These four actions must not be conflated.

The current colour-matrix PreviewPanel supports an optional “Approve & mark
calibrated” action. Marigold readiness has no corresponding approval requirement;
do not insert one into its preparation flow. Existing-renderer behavior remains
outside this change unless explicitly amended in the product spec.

The following need real integration rather than copying fixture logic:

- Persistent settings and calibration, actual design selection/upload and previews.
- Background queue, cancellation, progress, recovery and readiness invalidation.
- Automatically inferred masks and per-placement map state; the multiple mock
  demonstrates two boxes but does not implement independent persisted mask data.
- Existing-renderer conditional controls and actual save/error feedback.
- Modal validation, accessible labeling and keyboard behavior verified in the
  production UI. The mock's close-button accessible label still uses the older
  “advanced inference” wording; use “Close Advanced Marigold Settings”.

Queued, CPU-rebuilding and single-scene states are described by the integration
spec but do not each have a dedicated exported screenshot. Frame links such as
Prepare, Cancel, Retry and Re-render navigate between fixtures; they do not run
those operations. The earlier screenshot review and TypeScript checks are not
end-to-end validation of the production feature.
