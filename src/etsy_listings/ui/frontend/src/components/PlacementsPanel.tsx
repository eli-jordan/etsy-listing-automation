import type { BoundingBox, Placement } from "../types";

interface Props {
  placements: Placement[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  onChange: (placements: Placement[]) => void;
}

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

/**
 * Add/duplicate/delete/select for a `multiple`-kind template's placements --
 * the ergonomic core of calibrating a many-garment chart. Duplicate-and-offset
 * (copy the selected box, shifted by its own width) is what makes calibrating
 * twelve near-identical flat-lays tractable instead of dragging four handles
 * twelve times over.
 */
export function PlacementsPanel({ placements, selectedIndex, onSelect, onChange }: Props) {
  function addPlacement() {
    const source = placements[selectedIndex] ?? placements[placements.length - 1];
    const bounding_box = source ? offsetBox(source.bounding_box) : DEFAULT_BOX;
    onChange([...placements, { colour: "", bounding_box }]);
    onSelect(placements.length);
  }

  function duplicateSelected() {
    const source = placements[selectedIndex];
    if (!source) return;
    const copy: Placement = { ...source, bounding_box: offsetBox(source.bounding_box) };
    const next = [...placements];
    next.splice(selectedIndex + 1, 0, copy);
    onChange(next);
    onSelect(selectedIndex + 1);
  }

  function deleteSelected() {
    if (placements.length === 0) return;
    onChange(placements.filter((_, i) => i !== selectedIndex));
    onSelect(Math.max(0, selectedIndex - 1));
  }

  function updateColour(index: number, colour: string) {
    onChange(placements.map((p, i) => (i === index ? { ...p, colour } : p)));
  }

  function updateArtwork(index: number, artwork: string) {
    onChange(placements.map((p, i) => (i === index ? { ...p, artwork: artwork || null } : p)));
  }

  return (
    <fieldset className="placements-panel">
      <legend>Placements</legend>
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
            <input
              aria-label={`Colour for placement ${index + 1}`}
              value={placement.colour}
              onChange={(e) => updateColour(index, e.target.value)}
              placeholder="colour slug"
            />
            <input
              aria-label={`Artwork override for placement ${index + 1}`}
              value={placement.artwork ?? ""}
              onChange={(e) => updateArtwork(index, e.target.value)}
              placeholder="artwork override (optional)"
            />
          </li>
        ))}
      </ul>
      <div className="placements-panel__actions">
        <button type="button" onClick={addPlacement}>
          Add placement
        </button>
        <button type="button" onClick={duplicateSelected} disabled={placements.length === 0}>
          Duplicate &amp; offset selected
        </button>
        <button type="button" onClick={deleteSelected} disabled={placements.length === 0}>
          Delete selected
        </button>
      </div>
    </fieldset>
  );
}
