# Mask control alternatives

Five throwaway Marver alternatives for the controls directly above the existing
template editor image. The application shell, rail, preview tabs and realism
inspector are unchanged. No winner has been selected.

The automatic cloth mask is always the starting point; no checkbox enables it.
Blue shows where printing is allowed. Remove print and Allow print edit the same
mask. Placement is the default outside mask editing; no Move placement tool is
present. Done (or Design in B) returns to the corner editor. The eye changes only
overlay visibility. Brush size, Undo and Reset operate in memory.

| Alternative | Structure | Screenshot |
| --- | --- | --- |
| A: Compact action bar | Two named brush actions; Done exits editing. Brush size and reset are disclosed only when needed. | [A](a-action-bar.png) |
| B: Editing tabs | Design and Print area modes separate placement from masking, with grouped brushes below. | [B](b-editing-tabs.png) |
| C: Single brush menu | One action dropdown says what painting will do; Done exits editing. | [C](c-brush-menu.png) |
| D: Descriptive actions | Hide print and Bring print back have short explanations underneath. | [D](d-named-actions.png) |
| E: Popover editor | A quiet Print area strip opens a compact correction panel; the panel becomes inline on mobile. | [E](e-popover-editor.png) |

All screenshots show mask editing active at 1280 × 1100 CSS pixels, exported at
2× resolution. Geometry is illustrative fixture data, not new segmentation or a
new Marigold render. No production code imports the frames.

Open Marver's **Marigold · Mask Controls** board. Frames live in
[`design/scenes/marigold-controls/`](../../../../../src/ui/design/scenes/marigold-controls).
The pre-round UI is preserved as marigold-v2 on the Archive board.

Checked the TypeScript scene and rendered every alternative at laptop, mobile,
tablet and monitor widths. A live browser check verified painting, Undo and
returning to placement in A. The alternatives share the same mask state. This
does not validate inference, persisted masks or production preparation.
