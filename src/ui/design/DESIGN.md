# Listings UI

Source of truth: `src/index.css`; `design/theme.css` imports it unchanged for canvas frames.

- Ground: warm paper `--color-bg`; surfaces are a slightly deeper oat `--color-surface`.
- Ink: near-black `--color-text`, with divider and muted text derived from it rather than new greys.
- Primary accent: clay orange `--color-accent` marks actions, selection, and unfinished work.
- Settled or successful state: restrained sage `--color-accent-2`; danger is warm brick red.
- Type: Caprasimo carries headings and buttons; Figtree is the clear, compact working voice.
- Scale: 42 / 32 / 25 / 20px heading steps; 15px body copy with generous 1.55 line height.
- Spacing follows the 4.4px-based `--space-*` rhythm; avoid one-off gaps when a token fits.
- Inputs, buttons, and structural cards use a crisp 4px radius; tags remain fully pill-shaped.
- Borders are quiet, ink-derived dividers; elevation is soft and ink-tinted, not glossy.
- Copy is practical and reassuring: state the next action, explain risk plainly, and avoid marketplace hype.
- Both light and dark canvas modes are available; frames use semantic tokens so the chosen mode can carry them.
