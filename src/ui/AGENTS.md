# marver

This repo designs with marver. Before any design or canvas work, read design/AGENTS.md and follow it - it is binding.

## Phone layout

Phones are `(max-width: 700px)`. Anything wider is the desktop layout, which phone work leaves pixel-identical.

- Phone CSS lives only in `src/phone/<area>.css`, each file wrapped in that media query and imported last through `src/phone/index.css`.
- Phone-only markup and behaviour render behind `useIsPhone()`, which is false in jsdom, so Vitest sees the desktop DOM. Gestures go through `useSwipe` (touch only), sheets through `PhoneSheet` or `SheetGrabber`.
- Phone wording keeps each desktop sentence one text node (a single template-string expression), since splitting it into new nodes shifts its kerning on the desktop.
- Phone browser tests use the `phone_page` fixture and `swipe` from `tests/support/mobile.py`. After a swipe, use `click()` rather than `tap()`: emulated touch drops that tap's click.
