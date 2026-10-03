import Shell from "../template-cards/_layout";
import { Tile, TemplatesPage } from "../template-cards/_TemplatesPage";

export const meta = {
  title: "Template card - three even squares",
  viewport: "laptop",
  description:
    "Retired: C (fanned stack) won -- three small squares read as a summary, not a gallery.",
};

const SLOTS = 3;

export default function EvenSquares() {
  return (
    <Shell>
    <TemplatesPage
      gallery={(template) => {
        const shown = template.gallery.slice(0, SLOTS);
        const more = template.gallery.length - shown.length;
        return (
          <div className="tc-squares">
            {Array.from({ length: SLOTS }, (_, index) => {
              const item = shown[index];
              if (!item) return <span key={index} className="tc-squares__empty" />;
              return (
                <span key={index} className="tc-squares__cell">
                  <Tile item={item} />
                  {index === SLOTS - 1 && more > 0 && <span className="tc-more">+{more}</span>}
                </span>
              );
            })}
          </div>
        );
      }}
    />
    </Shell>
  );
}
