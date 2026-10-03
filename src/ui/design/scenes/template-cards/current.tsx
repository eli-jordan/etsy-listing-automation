import { Tile, TemplatesPage } from "./_TemplatesPage";

export const meta = {
  title: "Today · 2fr/1fr/1fr strip",
  viewport: "laptop",
  description:
    "Baseline: square mockups forced into one wide and two skinny 128px tiles with object-fit: cover -- each shows a slice of the middle.",
};

export default function Current() {
  return (
    <TemplatesPage
      gallery={(template) => (
        <div className="bc-card__gallery">
          {template.gallery.slice(0, 3).map((item, index) => (
            <Tile key={index} item={item} className="tc-tile--fill" />
          ))}
        </div>
      )}
    />
  );
}
