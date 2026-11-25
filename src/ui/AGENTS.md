# marver

This repo designs with marver. Before any design or canvas work, read design/AGENTS.md and follow it - it is binding.

## Phone layout

Phones are `PHONE_QUERY` in `src/phone/usePhone.ts`: `(max-width: 700px)`, or a phone held sideways (`PHONE_LANDSCAPE_QUERY`: a coarse pointer, landscape, at most 500px tall). Everything else is the desktop layout, which phone work leaves pixel-identical; a short desktop window has a fine pointer, so it stays desktop.

- Phone CSS lives only in `src/phone/<area>.css`, each file wrapped in that query spelled out in full and imported last through `src/phone/index.css`. `phoneQuery.test.ts` fails on any other spelling.
- Sideways-only rules (the nav rail, two-column layouts, centred sheets) go in a block under `PHONE_LANDSCAPE_QUERY` in the same area file, so portrait never sees them.
- Phone-only markup and behaviour render behind `useIsPhone()` (or `useIsPhoneLandscape()`), both false in jsdom, so Vitest sees the desktop DOM. Gestures go through `useSwipe` (touch only), sheets through `PhoneSheet` or `SheetGrabber`.
- The editor head's "⋯" sheet closes as soon as an action is picked, so an action there reports its error through `HeadAlert` (`pages/editor/HeadAlert.tsx`), which a phone shows under the head. Something fixed-position inside a tab (a toast) goes on `document.body` on a phone: the tab swipe's transform would carry it along.
- Phone wording keeps each desktop sentence one text node (a single template-string expression), since splitting it into new nodes shifts its kerning on the desktop.
- Phone browser tests use the `phone_page` fixture (`phone_landscape_page` sideways) and `swipe` from `tests/support/mobile.py`. After a swipe, use `click()` rather than `tap()`: emulated touch drops that tap's click.
