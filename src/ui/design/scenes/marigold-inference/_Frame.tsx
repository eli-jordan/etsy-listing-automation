import { useState } from "react";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { MarigoldScreen } from "./_MarigoldScreen";
import "./_inference.css";
type Key = "num_inference_steps" | "ensemble_size";
const defaults = { num_inference_steps: 10, ensemble_size: 3 };
const info = {
  num_inference_steps: {
    title: "Refinement steps",
    body: "The number of denoising steps in each prediction. More steps take longer and may improve the result; extra steps do not guarantee better folds.",
    link: "https://huggingface.co/docs/diffusers/main/using-diffusers/marigold_usage#speeding-up-inference",
  },
  ensemble_size: {
    title: "Combined predictions",
    body: "The number of predictions combined for each map. More predictions can reduce inconsistent estimates, at the cost of preparation time. Three or more also enable uncertainty estimates.",
    link: "https://huggingface.co/docs/diffusers/main/using-diffusers/marigold_usage#maximizing-precision-and-ensembling",
  },
};
export function InferenceFrame({ variant }: { variant: "inline" | "drawer" | "dialog" }) {
  const [values, setValues] = useState(defaults);
  const [opened, setOpened] = useState(true);
  const [selected, setSelected] = useState<Key>("num_inference_steps");
  const [saved, setSaved] = useState(false);
  const reset = () => {
    setValues({ ...defaults });
    setSaved(false);
  };
  const input = (key: Key) => (
    <input
      id={"mi-" + key}
      type="number"
      min={1}
      max={key === "num_inference_steps" ? 50 : 10}
      step={1}
      value={values[key]}
      onFocus={() => setSelected(key)}
      onChange={(e) => {
        setValues({ ...values, [key]: Number(e.target.value) });
        setSaved(false);
      }}
    />
  );
  const label = (key: Key) => (
    <label htmlFor={"mi-" + key}>
      <code>{key}</code>
      <button
        type="button"
        className="mi-info-button"
        aria-label={"About " + key}
        onClick={() => setSelected(key)}
      >
        <InfoIcon />
      </button>
    </label>
  );
  const card = (key: Key) => (
    <div className="mi-info-card">
      <div className="mi-info-title">
        <InfoIcon />
        <strong>{info[key].title}</strong>
      </div>
      <p>{info[key].body}</p>
      <a href={info[key].link} target="_blank" rel="noreferrer">
        Marigold documentation ↗
      </a>
    </div>
  );
  const resetButton = (
    <button className="mi-reset" onClick={reset}>
      <ArrowCounterClockwiseIcon />
      Reset to defaults
    </button>
  );
  const note = (
    <p className="mi-notice">Changes take effect the next time you prepare this template.</p>
  );
  const keys = Object.keys(defaults) as Key[];
  const fields = (
    <div className="mi-fields">
      {keys.map((key) => (
        <div className="mi-field" key={key}>
          {label(key)}
          {input(key)}
          <span className="mi-default">Default: {defaults[key]}</span>
        </div>
      ))}
    </div>
  );
  const launch = (
    <button className="btn btn-secondary mi-launch" onClick={() => setOpened(true)}>
      Advanced inference <span>→</span>
    </button>
  );
  const advanced =
    variant === "inline" ? (
      <section className="realism mi-inline">
        <button
          className="mi-section-toggle"
          aria-expanded={opened}
          onClick={() => setOpened(!opened)}
        >
          <strong>Advanced inference</strong>
          <CaretDownIcon />
        </button>
        {opened && (
          <>
            {note}
            {fields}
            {card(selected)}
            {resetButton}
            <span className="mi-save-state" role="status">
              {saved ? "Saved" : "Applies on preparation"}
            </span>
          </>
        )}
      </section>
    ) : (
      <>
        {launch}
        {opened && (
          <div
            className={"mi-backdrop mi-" + variant}
            onKeyDown={(e) => {
              if (e.key === "Escape") setOpened(false);
            }}
          >
            <section
              className="mi-sheet"
              role="dialog"
              aria-modal="true"
              aria-label="Advanced inference"
            >
              <header>
                <div>
                  <span className="mi-eyebrow">HANGING ON FENCE</span>
                  <h2>Advanced inference</h2>
                  <p>Custom settings for Marigold map preparation.</p>
                </div>
                <button
                  className="mi-close"
                  aria-label="Close advanced inference"
                  onClick={() => setOpened(false)}
                >
                  ×
                </button>
              </header>
              {variant === "drawer" ? (
                <div className="mi-sheet-body">
                  {note}
                  {keys.map((key) => (
                    <section className="mi-setting-card" key={key}>
                      <div className="mi-field">
                        {label(key)}
                        {input(key)}
                        <span className="mi-default">Default: {defaults[key]}</span>
                      </div>
                      {card(key)}
                    </section>
                  ))}
                </div>
              ) : (
                <div className="mi-dialog-body">
                  <div>
                    {note}
                    {fields}
                  </div>
                  <aside>
                    {card("num_inference_steps")}
                    {card("ensemble_size")}
                  </aside>
                </div>
              )}
              <footer>
                {resetButton}
                <button
                  className="btn btn-primary"
                  onClick={() => {
                    setSaved(true);
                    setOpened(false);
                  }}
                >
                  Save settings
                </button>
              </footer>
            </section>
          </div>
        )}
        {saved && (
          <p className="mi-saved" role="status">
            Settings saved · preparation needed
          </p>
        )}
      </>
    );
  return (
    <div className={"mi-frame mi-layout-" + variant}>
      <MarigoldScreen state="edit" advancedControls={advanced} />
    </div>
  );
}
