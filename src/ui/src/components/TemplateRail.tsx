import type { PreparationJob } from "../api/preparation";
import { useMemo, useState } from "react";
import { templateThumbnailUrl } from "../api/calibrator";
import type { TemplateKind, TemplateSummary } from "../types";

/**
 * The template picker, as a rail rather than a dropdown (wireframe 2a).
 *
 * The point of the change is ordering: a dropdown presents 34 templates as an
 * undifferentiated list you have to already know your way around, while the
 * rail leads with the ones that are not finished and says what each is missing.
 * "Which do I open next?" stops being a question the user has to answer from
 * memory.
 *
 * Status is server-derived (`TemplateSummary.status`), so this component never
 * decides what "calibrated" means -- it only arranges what it is told.
 */

const KIND_LABELS: Record<TemplateKind, string> = {
  "colour-matrix": "Colour Matrix",
  multiple: "Multiple",
  single: "Single",
};

const VISIBLE_LIMIT = 5;
/** Rows shown per group before "+ N more". The rail is a sidebar, not the
 * page: a 34-template workspace should not push the calibrate button off
 * screen. */

type StatusFilter = "needs" | "all" | "done";

function needsCalibration(t: TemplateSummary): boolean {
  return t.renderer === "marigold"
    ? Boolean(t.maps && !t.maps.can_render)
    : t.status === "needs-calibration";
}

