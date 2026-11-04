# Recolour the t-shirt: {colour}

Edit the photo `{source}` with your built-in image generation tool. 
Open the source with your image viewer first so the generator edits that photo rather than inventing a new one.

## The edit

Recolour **only the t-shirt** to the Comfort Colors 1717 colour **{colour}**, hex **{hex}**. 
Keep everything else in the image exactly the same.
Keep the shirt's outline exactly as in the source.

## Output

Save the result as a square PNG at `{output}`, with the same framing as the source. 
Keep the generator's resolution; the run's assemble step resizes it to 2048 x 2048.

## Check before handing back

Open the result beside the source and confirm:

- the whole shirt is {colour}, sleeves, collar and hem included, with no patches of the old colour;
- nothing outside the shirt moved or changed: face, hands, pose, background and crop line up with the source;

Regenerate when a check fails, up to three attempts in all, and keep the best. 
Reply with one line: the output path, and any check the saved image still fails.
