import Shell from "../template-cards/_layout";
import { Tile, TemplatesPage } from "../template-cards/_TemplatesPage";

export const meta = {
  title: "Template card - hero + thumbnail strip",
  viewport: "laptop",
  description:
    "Retired: C (fanned stack) won -- the hero made every card poster-tall.",
};

const THUMBS = 4;

export default function HeroStrip() {
  return (
    <Shell>
    <TemplatesPage
      gridClass="tc-cards--narrow"
      gallery={(template) => {
        const [hero, ...rest] = template.gallery;
        const shown = rest.slice(0, THUMBS);
        const more = rest.length - shown.length;
        return (
          <div className="tc-hero">
            {hero && <Tile item={hero} className="tc-hero__main" />}
            {rest.length > 0 && (
              <div className="tc-hero__strip">
                {shown.map((item, index) => {
                  const last = index === shown.length - 1 && more > 0;
                  return (
                    <span key={index} className="tc-hero__thumb">
                      <Tile item={item} />
                      {last && <span className="tc-more">+{more}</span>}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        );
      }}
    />
    </Shell>
  );
}
