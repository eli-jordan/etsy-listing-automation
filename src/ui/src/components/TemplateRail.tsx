import { marigoldMapsReady } from "./preparationLabel";
import type { PreparationJob } from "../api/preparation";
import { useMemo, useState } from "react";
import { templateThumbnailUrl } from "../api/calibrator";
import { LabelSearch } from "./LabelSearch";
import { holdsLabels } from "./labelRules";
import type { TemplateKind, TemplateSummary } from "../types";

const KIND_LABELS: Record<TemplateKind, string> = {
  "colour-matrix": "Colour Matrix",
  multiple: "Multiple",
  single: "Single",
};

/** Rows per group before "+ N more", so a big workspace keeps the calibrate button on screen. */
const VISIBLE_LIMIT = 5;

type StatusFilter = "needs" | "all" | "done";

function needsCalibration(t: TemplateSummary): boolean {
  return t.renderer === "marigold"
    ? Boolean(t.maps && !marigoldMapsReady(t.maps))
    : t.status === "needs-calibration";
}

function countLabel(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

function describe(t: TemplateSummary): string {
  const kind = t.kind ? KIND_LABELS[t.kind] : null;
  if (t.renderer === "marigold") return kind ?? "Unknown";
  if (needsCalibration(t)) {
    const reason = t.status_reason ?? "not calibrated";
    return kind ? `${kind} · ${reason}` : reason;
  }
  return `${kind ?? "Unknown"} · ${countLabel(t.colours.length, "colour")}`;
}

function mapsLabel(maps: TemplateSummary["maps"]): string {
  if (!maps) return "Checking maps";
  return marigoldMapsReady(maps) ? "Ready" : "Needs maps";
}

function queueStatus(jobs: PreparationJob[], name: string): string | null {
  const job = jobs.find((candidate) => candidate.template === name);
  if (!job) return null;
  return job.phase === "queued" ? "Queued" : "Preparing";
}

function jobLabel(job: PreparationJob): string {
  if (job.phase === "queued") return "Queued";
  return job.kind === "rebuild" ? "Rebuilding maps" : "Preparing";
}

/** `/thumbnail` 404s for a template directory with no photo yet; a blank tile
 * stops the browser drawing its broken-image icon. */
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
        <span
          className={`template-rail__labels${template.labels.length === 0 ? " template-rail__labels--none" : ""}`}
        >
          {template.labels.length > 0 ? template.labels.join(" · ") : "No labels"}
        </span>
        {template.renderer === "marigold" && (
          <span
            className={`mg-rail-state${marigoldMapsReady(template.maps) ? " mg-rail-state--ready" : ""}`}
          >
            {preparationStatus || mapsLabel(template.maps)}
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
            t.name === selected ? (selectedPreparationStatus ?? null) : queueStatus(jobs, t.name)
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

function RailGroups({
  shown,
  marigold,
  selected,
  onSelect,
  jobs,
  selectedPreparationStatus,
}: {
  shown: TemplateSummary[];
  marigold: boolean;
  selected: string | null;
  onSelect: (name: string) => void;
  jobs: PreparationJob[];
  selectedPreparationStatus: string | null;
}) {
  if (shown.length === 0) return <p className="template-rail__empty">No templates match.</p>;
  if (marigold) {
    return (
      <Group
        heading="Templates"
        templates={shown}
        selected={selected}
        onSelect={onSelect}
        jobs={jobs}
        selectedPreparationStatus={selectedPreparationStatus}
      />
    );
  }
  return (
    <>
      <Group
        heading="Needs calibration"
        templates={shown.filter(needsCalibration)}
        selected={selected}
        onSelect={onSelect}
      />
      <Group
        heading="Calibrated"
        templates={shown.filter((t) => !needsCalibration(t))}
        selected={selected}
        onSelect={onSelect}
      />
    </>
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
  const [pills, setPills] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [kind, setKind] = useState<TemplateKind | null>(null);

  const outstanding = useMemo(() => templates.filter(needsCalibration), [templates]);
  const isReady = (t: TemplateSummary) =>
    t.renderer === "marigold" ? marigoldMapsReady(t.maps) : !needsCalibration(t);
  const doneCount = templates.filter(isReady).length;
  const nextToCalibrate = outstanding.find((template) => template.renderer !== "marigold") ?? null;

  const filtered = useMemo(
    () =>
      templates.filter((t) => {
        if (status === "needs" && !needsCalibration(t)) return false;
        if (status === "done" && !isReady(t)) return false;
        return !kind || t.kind === kind;
      }),
    [templates, status, kind],
  );
  const labelLists = useMemo(() => filtered.map((t) => t.labels), [filtered]);
  const shown = useMemo(() => {
    const term = search.trim().toLowerCase();
    return filtered.filter(
      (t) => holdsLabels(t.labels, pills) && t.name.toLowerCase().includes(term),
    );
  }, [filtered, pills, search]);

  return (
    <nav className="template-rail" aria-label="Templates">
      {nextToCalibrate && (
        <div className="template-rail__banner">
          <p className="template-rail__banner-text">
            {`${countLabel(outstanding.length, "template")} need${
              outstanding.length === 1 ? "s" : ""
            } calibration`}
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onSelect(nextToCalibrate.name)}
          >
            Calibrate next →
          </button>
        </div>
      )}

      <LabelSearch
        items={labelLists}
        on={pills}
        onOn={setPills}
        query={search}
        onQuery={setSearch}
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

      <RailGroups
        shown={shown}
        marigold={marigold}
        selected={selected}
        onSelect={onSelect}
        jobs={jobs}
        selectedPreparationStatus={selectedPreparationStatus ?? null}
      />
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
              <span>{jobLabel(job)}</span>
            </button>
          ))}
        </section>
      )}
    </nav>
  );
}
