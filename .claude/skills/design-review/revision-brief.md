# Revise __SLUG__: revision __N__

The seller reviewed this design and tagged it Iterate, with this note:

> __NOTE__

The design folder is `__FOLDER__`. Touch only this folder, because other agents are revising its sibling folders at the same time.

## Files

- `prompt.md`: the brief the design came from: its concept, exact text, style, palette, shirt colour and print rules.
- `out\__FILE__`: the current design, a 4500x5400 RGBA PNG with a transparent background. Image viewers flatten transparency, so look at it composited on the shirt colour, __SHIRT__.

`generate_designs.py` below means `uv run python .claude/skills/etsy-research-design/generate_designs.py`, run from `__REPO__`.

## Steps

1. **Archive** the current print with `generate_designs.py archive "__FOLDER__"`, which copies it to `rejected\`.
2. **Research first** when the note touches a fact or a symbol. Check any claim printed on the design (a date, a patent, a "banned" book) against primary sources, and any cultural symbol against two references. Write what you found, with links, to `research.md`.
3. **Make the change**, and change only what the note asks. The concept, style, palette, shirt colour and everything the note doesn't mention stay as they are.
   - A **mechanical** change (removing text or an outline, moving a block, recolouring a shape): edit `out\__FILE__` in place with Pillow through `uv run python`, so nothing else moves. Keep scratch files outside the design folder.
   - **Anything else**: write the change as a short instruction to an image editor in `raw\revision-__N__-change.txt`, then run `generate_designs.py revise "__FOLDER__" "__FOLDER__\raw\revision-__N__-change.txt"`. It sends the current print to Nano Banana 2.1 on Kie.ai as an image edit and cuts the result into `out\__FILE__`. Each attempt costs 6 credits; stop after three.
4. **Check** with `generate_designs.py check "__FOLDER__"`, which must print `ok`. Then look at the print on its shirt colour. Read every word on it letter by letter, confirm there is no stray or garbled text, and confirm the change is the one the note asked for.
5. **Update `prompt.md`** so it describes the design as it now is: the text sentence (`The artwork has no text, letters, numbers, signatures or watermarks.` when the text is gone) and the style line. Add a final `## Revision __N__` section that quotes the seller's note and says what you changed and why. The review page reads this file.

## Reply

- the file path;
- what you changed, in one or two sentences;
- the exact text now on the design, or "no text";
- any research findings, with source links.
