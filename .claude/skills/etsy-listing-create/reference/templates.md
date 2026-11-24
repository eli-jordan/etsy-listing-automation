# Mockup templates for Comfort Colors 1717

What the shop's finished listings use, and the scenes known to need help. New templates appear over time, so list them with `ls $ROOT/mockup-templates`.

## Variation template and hero, by section

A variation template needs a photo in every colour. Four have one: `cc1717-red-shirt-flat-lay`, `cc1717-folded-with-hat-and-leaf`, `cc1717-hanging-on-fence` and `cc1717-hanging-under-umbrella`. Rotate through a section's choices across the batch rather than giving every listing the same one, and match each listing's template to its art.

| Section | Variation templates to rotate | Hero |
|---|---|---|
| Christmas | `cc1717-red-shirt-flat-lay`, then the non-festive ones for variety | the variation template in the strongest colour |
| Geek Humor | `cc1717-folded-with-hat-and-leaf`, `cc1717-hanging-on-fence`, `cc1717-hanging-under-umbrella` | usually black or white |
| Artistic | `cc1717-hanging-on-fence`, `cc1717-hanging-under-umbrella`, `cc1717-folded-with-hat-and-leaf` | the colour the art reads best on at thumbnail size |

How to match them:

- `hanging-on-fence` has a grass backdrop that suits nature and animal art, but stretches art 1.2 times.
- `hanging-under-umbrella` is a sunny beach shot that suits ocean, travel and summer art. It stretches art least (about 1.06), so it's the best variation for round art. A diagonal shadow crosses the chest, so check that fine linework still reads.
- `folded-with-hat-and-leaf` stretches art most (1.32), and tall art runs into its hat and necklace, so give it short or wide art.

The flat lay, `cc1717-woman-with-peace-sign-and-mug` and `cc1717-woman-on-white-sofa` show stockings, fairy lights, a tree or a reindeer slipper, so keep them to Christmas.

The hero is the variation template in 28 of the shop's 34 listings.

## Lifestyle scenes

Pick scenes for the audience the brief names, and vary the colours across them.

- **Christmas** leans on women and seasonal scenes: `woman-by-christmas-tree`, `woman-with-peace-sign-and-mug`, `woman-on-white-sofa`, `woman-with-mug-and-blanket`, `woman-in-elevator`, `woman-in-cardigan-by-tree`, plus one or two men, `man-with-tattoos-standing` or `man-sitting-with-hat-and-glasses`.
- **Artistic** uses `man-with-tattoos-standing`, `woman-holding-a-bag`, `woman-with-oversize-fit`, `woman-in-elevator`, `man-sitting-with-hat-and-glasses`, `woman-sitting-cross-legged`, `man-sitting-in-white-kitchen`, `man-at-backyard-cookout-grill` and `woman-mirror-selfie-sunglasses`. Leave `woman-in-elevator` off round art, such as a globe or an ensō circle.
- **Geek Humor** leans on men: `man-sitting-with-hat-and-glasses`, `man-with-sunglasses-against-blue-tiles`, `man-with-tattoos-standing`, with women in `woman-holding-a-bag`, `woman-with-oversize-fit` and `woman-sitting-cross-legged`.

Every name above takes the `cc1717-` prefix.

## Scenes that need help

| Template | What happens | Usual fix |
|---|---|---|
| `cc1717-man-sitting-with-hat-and-glasses` | Tall art sits low on the chest. | Raise it 7 to 10%: `:1:-0.08` |
| `cc1717-folded-with-hat-and-leaf` | Tall art runs into the hat and necklace. | Use `cc1717-hanging-on-fence` for the variation |
| `cc1717-red-shirt-flat-lay` | The box sits about 2% right of centre. | `:1:0:-0.02` when it shows |
| Lifestyle scenes generally | Short, wide art, such as one line of text over a row of figures, can sit high. Judge each scene, because a band on the upper chest is often right. | Move it down 5 to 9% where it looks high |

## Stretch

The renderer fills each template's box with the design without keeping its shape. Most boxes are wider than the 4500 x 5400 designs, so art looks wider than it prints. Text hides this, but a circle shows it as an oval. For round badges, emblems and circles, prefer the scenes near 1.0, and leave the worst off.

| Stretch | Templates |
|---|---|
| About 1.0 | `man-with-tattoos-standing`, `man-sitting-in-white-kitchen`, `man-at-backyard-cookout-grill`, `woman-mirror-selfie-sunglasses`, `woman-holding-a-bag`, `woman-with-oversize-fit`, `woman-on-white-sofa` |
| 1.06 to 1.10 | `hanging-under-umbrella`, `man-sitting-with-hat-and-glasses`, `woman-with-peace-sign-and-mug`, `woman-with-mug-and-blanket`, `red-shirt-flat-lay` |
| 1.11 to 1.14 | `woman-in-elevator`, `woman-in-cardigan-by-tree`, `woman-sitting-cross-legged`, `man-with-sunglasses-against-blue-tiles` |
| 1.20 or more | `hanging-on-fence`, `woman-by-christmas-tree`, `folded-with-hat-and-leaf` (1.32) |

## Colours that photograph differently

- Ivory looks tan on the tattoos and flat-lay photos and near white elsewhere.
- Mustard looks lemon yellow on `man-sitting-with-hat-and-glasses`.
- Chambray can look washed out on the flat lay, so check it before making it the hero.
