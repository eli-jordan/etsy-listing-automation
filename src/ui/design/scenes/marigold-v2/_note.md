UI mockups only. The current application shell, tabs and corner editor are reused.
Photos and artwork are existing design fixtures; the images here do not demonstrate
new renderer output or validated shared-map quality.
The Preview grid keeps the current app's tile-to-full-size interaction. Only
Bay and Berry fixture images are included here; the remaining colour tiles are
omitted from the mockup.

Start with [placement and masks](goto:marigold-v2/edit), then
[preparation](goto:marigold-v2/preparing) and [ready preview](goto:marigold-v2/preview).
Additional states show [saved changes](goto:marigold-v2/outdated),
[multiple placements](goto:marigold-v2/multiple) and [failure recovery](goto:marigold-v2/failed).
See [visible mask editing](goto:marigold-v2/mask-editing) and
[clicked field help](goto:marigold-v2/realism-help). The tinted mask is illustrative
fixture geometry; strokes, Restore and Undo update it in memory. Hiding the mask
does not change its rendering effect. The saved-changes frame is after the CPU
rebuild: maps are Ready, and the existing red Re-render button marks stale images.
The previous round is preserved as marigold-v1 on the archive board.

First Preview opening renders automatically once maps are ready. After edits,
the seller uses Re-render. Closing the browser leaves preparation running;
server restart resumes unfinished work. Readiness has no approval step.
