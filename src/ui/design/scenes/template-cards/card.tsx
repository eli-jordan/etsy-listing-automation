import { Tile, TemplatesPage } from "./_TemplatesPage";

export const meta = {
  title: "Template card · fanned stack (shipped)",
  viewport: "laptop",
  description:
    "The first mockup whole, on a soft stage, with the next two fanned behind it like a deck of prints and a count chip. Reads as 'a gallery'; one image is simply one print.",
};

export default function FannedStack() {
  return (
    <TemplatesPage
      gallery={(template) => {
        const deck = template.gallery.slice(0, 3);
        return (
          <div className="tc-stage">
            <div className={`tc-deck tc-deck--${deck.length}`}>
              {deck
                .map((item, index) => (
                  <Tile key={index} item={item} className={`tc-deck__card tc-deck__card--${index}`} />
                ))
                .reverse()}
            </div>
            {template.gallery.length > 1 && (
              <span className="tc-count">{template.gallery.length} items</span>
            )}
          </div>
        );
      }}
    />
  );
}
