// The deploy page around each direction: the real head, StepStrip and footer,
// with the comparison laid out as rows so a field's two sides line up.
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import type { ReactNode } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { ApplyFooter } from "../../../src/pages/deploy/ApplyFooter";
import { StepStrip } from "../../../src/pages/deploy/StepStrip";
import {
  afterTiles,
  beforeTiles,
  colours,
  etsyListingId,
  listingName,
  materials,
  plan,
  priceRange,
  tags,
  type DriftedField,
} from "./_fixtures";

export function DriftIcon() {
  return (
    <svg className="dv-callout__icon" viewBox="0 0 20 20" fill="none" stroke="var(--color-accent-700)" strokeWidth="1.8" strokeLinecap="round">
      <path d="M3 7h11l-3-3M17 13H6l3 3" />
    </svg>
  );
}

export function DriftPage({
  headTag,
  warning,
  impacts,
  children,
}: {
  headTag?: ReactNode;
  warning: ReactNode;
  impacts: string[];
  children: ReactNode;
}) {
  return (
    <PageFrame headTag={headTag}>
      <div className="dv-banner">
        <h2>Apply will change what buyers see</h2>
        <div className="dv-impacts">
          {impacts.map((tag) => (
            <span key={tag} className="tag tag-accent">
              {tag}
            </span>
          ))}
        </div>
      </div>
      {warning}
      {children}
    </PageFrame>
  );
}

export function PageFrame({ headTag, children }: { headTag?: ReactNode; children: ReactNode }) {
  return (
    <div className="editor">
      <div className="page-head">
        <button type="button" className="btn btn-secondary dv-back">
          &larr; Back
        </button>
        <span className="page-head__crumb">Listings</span>
        <span className="page-head__sep">/</span>
        <span className="page-head__crumb">{listingName}</span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">Deploy</h1>
        <StatusTag status="dirty" />
        {headTag}
        <span className="page-head__meta">Planned just now</span>
        <div className="page-head__actions dv-head-actions">
          <button type="button" className="btn btn-ghost">
            Plan again
          </button>
        </div>
      </div>
      <div className="dv-stack">
        {children}
        <StepStrip plan={plan} stageRuntime={{}} heading="What apply will do" />
        <ApplyFooter controlPhase="ready-work" previewsTotal={0} previewsDone={0} onApply={() => {}} etsyListingId={etsyListingId} />
      </div>
    </div>
  );
}

export function Row({ left, right, className }: { left: ReactNode; right: ReactNode; className?: string }) {
  return (
    <div className={`dd-row ${className ?? ""}`}>
      <div className="dd-cell">{left}</div>
      <div className="dd-cell">{right}</div>
    </div>
  );
}

function Label({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <div className="dv-block__label">
      <span className="dv-eyebrow">{text}</span>
      {action}
    </div>
  );
}

function ImagesRow() {
  return (
    <Row
      left={
        <>
          <Label text="Images" action={<span className="dv-changed dv-changed--before">Replaced</span>} />
          <div className="dv-gallery">
            {beforeTiles.map((src, index) => (
              <figure key={index} className="dv-thumb-wrap">
                <div className="dv-thumb">
                  <img alt="" src={src} />
                </div>
              </figure>
            ))}
          </div>
        </>
      }
      right={
        <>
          <Label text="Images" action={<span className="dv-changed">Changes</span>} />
          <div className="dv-gallery">
            {afterTiles.map((tile, index) => (
              <figure key={index} className="dv-thumb-wrap">
                <div className="dv-thumb">
                  <img alt="" src={tile.src} />
                  {tile.movedFrom !== null && <span className="dv-thumb__badge dv-thumb__badge--moved">was {tile.movedFrom}</span>}
                </div>
              </figure>
            ))}
          </div>
        </>
      }
    />
  );
}

export function Compare({ children }: { children: ReactNode }) {
  return (
    <div className="dd-compare">
      <Row
        className="dd-row--head"
        left={
          <div className="dv-col__head">
            <h3>On Etsy now</h3>
            <span className="dv-eyebrow">listing {etsyListingId}</span>
          </div>
        }
        right={
          <div className="dv-col__head">
            <h3>After apply</h3>
            <span className="dv-eyebrow">from this plan</span>
          </div>
        }
      />
      <ImagesRow />
      {children}
    </div>
  );
}

function Chips({ values }: { values: string[] }) {
  return (
    <div className="dv-chips">
      {values.map((value) => (
        <span key={value} className="dv-chip">
          {value}
        </span>
      ))}
    </div>
  );
}

function Same({ label, content }: { label: string; content: ReactNode }) {
  const side = (
    <>
      <Label text={label} />
      {content}
    </>
  );
  return <Row left={side} right={side} />;
}

/** The fields Etsy still agrees with. */
export function SettledRows() {
  return (
    <>
      <Same label="Price" content={<div className="dv-price dv-tnum">{priceRange}</div>} />
      <Same
        label="Colours"
        content={
          <div className="dv-swatches">
            {colours.map((colour) => (
              <span key={colour} className="dv-sw">
                {colour}
              </span>
            ))}
          </div>
        }
      />
      <Same label="Tags" content={<Chips values={tags} />} />
      <Same label="Materials" content={<Chips values={materials} />} />
    </>
  );
}

export function DriftMark() {
  return <span className="dd-mark">Changed on Etsy</span>;
}

/** A drifted text field at rest. The whole row is the click target, through a
 * real button stretched over it. */
export function ClosedRow({
  field,
  actionLabel,
  onClick,
  selected,
}: {
  field: DriftedField;
  actionLabel: string;
  onClick: () => void;
  selected?: boolean;
}) {
  const body = (value: string) =>
    field.id === "title" ? <div className="dv-title">{value}</div> : <div className="dd-clamp">{value}</div>;
  return (
    <div id={`row-${field.id}`} className={`dd-row dd-row--drift${selected ? " dd-row--selected" : ""}`}>
      <div className="dd-cell">
        <Label text={field.label} action={<DriftMark />} />
        {body(field.live)}
      </div>
      <div className="dd-cell">
        <Label
          text={field.label}
          action={
            <button type="button" className="dd-stretch" aria-pressed={selected ?? false} aria-label={`${actionLabel}: ${field.label}`} onClick={onClick}>
              {actionLabel}
              <CaretDownIcon aria-hidden="true" />
            </button>
          }
        />
        {body(field.after)}
      </div>
    </div>
  );
}

/** A drifted setting: short enough that both values fit in the row. */
export function SettingRow({
  field,
  onClick,
  selected,
}: {
  field: DriftedField;
  onClick?: () => void;
  selected?: boolean;
}) {
  return (
    <div id={`row-${field.id}`} className={`dd-row dd-row--drift${selected ? " dd-row--selected" : ""}`}>
      <div className="dd-cell">
        <Label text={field.label} action={<DriftMark />} />
        <div className="dd-setting">{field.live}</div>
      </div>
      <div className="dd-cell">
        <Label
          text={field.label}
          action={
            onClick ? (
              <button type="button" className="dd-stretch" aria-pressed={selected ?? false} aria-label={`Inspect: ${field.label}`} onClick={onClick}>
                Inspect
                <CaretDownIcon aria-hidden="true" />
              </button>
            ) : undefined
          }
        />
        <div className="dd-setting">{field.after}</div>
      </div>
    </div>
  );
}

export function revealRow(id: string) {
  document.getElementById(`row-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
}
