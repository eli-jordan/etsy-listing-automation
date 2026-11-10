import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CaretUpIcon } from "@phosphor-icons/react/dist/csr/CaretUp";
import { useState } from "react";
import type { DriftedField } from "./comparison";
import { driftRowId } from "./driftRowAnchor";
import { diffSegments, driftVerdict, paragraphGroups, type DiffSide } from "./driftText";

/**
 * A drifted field's row in the comparison. Long copy opens in place to show
 * only what differs; a short value already fits in its row.
 */

function Mark({ field }: { field: DriftedField }) {
  return (
    <span className="dv-drift-mark">
      {field.source === "etsy" ? "Changed on Etsy" : "Changed in Printify"}
    </span>
  );
}

function RowLabel({ label, action }: { label: string; action?: React.ReactNode }) {
  return (
    <div className="dv-block__label">
      <span className="dv-eyebrow">{label}</span>
      {action}
    </div>
  );
}

function DiffText({ live, after, side }: { live: string; after: string; side: DiffSide }) {
  return diffSegments(live, after, side).map((segment, index) => (
    <span key={index} className={segment.kind === "same" ? undefined : `dv-${segment.kind}`}>
      {segment.text}
    </span>
  ));
}

function Comparison({ field, onClose }: { field: DriftedField; onClose: () => void }) {
  const [showAll, setShowAll] = useState(false);
  const where = field.source === "etsy" ? "on Etsy" : "in Printify";

  return (
    <section
      id={driftRowId(field.key)}
      className="dv-lens"
      aria-label={`${field.label} compared with this plan`}
    >
      <div className="dv-lens__band">
        <span className="dv-eyebrow">{field.label}</span>
        <span className="dv-lens__verdict">{driftVerdict(field.live, field.after, where)}</span>
        <button type="button" className="dv-textbtn" onClick={onClose}>
          Close <CaretUpIcon aria-hidden="true" />
        </button>
      </div>
      {paragraphGroups(field.live, field.after).map((group, index) => {
        if (group.type === "diff") {
          return (
            <div key={index} className="dv-row dv-row--text">
              <div className="dv-cell">
                <DiffText live={group.live} after={group.after} side="live" />
              </div>
              <div className="dv-cell">
                <DiffText live={group.live} after={group.after} side="after" />
              </div>
            </div>
          );
        }
        if (showAll) {
          return group.paragraphs.map((text, paragraph) => (
            <div key={`${index}-${paragraph}`} className="dv-row dv-row--text dv-row--quiet">
              <div className="dv-cell">{text}</div>
              <div className="dv-cell">{text}</div>
            </div>
          ));
        }
        const count = group.paragraphs.length;
        return (
          <button key={index} type="button" className="dv-fold" onClick={() => setShowAll(true)}>
            {count} identical {count === 1 ? "paragraph" : "paragraphs"}. Show them
          </button>
        );
      })}
    </section>
  );
}

export function DriftTextRow({
  field,
  open,
  onToggle,
}: {
  field: DriftedField;
  open: boolean;
  onToggle: () => void;
}) {
  if (open) return <Comparison field={field} onClose={onToggle} />;
  const valueClass = field.path === "title" ? "dv-title" : "dv-clamp";

  return (
    <div id={driftRowId(field.key)} className="dv-row dv-row--drift">
      <div className="dv-cell">
        <RowLabel label={field.label} action={<Mark field={field} />} />
        <div className={valueClass}>{field.live}</div>
      </div>
      <div className="dv-cell">
        <RowLabel
          label={field.label}
          action={
            // Stretched over the row, so the whole field is the click target.
            <button
              type="button"
              className="dv-drift-toggle"
              aria-expanded={false}
              aria-label={`Compare ${field.label}`}
              onClick={onToggle}
            >
              Compare
              <CaretDownIcon aria-hidden="true" />
            </button>
          }
        />
        <div className={valueClass}>{field.after}</div>
      </div>
    </div>
  );
}

export function DriftValueRow({ field }: { field: DriftedField }) {
  return (
    <div id={driftRowId(field.key)} className="dv-row dv-row--drift">
      <div className="dv-cell">
        <RowLabel label={field.label} action={<Mark field={field} />} />
        <div className="dv-setting">{field.live}</div>
      </div>
      <div className="dv-cell">
        <RowLabel label={field.label} />
        <div className="dv-setting">{field.after}</div>
      </div>
    </div>
  );
}
