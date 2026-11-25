# marver

This repo designs with marver. Before any design or canvas work, read design/AGENTS.md and follow it - it is binding.

## Phone layout

Phones are `PHONE_QUERY` in `src/phone/usePhone.ts`: `(max-width: 700px)`, or a phone held sideways (`PHONE_LANDSCAPE_QUERY`: a coarse pointer, landscape, at most 500px tall). Everything else is the desktop layout, which phone work leaves pixel-identical; a short desktop window has a fine pointer, so it stays desktop.

- Phone CSS lives only in `src/phone/<area>.css`, each file wrapped in that query spelled out in full and imported last through `src/phone/index.css`. `phoneQuery.test.ts` fails on any other spelling.
- Sideways-only rules (the nav rail, two-column layouts, centred sheets) go in a block under `PHONE_LANDSCAPE_QUERY` in the same area file, so portrait never sees them.
- Phone-only markup and behaviour render behind `useIsPhone()` (or `useIsPhoneLandscape()`), both false in jsdom, so Vitest sees the desktop DOM. Sheets go through `PhoneSheet` or `SheetGrabber`.
- Every swipe goes through one of two modules in `src/phone/`, which own the motion so every page feels the same. Never write transforms, timers or a reduced-motion check for a gesture in a page, and never import `useSwipe` outside `phone/` (lint refuses it).
  - `usePager(zone, { items, current, onPick })` for a sideways swipe between items in order: editor tabs, Admin sections, the template switcher, the Lightbox's pictures. It follows the finger 1:1, resists past either end, slides out in 110ms, picks, and slides the new item in over 200ms whenever `current` changes. It returns `previous` and `next` for arrows. Options: `moves` (another element moves), `follow` (a share of the finger, for a small element between arrows), `enabled`.
  - `useSheetDrag(zone, { onDismiss })` for pull down to dismiss: every sheet (through `SheetGrabber`), the deploy drawer, the Lightbox's close. It follows down 1:1 and slides out in 180ms. Options: `moves`, `fade`, `grow` (upward drags, for the deploy drawer), `enabled`.
  - Both are phone and touch only, so a desktop page can mount them unconditionally. Both honour `prefers-reduced-motion`, acting at once. Test a new caller's wiring in a browser test. The motion itself is covered by `usePager.test.tsx` and `useSheetDrag.test.tsx`, which use `src/test/touch.ts`.
- Phone wording keeps each desktop sentence one text node (a single template-string expression), since splitting it into new nodes shifts its kerning on the desktop.
- Phone browser tests use the `phone_page` fixture (`phone_landscape_page` sideways) and `swipe` from `tests/support/mobile.py`. After a swipe, use `click()` rather than `tap()`: emulated touch drops that tap's click.
