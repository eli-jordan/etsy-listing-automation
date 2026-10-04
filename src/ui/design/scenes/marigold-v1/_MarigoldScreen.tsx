// Throwaway Marver UI: additions to the existing workbench, fixture state only.
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { ClockIcon } from "@phosphor-icons/react/dist/csr/Clock";
import { EraserIcon } from "@phosphor-icons/react/dist/csr/Eraser";
import { HandIcon } from "@phosphor-icons/react/dist/csr/Hand";
import { PaintBrushIcon } from "@phosphor-icons/react/dist/csr/PaintBrush";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { useState } from "react";
import { QuadEditor } from "../../../src/components/QuadEditor";
import { ViewTabs, type View } from "../../../src/components/ViewTabs";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import type { BoundingBox } from "../../../src/types";
import { assets, initialBox, pairBoxes, pairImage, templates } from "./_fixtures";
import "./_marigold.css";

export type ScreenState = "edit" | "preparing" | "preview" | "outdated" | "multiple" | "failed";
type Tool = "placement" | "exclude" | "restore";

function Status({
  text,
  ready = false,
  failed = false,
}: {
  text: string;
  ready?: boolean;
  failed?: boolean;
}) {
  return (
    <span
      className={`tag mg-status ${ready ? "mg-status--ready" : ""} ${failed ? "mg-status--failed" : ""}`}
    >
      {ready ? (
        <CheckCircleIcon weight="bold" />
      ) : failed ? (
        <WarningCircleIcon weight="bold" />
      ) : (
        <ClockIcon weight="bold" />
      )}
      {text}
    </span>
  );
}

function Slider({
  label,
  initial,
  low,
  high,
}: {
  label: string;
  initial: number;
  low: string;
  high: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <div className="realism__pass">
      <label className="realism__title mg-slider-label">{label}</label>
      <div className="realism__row">
        <input
          aria-label={label}
          type="range"
          min="0"
          max="100"
          value={value}
          onChange={(e) => setValue(Number(e.target.value))}
        />
        <span className="realism__value">{value}%</span>
      </div>
      <p className="realism__scale">
        {low} <span aria-hidden="true">—</span> {high}
      </p>
    </div>
  );
}

