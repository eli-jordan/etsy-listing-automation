import { CaretLeftIcon } from "@phosphor-icons/react/dist/csr/CaretLeft";
import { CaretRightIcon } from "@phosphor-icons/react/dist/csr/CaretRight";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useState, type ReactNode } from "react";
import { ClosedRow, Compare, DriftIcon, DriftPage, SettingRow, SettledRows } from "./_DriftPage";
import { DiffText, foldLabel, groupParagraphs } from "./_driftDiff";
import { description, driftedFields, shipping, title, type DriftedField } from "./_fixtures";

export const meta = {
  title: "B · History inspector",
  viewport: "monitor",
  description: "Not chosen, A won. A short warning opens a docked inspector that steps through drifted fields and shows last applied, on Etsy now and after apply as one history.",
};

function Stop({ state, label, note, children }: { state: "past" | "now" | "next"; label: string; note: string; children?: ReactNode }) {
  return (
    <li className={`dd-stop dd-stop--${state}`}>
      <div className="dd-stop__head">
        <strong>{label}</strong>
        <span>{note}</span>
      </div>
      {children && <div className="dd-stop__body">{children}</div>}
    </li>
  );
}

function Differences({ field, side, from, to }: { field: DriftedField; side: "from" | "to"; from: string; to: string }) {
  const [showAll, setShowAll] = useState(false);
  return groupParagraphs(from, to).map((group, index) => {
    if (group.type === "diff") {
      return (
        <p key={index} className={field.id === "description" ? "dd-para" : "dd-para dd-para--strong"}>
          <DiffText from={group.from} to={group.to} side={side} />
        </p>
      );
    }
    if (showAll) return group.paragraphs.map((text) => <p key={text} className="dd-para dd-para--quiet">{text}</p>);
    return (
      <button key={index} type="button" className="dd-textbtn" onClick={() => setShowAll(true)}>
        {foldLabel(group.paragraphs.length)}. Show them
      </button>
    );
  });
}

function Inspector({ field, index, total, onStep, onClose }: { field: DriftedField; index: number; total: number; onStep: (delta: number) => void; onClose: () => void }) {
  const afterIsApplied = field.after === field.lastApplied;
  return (
    <aside className="dd-rail" aria-label={`${field.label} history`}>
      <div className="dd-rail__head">
        <h3>{field.label}</h3>
        <span className="dd-count dv-tnum">
          {index + 1} of {total}
        </span>
        <div className="dd-rail__nav">
          <button type="button" className="dd-iconbtn" aria-label="Previous change" onClick={() => onStep(-1)}>
            <CaretLeftIcon aria-hidden="true" />
          </button>
          <button type="button" className="dd-iconbtn" aria-label="Next change" onClick={() => onStep(1)}>
            <CaretRightIcon aria-hidden="true" />
          </button>
          <button type="button" className="dd-iconbtn" aria-label="Close inspector" onClick={onClose}>
            <XIcon aria-hidden="true" />
          </button>
        </div>
      </div>
      <p className="dd-rail__verdict">{field.verdict}</p>
      <ol className="dd-history">
        <Stop state="past" label="Your last apply" note="What this tool wrote">
          <Differences key={`${field.id}-past`} field={field} side="from" from={field.lastApplied} to={field.live} />
        </Stop>
        <Stop state="now" label="On Etsy now" note="Changed since then">
          <Differences key={`${field.id}-now`} field={field} side="to" from={field.lastApplied} to={field.live} />
        </Stop>
        <Stop state="next" label="After apply" note={afterIsApplied ? "Goes back to your last apply" : "From this plan"}>
          {!afterIsApplied && <Differences key={`${field.id}-next`} field={field} side="to" from={field.live} to={field.after} />}
        </Stop>
      </ol>
    </aside>
  );
}

export default function Frame() {
  const [selected, setSelected] = useState<number | null>(1);
  const total = driftedFields.length;
  const field = selected === null ? null : (driftedFields[selected] ?? null);
  const step = (delta: number) => setSelected((current) => ((current ?? 0) + delta + total) % total);
  const isSelected = (candidate: DriftedField) => field?.id === candidate.id;
  const pick = (candidate: DriftedField) => setSelected(isSelected(candidate) ? null : driftedFields.indexOf(candidate));

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  return (
    <div className={`dd-docked${field ? " dd-docked--open" : ""}`}>
      <DriftPage
        headTag={<span className="tag tag-accent">Drifted from Etsy</span>}
        impacts={["Images", "Title", "Description"]}
        warning={
          <div className="dv-callout dv-callout--drift dd-strip">
            <DriftIcon />
            <div>
              <strong>Etsy no longer matches your last apply.</strong> Apply will set {total} fields back.
            </div>
            <button type="button" className="btn btn-secondary dd-strip__action" onClick={() => setSelected(0)}>
              Review {total} changes
            </button>
          </div>
        }
      >
        <Compare>
          <ClosedRow field={title} actionLabel="Inspect" selected={isSelected(title)} onClick={() => pick(title)} />
          <ClosedRow field={description} actionLabel="Inspect" selected={isSelected(description)} onClick={() => pick(description)} />
          <SettledRows />
          <SettingRow field={shipping} selected={isSelected(shipping)} onClick={() => pick(shipping)} />
        </Compare>
      </DriftPage>
      {field && <Inspector field={field} index={selected ?? 0} total={total} onStep={step} onClose={() => setSelected(null)} />}
    </div>
  );
}
