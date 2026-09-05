import { useId } from "react";
import type { BoundingBox, Placement, Point } from "../types";

/**
 * The bounding-box list for a `multiple`-kind template (wireframe 2a).
 *
 * Boxes are quads, not rectangles: `BoundingBox` is four corners so that
 * angled and draped photos are representable (render/config.py, PRD). The
 * wireframe draws x/y/w/h fields, which would silently flatten the skew on
 * every one of those, so the selected box exposes all four corners instead --
 * eight fields where the design asked for four. The extent readout gives back
 * the thing x/y/w/h was actually useful for.
 */

const DEFAULT_BOX: BoundingBox = [
  { x: 40, y: 40 },
  { x: 200, y: 40 },
  { x: 200, y: 200 },
  { x: 40, y: 200 },
];

function offsetBox(box: BoundingBox): BoundingBox {
  const xs = box.map((p) => p.x);
  const width = Math.max(...xs) - Math.min(...xs);
  return box.map((p) => ({ x: p.x + width, y: p.y })) as BoundingBox;
}

function extent(box: BoundingBox): { width: number; height: number } {
  const xs = box.map((p) => p.x);
  const ys = box.map((p) => p.y);
  return {
    width: Math.round(Math.max(...xs) - Math.min(...xs)),
    height: Math.round(Math.max(...ys) - Math.min(...ys)),
  };
}

/** The same rule the server uses for `TemplateSummary.status_reason`, so the
 * panel and the rail can never disagree about whether this is finished. */
export function uncolouredWarning(placements: Placement[]): string | null {
  const count = placements.filter((p) => !p.colour.trim()).length;
  if (count === 0) return null;
  const [noun, verb] = count === 1 ? ["box", "has"] : ["boxes", "have"];
  return `${count} ${noun} ${verb} no colour — can't mark calibrated yet`;
}

interface Props {
  placements: Placement[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  onChange: (placements: Placement[]) => void;
  /** Colours already in use across the workspace, offered as suggestions.
   * Suggestions and not a closed list: a `multiple` template's colours are
   * whatever the listing sells, and the calibrator does not know that yet. */
  knownColours: string[];
}

export function PlacementsPanel({
  placements,
  selectedIndex,
  onSelect,
  onChange,
  knownColours,
}: Props) {
  const listId = useId();
  const selected = placements[selectedIndex];
  const warning = uncolouredWarning(placements);

  function replaceSelected(next: Placement): void {
    onChange(placements.map((p, i) => (i === selectedIndex ? next : p)));
  }

  function addPlacement(): void {
    const source = placements[selectedIndex] ?? placements[placements.length - 1];
    const bounding_box = source ? offsetBox(source.bounding_box) : DEFAULT_BOX;
    onChange([...placements, { colour: "", bounding_box, artwork: null }]);
    onSelect(placements.length);
  }

  function duplicateSelected(): void {
    if (!selected) return;
    const copy: Placement = { ...selected, bounding_box: offsetBox(selected.bounding_box) };
    const next = [...placements];
    next.splice(selectedIndex + 1, 0, copy);
    onChange(next);
    onSelect(selectedIndex + 1);
  }

  function deleteSelected(): void {
    if (!selected) return;
    onChange(placements.filter((_, i) => i !== selectedIndex));
    onSelect(Math.max(0, selectedIndex - 1));
  }

  function bringToFront(): void {
    if (!selected) return;
    const next = placements.filter((_, i) => i !== selectedIndex);
    next.push(selected);
    onChange(next);
    onSelect(next.length - 1);
  }

  function updateCorner(corner: number, axis: "x" | "y", raw: string): void {
    const value = Number(raw);
    // A half-typed "-" or a stray letter must not write NaN into the config;
    // the field keeps the text and the box keeps its last good geometry.
    if (!selected || raw.trim() === "" || Number.isNaN(value)) return;
    const box = selected.bounding_box.map((p, i) =>
      i === corner ? ({ ...p, [axis]: value } as Point) : p,
    ) as BoundingBox;
    replaceSelected({ ...selected, bounding_box: box });
  }

  return (
    <section className="placements-panel">
      <div className="placements-panel__head">
        <h3 className="placements-panel__heading">{`Bounding boxes · ${placements.length}`}</h3>
        <button type="button" className="btn btn-primary placements-panel__add" onClick={addPlacement}>
          + Add
        </button>
      </div>

      <ul className="placements-panel__list">
        {placements.map((placement, index) => (
          <li
            key={index}
            className={
              index === selectedIndex
                ? "placements-panel__item placements-panel__item--active"
                : "placements-panel__item"
            }
            onClick={() => onSelect(index)}
          >
            <span className="placements-panel__name">
              {`${index + 1} · ${placement.colour.trim() || "new box"}`}
            </span>
          </li>
        ))}
      </ul>

      {selected && (
        <div className="placements-panel__detail">
          <label className="placements-panel__field">
            <span>Colour</span>
            <input
              className="input"
              list={listId}
              value={selected.colour}
              placeholder="assign colour…"
              onChange={(e) => replaceSelected({ ...selected, colour: e.target.value })}
            />
          </label>
          <datalist id={listId}>
            {knownColours.map((colour) => (
              <option key={colour} value={colour} />
            ))}
          </datalist>

          <div className="placements-panel__corners">
            {selected.bounding_box.map((point, corner) => (
              <div key={corner} className="placements-panel__corner">
                <span className="placements-panel__corner-label">{`Corner ${corner + 1}`}</span>
                <input
                  className="input"
                  aria-label={`Corner ${corner + 1} x`}
                  defaultValue={String(Math.round(point.x))}
                  onChange={(e) => updateCorner(corner, "x", e.target.value)}
                />
                <input
                  className="input"
                  aria-label={`Corner ${corner + 1} y`}
                  defaultValue={String(Math.round(point.y))}
                  onChange={(e) => updateCorner(corner, "y", e.target.value)}
                />
              </div>
            ))}
          </div>

          <p className="placements-panel__extent">
            {`${extent(selected.bounding_box).width} × ${extent(selected.bounding_box).height}`}
          </p>

          <div className="placements-panel__actions">
            <button type="button" onClick={duplicateSelected}>
              Duplicate
            </button>
            <button type="button" onClick={bringToFront}>
              Bring to front
            </button>
            <button type="button" onClick={deleteSelected}>
              Delete ⌫
            </button>
          </div>
        </div>
      )}

      {warning && <p className="placements-panel__warn">{warning}</p>}
    </section>
  );
}