function countLabel(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** What the row says under the name: what is missing, or what it holds. */
function describe(t: TemplateSummary): string {
  const kind = t.kind ? KIND_LABELS[t.kind] : null;
  if (t.renderer === "marigold") return kind ?? "Unknown";
  if (needsCalibration(t)) {
    const reason = t.status_reason ?? "not calibrated";
    return kind ? `${kind} · ${reason}` : reason;
  }
  return `${kind ?? "Unknown"} · ${countLabel(t.colours.length, "colour")}`;
}

/** The row's photo, or a blank tile when there isn't one.
 *
 * A template directory can exist before any photo is in it -- an interrupted
 * upload, or a folder made by hand -- and `/thumbnail` 404s for those. Without
 * this the browser draws its own broken-image icon, which reads as the rail
 * being broken rather than as the template being empty. */
function Thumb({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="template-rail__thumb template-rail__thumb--empty" />;
  return (
    <img
      className="template-rail__thumb"
      src={templateThumbnailUrl(name)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

interface RowProps {
  preparationStatus?: string | null;
  template: TemplateSummary;
  selected: boolean;
  onSelect: (name: string) => void;
}

function Row({ template, selected, onSelect, preparationStatus }: RowProps) {
  const classes = ["template-rail__item"];
  if (selected) classes.push("template-rail__item--active");
  if (needsCalibration(template)) classes.push("template-rail__item--needs");
  return (
    <button
      type="button"
      className={classes.join(" ")}
      data-template={template.name}
      aria-current={selected ? "true" : undefined}
      onClick={() => onSelect(template.name)}
    >
      <Thumb name={template.name} />
      <span className="template-rail__text">
        <span className="template-rail__name">{template.name}</span>
        <span className="template-rail__meta">{describe(template)}</span>
        {template.renderer === "marigold" && (
          <span
            className={`mg-rail-state${template.maps?.can_render ? " mg-rail-state--ready" : ""}`}
          >
            {preparationStatus ||
              (template.maps
                ? template.maps.can_render
                  ? "Ready"
                  : "Needs maps"
                : "Checking maps")}
          </span>
        )}
      </span>
    </button>
  );
}

interface GroupProps {
  jobs?: PreparationJob[];
  selectedPreparationStatus?: string | null;
  heading: string;
  templates: TemplateSummary[];
  selected: string | null;
  onSelect: (name: string) => void;
}

function Group({
  heading,
  templates,
  selected,
  onSelect,
  jobs = [],
  selectedPreparationStatus,
}: GroupProps) {
  const [expanded, setExpanded] = useState(false);
  if (templates.length === 0) return null;

  const hidden = expanded ? 0 : Math.max(0, templates.length - VISIBLE_LIMIT);
  const visible = expanded ? templates : templates.slice(0, VISIBLE_LIMIT);

  return (
    <section className="template-rail__group">
      <h2 className="template-rail__heading">{`${heading} · ${templates.length}`}</h2>
      {visible.map((t) => (
        <Row
          key={t.name}
          template={t}
          selected={t.name === selected}
          onSelect={onSelect}
          preparationStatus={
            t.name === selected
              ? (selectedPreparationStatus ?? null)
              : jobs.find((job) => job.template === t.name)?.phase === "queued"
                ? "Queued"
                : jobs.some((job) => job.template === t.name)
                  ? "Preparing"
                  : null
          }
        />
      ))}
      {hidden > 0 && (
        <button type="button" className="template-rail__more" onClick={() => setExpanded(true)}>
          {`+ ${hidden} more`}
        </button>
      )}
    </section>
  );
}

interface TemplateRailProps {
  selectedPreparationStatus?: string | null;
  jobs?: PreparationJob[];
  templates: TemplateSummary[];
  selected: string | null;
  onSelect: (name: string) => void;
}

export function TemplateRail({
  templates,
  selected,
  onSelect,
  jobs = [],
  selectedPreparationStatus,
}: TemplateRailProps) {
  const marigold = templates.some((t) => t.renderer === "marigold");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [kind, setKind] = useState<TemplateKind | null>(null);

  const outstanding = useMemo(() => templates.filter(needsCalibration), [templates]);
  const isReady = (t: TemplateSummary) =>
    t.renderer === "marigold" ? Boolean(t.maps?.can_render) : !needsCalibration(t);
  const doneCount = templates.filter(isReady).length;
  // Held separately so the banner's callback has something TypeScript can
  // narrow -- `outstanding.length > 0` in JSX does not narrow `outstanding[0]`.
  const nextUp = outstanding.find((template) => template.renderer !== "marigold") ?? null;

  const shown = useMemo(() => {
    const term = search.trim().toLowerCase();
    return templates.filter((t) => {
      if (term && !t.name.toLowerCase().includes(term)) return false;
      if (status === "needs" && !needsCalibration(t)) return false;
      if (status === "done" && !isReady(t)) return false;
      if (kind && t.kind !== kind) return false;
      return true;
    });
  }, [templates, search, status, kind]);

  const pending = shown.filter(needsCalibration);
  const finished = shown.filter((t) => !needsCalibration(t));

  return (
    <nav className="template-rail" aria-label="Templates">
      {nextUp && (
        <div className="template-rail__banner">
          <p className="template-rail__banner-text">
            {`${countLabel(outstanding.length, "template")} need${
              outstanding.length === 1 ? "s" : ""
            } calibration`}
          </p>
          <button type="button" className="btn btn-primary" onClick={() => onSelect(nextUp.name)}>
            Calibrate next →
          </button>
        </div>
      )}

      <input
        className="input template-rail__search"
        type="search"
        aria-label="Search templates"
        placeholder="Search templates…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="template-rail__filters">
        {(
          [
            ["all", `All ${templates.length}`],
            ["needs", `${marigold ? "Needs maps" : "Needs calibration"} ${outstanding.length}`],
            ["done", `${marigold ? "Ready" : "Done"} ${doneCount}`],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={`tag template-rail__pill${status === value ? " template-rail__pill--on" : ""}`}
            aria-pressed={status === value}
            onClick={() => setStatus(value)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="template-rail__filters">
        {(Object.keys(KIND_LABELS) as TemplateKind[]).map((value) => (
          <button
            key={value}
            type="button"
            className={`tag template-rail__pill${kind === value ? " template-rail__pill--on" : ""}`}
            aria-pressed={kind === value}
            onClick={() => setKind((current) => (current === value ? null : value))}
          >
            {KIND_LABELS[value]}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="template-rail__empty">No templates match.</p>
      ) : marigold ? (
        <Group
          heading="Templates"
          templates={shown}
          selected={selected}
          onSelect={onSelect}
          jobs={jobs}
          selectedPreparationStatus={selectedPreparationStatus ?? null}
        />
      ) : (
        <>
          <Group
            heading="Needs calibration"
            templates={pending}
            selected={selected}
            onSelect={onSelect}
          />
          <Group
            heading="Calibrated"
            templates={finished}
            selected={selected}
            onSelect={onSelect}
          />
        </>
      )}
      {jobs.length > 0 && (
        <section className="mg-queue">
          <h2 className="template-rail__heading">Preparation queue</h2>
          {jobs.map((job) => (
            <button
              className="mg-queue-entry"
              type="button"
              key={job.id}
              onClick={() => onSelect(job.template)}
            >
              <span>{job.template}</span>
              <span>
                {job.phase === "queued"
                  ? "Queued"
                  : job.kind === "rebuild"
                    ? "Updating maps"
                    : "Preparing"}
              </span>
            </button>
          ))}
        </section>
      )}
    </nav>
  );
}
