import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CaretUpIcon } from "@phosphor-icons/react/dist/csr/CaretUp";
import { useState } from "react";
import { ClosedRow, Compare, DriftIcon, DriftPage, SettingRow, SettledRows, revealRow } from "./_DriftPage";
import { DiffText, foldLabel, groupParagraphs } from "./_driftDiff";
import { description, driftedFields, kindLabels, shipping, title, type DriftedField } from "./_fixtures";

export const meta = {
  title: "C · Change ledger",
  viewport: "monitor",
  description: "Not chosen, A won. A top ledger names each exact difference; clicking a field replaces its two columns with one full-width unified diff.",
};

function LedgerRow({ field, onOpen }: { field: DriftedField; onOpen: () => void }) {
  const { from, to, count } = field.summary;
  return (
    <li>
      <button type="button" className="dd-ledger__row" onClick={onOpen}>
        <span className="dd-ledger__field">{field.label}</span>
        <span className={`dd-kind dd-kind--${field.kind}`}>{kindLabels[field.kind]}</span>
        <span className="dd-ledger__change">
          <span className="dv-del">{to}</span>
          <span className="dd-arrow">becomes</span>
          <span className="dv-ins">{from}</span>
          {count !== undefined && <span className="dd-times dv-tnum">{count} places</span>}
        </span>
        <CaretDownIcon aria-hidden="true" />
      </button>
    </li>
  );
}

function UnifiedBody({ field, full }: { field: DriftedField; full: boolean }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  return (
    <div className="dd-unified__text">
      {groupParagraphs(field.live, field.after).map((group, index) => {
        if (group.type === "diff") {
          return (
            <p key={index} className="dd-para">
              <DiffText from={group.from} to={group.to} side="unified" />
            </p>
          );
        }
        if (full || expanded.has(index)) {
          return group.paragraphs.map((text) => (
            <p key={text} className="dd-para dd-para--quiet">
              {text}
            </p>
          ));
        }
        return (
          <button key={index} type="button" className="dd-fold dd-fold--inline" onClick={() => setExpanded((seen) => new Set(seen).add(index))}>
            {foldLabel(group.paragraphs.length)}. Show them
          </button>
        );
      })}
    </div>
  );
}

function Unified({ field, onClose }: { field: DriftedField; onClose: () => void }) {
  const [full, setFull] = useState(false);
  return (
    <section id={`row-${field.id}`} className="dd-unified" aria-label={`${field.label}: Etsy compared with this plan`}>
      <div className="dd-unified__side">
        <span className="dv-eyebrow">{field.label}</span>
        <p className="dd-unified__verdict">{field.verdict}</p>
        <dl className="dd-legend">
          <div>
            <dt className="dv-del">Struck</dt>
            <dd>on Etsy now</dd>
          </div>
          <div>
            <dt className="dv-ins">Added</dt>
            <dd>after apply</dd>
          </div>
        </dl>
        <div className="dd-seg" role="group" aria-label="Text shown">
          <button type="button" aria-pressed={!full} onClick={() => setFull(false)}>
            Changes only
          </button>
          <button type="button" aria-pressed={full} onClick={() => setFull(true)}>
            Full text
          </button>
        </div>
        <button type="button" className="dd-textbtn" onClick={onClose}>
          Close <CaretUpIcon aria-hidden="true" />
        </button>
      </div>
      <UnifiedBody field={field} full={full} />
    </section>
  );
}

function TextField({ field, open, onToggle }: { field: DriftedField; open: boolean; onToggle: () => void }) {
  return open ? <Unified field={field} onClose={onToggle} /> : <ClosedRow field={field} actionLabel="See changes" onClick={onToggle} />;
}

export default function Frame() {
  const [open, setOpen] = useState<string | null>("description");
  const toggle = (id: string) => setOpen((current) => (current === id ? null : id));
  const jump = (id: string) => {
    if (id !== shipping.id) setOpen(id);
    requestAnimationFrame(() => revealRow(id));
  };

  return (
    <DriftPage
      impacts={["Images", "Title", "Description"]}
      warning={
        <div className="dd-ledger">
          <div className="dd-ledger__head">
            <DriftIcon />
            <h3>This listing has drifted from what&rsquo;s on Etsy</h3>
            <span>Apply will set all {driftedFields.length} back.</span>
          </div>
          <ul>
            {driftedFields.map((field) => (
              <LedgerRow key={field.id} field={field} onOpen={() => jump(field.id)} />
            ))}
          </ul>
        </div>
      }
    >
      <Compare>
        <TextField field={title} open={open === "title"} onToggle={() => toggle("title")} />
        <TextField field={description} open={open === "description"} onToggle={() => toggle("description")} />
        <SettledRows />
        <SettingRow field={shipping} />
      </Compare>
    </DriftPage>
  );
}
