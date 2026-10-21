// Throwaway Marver UI: additions to the existing workbench, fixture state only.
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { ClockIcon } from "@phosphor-icons/react/dist/csr/Clock";
import { WarningCircleIcon } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { useState } from "react";
import { QuadEditor } from "../../../src/components/QuadEditor";
import { ViewTabs, type View } from "../../../src/components/ViewTabs";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import type { BoundingBox } from "../../../src/types";
import { assets, initialBox, pairBoxes, pairImage, templates } from "./_fixtures";
import "./_marigold.css";
import { MaskToolbar, MaskBrushDock } from "./_MaskToolbar";
import "./_mask-toolbar.css";

export type ScreenState = "edit" | "preparing" | "preview" | "outdated" | "multiple" | "failed";
export type Tool = "placement" | "exclude" | "restore";
export type MaskControls = {
  tool: Tool;
  setTool: (tool: Tool) => void;
  showMask: boolean;
  setShowMask: (visible: boolean) => void;
  brushSize: number;
  setBrushSize: (size: number) => void;
  canUndo: boolean;
  undo: () => void;
  resetMask: () => void;
};

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

const explanations = {
  lighting:
    "Prepared garment lighting uses the lighting estimated during preparation. Photo-based lighting uses brightness from the original photo, which can also pick up the shirt's colour and texture.",
  shading:
    "Controls how much the garment's light and shadow affect the print. At 0% the design keeps its original brightness; at 100% it follows the cloth's shading fully.",
  texture:
    "Adds fine cloth texture and small wrinkles to the print. Increase it for a more textured look, or reduce it for a smoother print. This does not change placement or the larger folds.",
  highlights:
    "Adds bright reflections from the garment to the print. Higher values make the print look shinier and can wash out design detail. Leave at 0% for a matte print.",
  mask: "The placement box positions the design. The mask hides parts of it behind objects, in gaps or outside the garment. Mask hides print; Unmask restores it. Red shows hidden print. Showing the mask does not change the render.",
};
type InfoKey = keyof typeof explanations;

function FieldInfo({ name, open, toggle }: { name: InfoKey; open: boolean; toggle: () => void }) {
  return (
    <button
      type="button"
      className="mg-info"
      aria-label={`About ${name}`}
      aria-expanded={open}
      aria-controls={`help-${name}`}
      onClick={toggle}
    >
      <InfoIcon weight="regular" />
    </button>
  );
}

function Slider({
  label,
  value,
  onChange,
  low,
  high,
  info,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  low: string;
  high: string;
  info?: React.ReactNode;
}) {
  return (
    <div className="realism__pass">
      <div className="mg-field-title">
        <label className="realism__title mg-slider-label">{label}</label>
        {info}
      </div>
      <div className="realism__row">
        <input
          aria-label={label}
          type="range"
          min="0"
          max="100"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        <span className="realism__value">{value}%</span>
      </div>
      <p className="realism__scale">
        {low} <span aria-hidden="true">—</span> {high}
      </p>
    </div>
  );
}

// Illustrative fixture contour, not an inferred mask or a segmentation result.
const clothOutline =
  "M109 51 L180 41 Q216 53 236 64 Q256 57 282 42 L363 51 L432 151 L393 174 L371 150 L363 405 L112 410 L106 151 L81 177 L36 146 L81 100 Z";