export function MarigoldScreen({ state }: { state: ScreenState }) {
  const isMultiple = state === "multiple";
  const [view, setView] = useState<View>(
    state === "preview" || state === "outdated" ? "preview" : "calibrate",
  );
  const [renderer, setRenderer] = useState("marigold");
  const [tool, setTool] = useState<Tool>("placement");
  const [boxes, setBoxes] = useState<BoundingBox[]>(isMultiple ? pairBoxes : [initialBox]);
  const [selected, setSelected] = useState(0);
  const [outlines, setOutlines] = useState(true);
  const [mask, setMask] = useState(true);
  const [strokes, setStrokes] = useState<{ x: number; y: number }[]>([]);
  const [colour, setColour] = useState("Bay");
  const [light, setLight] = useState("Estimated illumination");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [kindFilter, setKindFilter] = useState<string | null>(null);
  const [fullImage, setFullImage] = useState(false);
  const ready = state === "preview";
  const running = state === "preparing" || state === "multiple";
  const rebuilding = state === "outdated";
  const failed = state === "failed";
  const status = ready
    ? "Ready"
    : rebuilding
      ? "Out of date"
      : running
        ? "Preparing"
        : failed
          ? "Preparation failed"
          : "Needs preparation";
  const selectedName = isMultiple ? "cc1717-colour-pair" : "cc1717-hanging-on-fence";
  const selectedImage = colour === "Bay" ? assets.bay : assets.berry;
  const readyCount = isMultiple ? 1 : ready ? 3 : 2;
  const activeStep = rebuilding ? 1 : isMultiple ? 3 : 2;
  const currentTool =
    tool === "placement"
      ? "Drag corners or move the box. Shift-drag scales it."
      : tool === "exclude"
        ? "Brush over foreground objects to keep the print off them."
        : "Brush to restore cloth accidentally excluded from the print.";

  const prepSection = (
    <section className="realism mg-preparation" aria-label="Renderer and preparation">
      <h3 className="realism__heading">Renderer</h3>
      <select
        className="input"
        aria-label="Renderer"
        value={renderer}
        onChange={(e) => setRenderer(e.target.value)}
      >
        <option value="existing">Existing renderer</option>
        <option value="marigold">Marigold</option>
      </select>
      {renderer === "marigold" && (
        <>
          <div className="mg-row">
            <strong className="mg-label">Template maps</strong>
            <Status text={status} ready={ready} failed={failed} />
          </div>
          <p className="mg-help">
            {isMultiple
              ? "Main image · both placements"
              : "Main image: Bay · shared by all 33 colours"}
          </p>
          {(running || rebuilding) && (
            <div className="mg-progress" role="status">
              <div className="mg-row">
                <strong>
                  {rebuilding
                    ? "Rebuilding maps"
                    : isMultiple
                      ? "Mapping placement 2 of 2"
                      : "Estimating depth"}
                </strong>
                <span>{rebuilding ? "00:04" : "00:48"}</span>
              </div>
              <ol className="mg-steps">
                {(rebuilding
                  ? ["Saved changes", "Rebuild maps", "Ready"]
                  : ["Normals", "Lighting", "Depth", "Maps"]
                ).map((step, index) => (
                  <li
                    key={step}
                    className={
                      index < activeStep
                        ? "mg-step--done"
                        : index === activeStep
                          ? "mg-step--active"
                          : ""
                    }
                  >
                    {index < activeStep ? (
                      <CheckCircleIcon weight="bold" />
                    ) : (
                      <span className="mg-step-dot" />
                    )}
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {failed && (
            <p className="mg-error">
              Preparation stopped while loading the models. Close other GPU-heavy apps, then retry.
            </p>
          )}
          {ready ? (
            <button className="btn btn-secondary mg-wide" data-goto="marigold-v1/preparing">
              Prepare again
            </button>
          ) : running ? (
            <button className="btn btn-secondary mg-wide" data-goto="marigold-v1/edit">
              Cancel preparation
            </button>
          ) : rebuilding ? (
            <button className="btn btn-secondary mg-wide" disabled>
              Updating from saved predictions…
            </button>
          ) : (
            <button className="btn btn-primary mg-wide" data-goto="marigold-v1/preparing">
              {failed ? "Retry preparation" : "Prepare template"}
            </button>
          )}
          <p className="mg-help">
            {ready
              ? "Prepared once. New designs render without preparation."
              : rebuilding
                ? "Using cached predictions. No new model inference."
                : running
                  ? "You can close this browser. Preparation will continue."
                  : failed
                    ? "Completed steps will be reused."
                    : "Prepare once, then reuse for every design and colour."}
          </p>
        </>
      )}
    </section>
  );

  return (
    <div className="mg-frame shell">
      <ShellSidebar shopName="North & Pine Studio">
        <nav className="sidebar__nav">
          <a className="nav-item" href="#dashboard">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <rect x="3" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" />
            </svg>
            Dashboard
          </a>
          <a className="nav-item" href="#listings">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <path d="M8 6h12M8 12h12M8 18h12" />
              <circle cx="4" cy="6" r="1" />
              <circle cx="4" cy="12" r="1" />
              <circle cx="4" cy="18" r="1" />
            </svg>
            Listings
          </a>
          <a className="nav-item" href="#listing-templates">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <path d="m3 8 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 18l9 5 9-5" />
            </svg>
            Listing Templates
          </a>
          <a
            className="nav-item nav-item--active"
            data-goto="marigold-v1/edit"
            href="#mockup-templates"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
              <rect x="7.5" y="7.5" width="13.5" height="13.5" rx="2" />
              <path d="M3.5 15.5v-10a2 2 0 0 1 2-2h10" />
            </svg>
            Mockup Templates
          </a>
        </nav>
      </ShellSidebar>
      <main className="shell__main">
        <div className="app mg-app">
          <header className="app__header">
            <h1 className="app__title">Mockup Templates</h1>
            <span className="app__crumb-sep">/</span>
            <span className="app__crumb">
              {isMultiple ? "Two-shirt scene" : "Hanging on fence"}
            </span>
            <Status text={status} ready={ready} failed={failed} />
            <span className="app__meta">
              {isMultiple ? "Multiple · 2 placements" : "Colour Matrix · 33 colours"}
            </span>
            <div className="app__actions">
              <span className="page-head__saved">
                <span className="page-head__dot" />
                Saved a moment ago
              </span>
            </div>
          </header>
          <div className="app__workbench">
            <nav className="template-rail" aria-label="Templates">
              <input
                type="search"
                className="input template-rail__search"
                placeholder="Search templates…"
                aria-label="Search templates"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <div className="template-rail__filters">
                {["All", "Needs maps", "Ready"].map((filter) => (
                  <button
                    key={filter}
                    className={`tag template-rail__pill ${statusFilter === filter ? "template-rail__pill--on" : ""}`}
                    onClick={() => setStatusFilter(filter)}
                  >
                    {filter}{" "}
                    {filter === "All" ? 4 : filter === "Ready" ? readyCount : 4 - readyCount}
                  </button>
                ))}
              </div>
              <div className="template-rail__filters">
                {["Colour Matrix", "Multiple", "Single"].map((kind) => (
                  <button
                    key={kind}
                    className={`tag template-rail__pill ${kindFilter === kind ? "template-rail__pill--on" : ""}`}
                    aria-pressed={kindFilter === kind}
                    onClick={() => setKindFilter(kindFilter === kind ? null : kind)}
                  >
                    {kind}
                  </button>
                ))}
              </div>
              <section className="template-rail__group">
                <h2 className="template-rail__heading">Templates · 4</h2>
                {templates
                  .filter(
                    (t) =>
                      (!query || t.label.toLowerCase().includes(query.toLowerCase())) &&
                      (!kindFilter || t.kind === kindFilter) &&
                      (statusFilter === "All" ||
                        (statusFilter === "Ready"
                          ? t.name === selectedName
                            ? ready
                            : t.kind !== "Colour Matrix"
                          : t.name === selectedName
                            ? !ready
                            : t.kind === "Colour Matrix")),
                  )
                  .map((t) => (
                    <button
                      key={t.name}
                      className={`template-rail__item ${t.name === selectedName ? "template-rail__item--active" : ""}`}
                      data-goto={t.goto}
                    >
                      <img src={t.image} className="template-rail__thumb" alt="" />
                      <span className="template-rail__text">
                        <span className="template-rail__name">{t.label}</span>
                        <span className="template-rail__meta">{t.kind}</span>
                        <span
                          className={`mg-rail-state ${t.name === selectedName && ready ? "mg-rail-state--ready" : ""}`}
                        >
                          {t.name === selectedName ? status : t.status}
                        </span>
                      </span>
                    </button>
                  ))}
              </section>
              {(running || rebuilding) && (
                <section className="mg-queue">
                  <h2 className="template-rail__heading">Preparation queue</h2>
                  <div className="mg-row">
                    <span>{isMultiple ? "Two-shirt scene" : "Hanging on fence"}</span>
                    <span className="mg-queue-dot" />
                  </div>
                  <p className="mg-help">{rebuilding ? "Rebuilding maps" : "Preparing · 00:48"}</p>
                  <hr className="realism__divider" />
                  <div className="mg-row">
                    <span>Folded shirt</span>
                    <span className="mg-muted">Queued</span>
                  </div>
                  <p className="mg-help">Starts when this template finishes.</p>
                </section>
              )}
            </nav>
            <div className="app__workspace">
              <div className="app__main">
                <div className="app__preview">
                  <div className="app__preview-bar">
                    <ViewTabs value={view} onChange={setView} />
                    {view === "calibrate" ? (
                      <>
                        <span className="mg-main-photo">
                          {isMultiple ? "Main image" : "Main image · Bay"}
                        </span>
                        <label className="app__outline-toggle">
                          <input
                            type="checkbox"
                            checked={outlines}
                            onChange={(e) => setOutlines(e.target.checked)}
                          />
                          show outline
                        </label>
                      </>
                    ) : null}
                  </div>
                  {view === "calibrate" ? (
                    <>
                      <div
                        className={`mg-stage ${tool !== "placement" ? "mg-stage--mask" : ""}`}
                        onPointerDown={(e) => {
                          if (tool === "placement") return;
                          const r = e.currentTarget.getBoundingClientRect();
                          if (tool === "restore") setStrokes(strokes.slice(0, -1));
                          else
                            setStrokes([
                              ...strokes,
                              {
                                x: ((e.clientX - r.left) / r.width) * 100,
                                y: ((e.clientY - r.top) / r.height) * 100,
                              },
                            ]);
                        }}
                      >
                        {isMultiple ? (
                          <QuadEditor
                            imageUrl={pairImage}
                            space={[960, 480]}
                            boxes={boxes}
                            selectedIndex={selected}
                            onSelect={setSelected}
                            onChangeBox={(index, box) =>
                              setBoxes(boxes.map((old, i) => (i === index ? box : old)))
                            }
                            outlines={outlines ? "all" : "selected"}
                            labels={["Ivory", "Yam"]}
                          />
                        ) : (
                          <QuadEditor
                            imageUrl={assets.bay}
                            space={[480, 480]}
                            boxes={boxes}
                            selectedIndex={0}
                            onSelect={() => {}}
                            onChangeBox={(_, box) => setBoxes([box])}
                            outlines={outlines ? "all" : "none"}
                          />
                        )}
                        {isMultiple &&
                          boxes.map((box, index) => (
                            <img
                              key={index}
                              src={assets.artwork}
                              alt=""
                              className="mg-artwork"
                              style={{
                                left: `${(box[0].x / 960) * 100}%`,
                                top: `${(box[0].y / 480) * 100}%`,
                                width: `${((box[1].x - box[0].x) / 960) * 100}%`,
                                height: `${((box[3].y - box[0].y) / 480) * 100}%`,
                              }}
                            />
                          ))}
                        {!isMultiple && boxes[0] && (
                          <img
                            src={assets.artwork}
                            alt=""
                            className="mg-artwork"
                            style={{
                              left: `${(boxes[0][0].x / 480) * 100}%`,
                              top: `${(boxes[0][0].y / 480) * 100}%`,
                              width: `${((boxes[0][1].x - boxes[0][0].x) / 480) * 100}%`,
                              height: `${((boxes[0][3].y - boxes[0][0].y) / 480) * 100}%`,
                            }}
                          />
                        )}
                        {strokes.map((p, index) => (
                          <span
                            key={index}
                            className="mg-mask-stroke"
                            style={{ left: `${p.x}%`, top: `${p.y}%` }}
                          />
                        ))}
                        {tool !== "placement" && (
                          <span className="mg-tool-caption">
                            {tool === "exclude" ? "Exclude foreground" : "Restore cloth"}
                          </span>
                        )}
                      </div>
                      <div className="mg-canvas-foot">
                        <strong>Placement preview</strong>
                        <span>Simple overlay · open Preview to see folds and lighting.</span>
                      </div>
                      <p className="mg-canvas-hint">{currentTool}</p>
                    </>
                  ) : (
                    <div className="preview-grid">
                      <div className="preview-grid__head">
                        <span className="preview-grid__count">
                          {rebuilding ? "Previous renders" : "33 / 33"}
                        </span>
                        <span className="preview-grid__status">
                          {rebuilding ? "Out of date" : "Full quality"}
                        </span>
                        <div className="preview-grid__actions">
                          <button
                            className="btn btn-secondary"
                            disabled={rebuilding || !ready}
                            data-goto="marigold-v1/preview"
                          >
                            Re-render
                          </button>
                        </div>
                      </div>
                      {!ready && !rebuilding ? (
                        <div className="mg-empty-preview">
                          <ClockIcon weight="bold" />
                          <h3>Prepare the template first</h3>
                          <p>Full-quality previews need current garment maps.</p>
                          <button className="btn btn-primary" data-goto="marigold-v1/preparing">
                            Prepare template
                          </button>
                        </div>
                      ) : (
                        <>
                          {rebuilding && (
                            <p className="mg-stale-notice">
                              Placement changed. Maps are updating; these images show the previous
                              settings. Re-render when ready.
                            </p>
                          )}
                          <div className="preview-grid__tiles">
                            {["Bay", "Berry"].map((c) => (
                              <figure key={c} className="gallery__item preview-grid__tile">
                                <button
                                  className="preview-grid__open mg-render-open"
                                  title="Open at full size"
                                  aria-label={`Open ${c} at full size`}
                                  onClick={() => {
                                    setColour(c);
                                    setFullImage(true);
                                  }}
                                >
                                  <img src={c === "Bay" ? assets.bay : assets.berry} alt={c} />
                                  <img src={assets.artwork} alt="" className="mg-render-art" />
                                </button>
                                <figcaption>{c}</figcaption>
                              </figure>
                            ))}
                          </div>
                          <p className="mg-help">
                            Full-size renders. Click a colour to see it large.
                          </p>
                          <p className="mg-help">
                            All colours use Bay’s prepared maps. No additional preparation.
                          </p>
                        </>
                      )}
                    </div>
                  )}
                </div>
                <aside className="app__controls">
                  {prepSection}
                  {view === "calibrate" && (
                    <section className="realism mg-masks" aria-label="Placement and mask tools">
                      <div className="realism__head">
                        <h3 className="realism__heading">
                          {isMultiple
                            ? `Placement ${selected + 1} · ${selected === 0 ? "Ivory" : "Yam"}`
                            : "Placement & masks"}
                        </h3>
                        <button
                          className="btn btn-ghost"
                          aria-label="Undo mask stroke"
                          onClick={() => setStrokes(strokes.slice(0, -1))}
                        >
                          <ArrowCounterClockwiseIcon weight="bold" />
                          Undo
                        </button>
                      </div>
                      {isMultiple && (
                        <select
                          className="input"
                          aria-label="Selected placement"
                          value={selected}
                          onChange={(e) => setSelected(Number(e.target.value))}
                        >
                          <option value="0">1 · Ivory</option>
                          <option value="1">2 · Yam</option>
                        </select>
                      )}
                      <div className="mg-tool-buttons">
                        {(
                          [
                            { value: "placement", label: "Move placement", icon: HandIcon },
                            { value: "exclude", label: "Exclude foreground", icon: PaintBrushIcon },
                            { value: "restore", label: "Restore cloth", icon: EraserIcon },
                          ] as const
                        ).map((t) => (
                          <button
                            key={t.value}
                            className={`btn btn-secondary ${tool === t.value ? "mg-tool--selected" : ""}`}
                            aria-pressed={tool === t.value}
                            onClick={() => setTool(t.value)}
                          >
                            <t.icon weight="bold" />
                            {t.label}
                          </button>
                        ))}
                      </div>
                      {tool !== "placement" && (
                        <Slider label="Brush size" initial={30} low="fine" high="broad" />
                      )}
                      <label className="mg-checkbox">
                        <input
                          type="checkbox"
                          checked={mask}
                          onChange={(e) => setMask(e.target.checked)}
                        />
                        Use proposed garment mask
                      </label>
                      <button
                        className="btn btn-ghost mg-reset"
                        onClick={() => {
                          setBoxes(isMultiple ? pairBoxes : [initialBox]);
                          setStrokes([]);
                          setTool("placement");
                          setMask(true);
                        }}
                      >
                        Reset placement & mask
                      </button>
                    </section>
                  )}
                  <section className="realism" aria-label="Print realism">
                    <div className="realism__head">
                      <h3 className="realism__heading">Print realism</h3>
                      <button
                        className="btn btn-ghost"
                        onClick={() => setLight("Estimated illumination")}
                      >
                        Reset
                      </button>
                    </div>
                    <label className="mg-label" htmlFor={`lighting-${state}`}>
                      Lighting
                    </label>
                    <select
                      id={`lighting-${state}`}
                      className="input"
                      value={light}
                      onChange={(e) => setLight(e.target.value)}
                    >
                      <option>Estimated illumination</option>
                      <option>Photographic lighting</option>
                    </select>
                    <Slider
                      label="Lighting strength"
                      initial={100}
                      low="flat"
                      high="full shading"
                    />
                    <Slider label="Fabric detail" initial={25} low="smooth" high="textured" />
                    <Slider label="Highlights" initial={0} low="none" high="strong" />
                  </section>
                  <section className="design-picker mg-design">
                    <h3 className="design-picker__heading">Test design</h3>
                    <select
                      className="input design-picker__select"
                      aria-label="Test design"
                      defaultValue="night-hike"
                    >
                      <option value="night-hike">Night Hike Club</option>
                      <option value="grid">Diagnostic grid</option>
                      <option value="white">Solid white</option>
                    </select>
                  </section>
                </aside>
              </div>
            </div>
          </div>
        </div>
      </main>
      {fullImage && (
        <div
          className="mg-lightbox"
          role="dialog"
          aria-label="Full-size preview"
          aria-modal="true"
          onKeyDown={(e) => {
            if (e.key === "Escape") setFullImage(false);
          }}
        >
          <button className="btn btn-secondary" autoFocus onClick={() => setFullImage(false)}>
            Close full-size preview
          </button>
          <div className="mg-lightbox-image">
            <img src={selectedImage} alt={`${colour} full-size mockup`} />
            <img src={assets.artwork} className="mg-render-art" alt="" />
          </div>
        </div>
      )}
    </div>
  );
}