export function MarigoldScreen({
  state,
  boxVisible = true,
  boxControl,
  initialInfo = null,
  initialTool = "placement",
  toolbar = (controls) => <MaskToolbar controls={controls} />,
  maskPresentation = "excluded",
}: {
  state: ScreenState;
  boxVisible?: boolean;
  boxControl?: React.ReactNode;
  initialInfo?: InfoKey | null;
  initialTool?: Tool;
  toolbar?: (controls: MaskControls) => React.ReactNode;
  maskPresentation?: "excluded" | "print-area";
}) {
  const isMultiple = state === "multiple";
  const [view, setView] = useState<View>(
    state === "preview" || state === "outdated" ? "preview" : "calibrate",
  );
  const [renderer, setRenderer] = useState("marigold");
  const [tool, setTool] = useState<Tool>(initialTool);
  const [boxes, setBoxes] = useState<BoundingBox[]>(isMultiple ? pairBoxes : [initialBox]);
  const [selected, setSelected] = useState(0);
  const outlines = boxVisible;
  const [mask, setMask] = useState(true);
  const [showMask, setShowMask] = useState(initialTool !== "placement");
  const [info, setInfo] = useState<InfoKey | null>(initialInfo);
  const [shading, setShading] = useState(100);
  const [texture, setTexture] = useState(25);
  const [highlights, setHighlights] = useState(0);
  const [brushSize, setBrushSize] = useState(30);
  const [strokes, setStrokes] = useState<{ x: number; y: number; mode: Tool; size: number }[]>([]);
  const [brushHistory, setBrushHistory] = useState<number[]>([]);
  const infoButton = (key: InfoKey) => (
    <FieldInfo name={key} open={info === key} toggle={() => setInfo(info === key ? null : key)} />
  );
  const infoText = (key: InfoKey) =>
    info === key ? (
      <p id={`help-${key}`} className="mg-info-text" role="note">
        {explanations[key]}
      </p>
    ) : null;
  const [colour, setColour] = useState("Bay");
  const [light, setLight] = useState("Prepared garment lighting");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");
  const [kindFilter, setKindFilter] = useState<string | null>(null);
  const [fullImage, setFullImage] = useState(false);
  const ready = state === "preview" || state === "outdated";
  const renderStale = state === "outdated";
  const running = state === "preparing" || state === "multiple";
  const rebuilding = false;
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
        ? "Mask: brush over areas where the print should be hidden."
        : "Unmask: brush to restore the print in masked areas.";

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
                  : ["Surface direction", "Garment lighting", "Depth", "Build maps"]
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
              <p className="mg-help">
                Steps run one after another. Map building uses all three predictions.
              </p>
            </div>
          )}
          {failed && (
            <p className="mg-error">
              Preparation stopped while loading the models. Close other GPU-heavy apps, then retry.
            </p>
          )}
          {ready ? (
            <button className="btn btn-secondary mg-wide" data-goto="marigold/preparing">
              Prepare again
            </button>
          ) : running ? (
            <button className="btn btn-secondary mg-wide" data-goto="marigold/edit">
              Cancel preparation
            </button>
          ) : rebuilding ? (
            <button className="btn btn-secondary mg-wide" disabled>
              Updating from saved predictions…
            </button>
          ) : (
            <button className="btn btn-primary mg-wide" data-goto="marigold/preparing">
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
    <div
      className="mg-frame shell"
      onKeyDown={(e) => {
        if (e.key === "Escape") setInfo(null);
        if (e.key === "Escape") {
          setTool("placement");
          setShowMask(false);
        }
      }}
    >
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
            data-goto="marigold/edit"
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
                      </>
                    ) : null}
                  </div>
                  {view === "calibrate" ? (
                    <>
                      {boxControl}
                      {toolbar({
                        tool,
                        setTool: (next) => {
                          setTool(next);
                          if (next !== "placement") setShowMask(true);
                        },
                        showMask,
                        setShowMask,
                        brushSize,
                        setBrushSize,
                        canUndo: brushHistory.length > 0,
                        undo: () => {
                          setStrokes(strokes.slice(0, brushHistory.at(-1)));
                          setBrushHistory(brushHistory.slice(0, -1));
                        },
                        resetMask: () => {
                          setStrokes([]);
                          setBrushHistory([]);
                          setMask(true);
                        },
                      })}
                      <div
                        className={`mg-stage ${tool !== "placement" ? "mg-stage--mask" : ""}`}
                        onPointerDown={(e) => {
                          if (tool === "placement") return;
                          e.currentTarget.setPointerCapture(e.pointerId);
                          setBrushHistory([...brushHistory, strokes.length]);
                          const r = e.currentTarget.getBoundingClientRect();
                          setStrokes([
                            ...strokes,
                            {
                              x: ((e.clientX - r.left) / r.width) * 100,
                              y: ((e.clientY - r.top) / r.height) * 100,
                              mode: tool,
                              size: brushSize,
                            },
                          ]);
                        }}
                        onPointerMove={(e) => {
                          if (tool === "placement" || !e.buttons) return;
                          const r = e.currentTarget.getBoundingClientRect();
                          setStrokes((old) => [
                            ...old,
                            {
                              x: ((e.clientX - r.left) / r.width) * 100,
                              y: ((e.clientY - r.top) / r.height) * 100,
                              mode: tool,
                              size: brushSize,
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
                        {showMask && (
                          <svg
                            className="mg-mask-overlay"
                            viewBox={`0 0 ${isMultiple ? 960 : 480} 480`}
                            aria-label={
                              maskPresentation === "print-area"
                                ? "Print area mask: red areas allow printing"
                                : "Mask overlay: red areas hide the print"
                            }
                            role="img"
                          >
                            <defs>
                              <mask id={`cloth-mask-${state}`}>
                                <rect
                                  width={isMultiple ? 960 : 480}
                                  height="480"
                                  fill={mask ? "white" : "black"}
                                />
                                {mask &&
                                  (isMultiple ? (
                                    <>
                                      <rect x="95" y="85" width="275" height="340" fill="black" />
                                      <rect x="575" y="85" width="275" height="340" fill="black" />
                                    </>
                                  ) : (
                                    <>
                                      <path d={clothOutline} fill="black" />
                                      <path
                                        d="M180 41 Q233 80 282 42 Q251 98 213 81 Z"
                                        fill="white"
                                      />
                                    </>
                                  ))}
                                {strokes.map((p, index) => (
                                  <circle
                                    key={index}
                                    cx={(p.x / 100) * (isMultiple ? 960 : 480)}
                                    cy={(p.y / 100) * 480}
                                    r={p.size / 2}
                                    fill={p.mode === "exclude" ? "white" : "black"}
                                  />
                                ))}
                              </mask>
                              {maskPresentation === "print-area" && (
                                <mask id={`print-area-${state}`}>
                                  <rect width={isMultiple ? 960 : 480} height="480" fill="black" />
                                  <path d={clothOutline} fill="white" />
                                  <path d="M180 41 Q233 80 282 42 Q251 98 213 81 Z" fill="black" />
                                  {strokes.map((p, index) => (
                                    <circle
                                      key={index}
                                      cx={(p.x / 100) * (isMultiple ? 960 : 480)}
                                      cy={(p.y / 100) * 480}
                                      r={p.size / 2}
                                      fill={p.mode === "exclude" ? "black" : "white"}
                                    />
                                  ))}
                                </mask>
                              )}
                            </defs>
                            <rect
                              width={isMultiple ? 960 : 480}
                              height="480"
                              mask={`url(#cloth-mask-${state})`}
                              fill={maskPresentation === "print-area" ? "#302820" : "#ed3737"}
                              opacity={maskPresentation === "print-area" ? "0.14" : "0.38"}
                            />
                            {maskPresentation === "print-area" && (
                              <rect
                                width={isMultiple ? 960 : 480}
                                height="480"
                                mask={`url(#print-area-${state})`}
                                fill="var(--mc-mask-color, #ed3737)"
                                opacity="0.46"
                              />
                            )}
                            {mask && !isMultiple && (
                              <path
                                d={clothOutline}
                                fill="none"
                                stroke="#FCE9DA"
                                strokeWidth="1.5"
                                strokeDasharray="4 3"
                              />
                            )}
                          </svg>
                        )}
                        {tool !== "placement" && (
                          <MaskBrushDock
                            controls={{
                              tool,
                              setTool,
                              showMask,
                              setShowMask,
                              brushSize,
                              setBrushSize,
                              canUndo: brushHistory.length > 0,
                              undo: () => {
                                setStrokes(strokes.slice(0, brushHistory.at(-1)));
                                setBrushHistory(brushHistory.slice(0, -1));
                              },
                              resetMask: () => {
                                setStrokes([]);
                                setBrushHistory([]);
                                setMask(true);
                              },
                            }}
                          />
                        )}
                      </div>
                      <div className="mg-canvas-foot">
                        <strong>
                          {tool !== "placement" ? "Mask preview" : "Placement preview"}
                        </strong>
                        <span>Simple overlay · open Preview to see folds and lighting.</span>
                      </div>
                      <p className="mg-canvas-hint">{currentTool}</p>
                    </>
                  ) : (
                    <div className="preview-grid">
                      <div className="preview-grid__head">
                        <span className="preview-grid__count">{"33 / 33"}</span>
                        <span className="preview-grid__status">{"Full quality"}</span>
                        <div className="preview-grid__actions">
                          <button
                            className={`btn ${renderStale ? "btn-danger" : "btn-secondary"}`}
                            disabled={!ready}
                            data-goto="marigold/preview"
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
                          <button className="btn btn-primary" data-goto="marigold/preparing">
                            Prepare template
                          </button>
                        </div>
                      ) : (
                        <>
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
                  <section className="realism" aria-label="Print realism">
                    <div className="realism__head">
                      <h3 className="realism__heading">Print realism</h3>
                      <button
                        className="btn btn-ghost"
                        onClick={() => {
                          setLight("Prepared garment lighting");
                          setShading(100);
                          setTexture(25);
                          setHighlights(0);
                        }}
                      >
                        Reset
                      </button>
                    </div>
                    <div className="mg-field-title">
                      <label className="mg-label" htmlFor={`lighting-${state}`}>
                        Lighting source
                      </label>
                      {infoButton("lighting")}
                    </div>
                    {infoText("lighting")}
                    <select
                      id={`lighting-${state}`}
                      className="input"
                      value={light}
                      onChange={(e) => setLight(e.target.value)}
                    >
                      <option>Prepared garment lighting</option>
                      <option>Photo-based lighting</option>
                    </select>
                    <Slider
                      label="Light & shadow strength"
                      value={shading}
                      onChange={setShading}
                      low="original design"
                      high="match cloth"
                      info={infoButton("shading")}
                    />
                    {infoText("shading")}
                    <Slider
                      label="Fabric texture"
                      value={texture}
                      onChange={setTexture}
                      low="smooth"
                      high="textured"
                      info={infoButton("texture")}
                    />
                    {infoText("texture")}
                    <Slider
                      label="Print shine"
                      value={highlights}
                      onChange={setHighlights}
                      low="matte"
                      high="shiny"
                      info={infoButton("highlights")}
                    />
                    {infoText("highlights")}
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
