// Selected dialog layout. Local prototype state only; no inference is started.
import { useEffect, useRef, useState } from "react";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import "./_inference.css";
const defaults = { num_inference_steps: 10, ensemble_size: 3 };
type Key = keyof typeof defaults;
const fields = {
  num_inference_steps: {
    name: "Inference steps",
    body: "The number of denoising steps in each prediction. More steps take longer and may improve the result; extra steps do not guarantee better folds.",
    link: "https://huggingface.co/docs/diffusers/main/using-diffusers/marigold_usage#speeding-up-inference",
  },
  ensemble_size: {
    name: "Ensemble size",
    body: "The number of predictions combined for each map. More predictions can reduce inconsistent estimates, at the cost of preparation time. Three or more also enable uncertainty estimates.",
    link: "https://huggingface.co/docs/diffusers/main/using-diffusers/marigold_usage#maximizing-precision-and-ensembling",
  },
};
export function InferenceSettings({
  initialOpen = false,
  templateName,
}: {
  initialOpen?: boolean;
  templateName: string;
}) {
  const [open, setOpen] = useState(initialOpen);
  const [saved, setSaved] = useState(defaults);
  const [draft, setDraft] = useState(defaults);
  const [changed, setChanged] = useState(false);
  const [highlight, setHighlight] = useState<Key | null>(null);
  const dialog = useRef<HTMLElement>(null);
  const launch = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) dialog.current?.querySelector<HTMLInputElement>("input")?.focus();
  }, [open]);
  const close = () => {
    setOpen(false);
    launch.current?.focus();
  };
  return (
    <div className="mi-frame">
      <button
        ref={launch}
        className="btn btn-secondary mi-launch"
        onClick={() => {
          setDraft({ ...saved });
          setOpen(true);
        }}
      >
        Advanced settings <span>→</span>
      </button>
      {changed && (
        <p className="mi-saved" role="status">
          Settings saved · preparation needed
        </p>
      )}
      {open && (
        <div
          className="mi-backdrop mi-dialog"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              close();
            }
            if (e.key === "Tab") {
              const elements = dialog.current?.querySelectorAll<HTMLElement>(
                "button:not(:disabled), input, a[href]",
              );
              if (!elements?.length) return;
              const first = elements[0],
                last = elements[elements.length - 1];
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last?.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first?.focus();
              }
            }
          }}
        >
          <section
            ref={dialog}
            className="mi-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mi-heading"
          >
            <header>
              <div>
                <span className="mi-eyebrow">{templateName}</span>
                <h2 id="mi-heading">Advanced Marigold Settings</h2>
                <p>Custom settings for Marigold map preparation.</p>
              </div>
              <button className="mi-close" aria-label="Close advanced inference" onClick={close}>
                ×
              </button>
            </header>
            <div className="mi-dialog-body">
              <div>
                <p className="mi-notice">
                  Changes take effect the next time you prepare this template.
                </p>
                <div className="mi-fields">
                  {(Object.keys(fields) as Key[]).map((key) => (
                    <div className="mi-field" key={key}>
                      <div className="mi-label-row">
                        <label htmlFor={"mi-" + key}>{fields[key].name}</label>
                        <button
                          className="mi-info-button"
                          aria-label={"About " + fields[key].name}
                          onClick={() => setHighlight(key)}
                        >
                          <InfoIcon />
                        </button>
                      </div>
                      <input
                        id={"mi-" + key}
                        aria-describedby={"mi-help-" + key}
                        type="number"
                        min={1}
                        max={key === "num_inference_steps" ? 50 : 10}
                        step={1}
                        value={draft[key]}
                        onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
                      />
                      <span className="mi-default">Default: {defaults[key]}</span>
                    </div>
                  ))}
                </div>
              </div>
              <aside>
                {(Object.keys(fields) as Key[]).map((key) => (
                  <div
                    id={"mi-help-" + key}
                    className={"mi-info-card" + (highlight === key ? " mi-info-highlight" : "")}
                    key={key}
                  >
                    <div className="mi-info-title">
                      <InfoIcon />
                      <strong>{fields[key].name}</strong>
                    </div>
                    <p>{fields[key].body}</p>
                    <a href={fields[key].link} target="_blank" rel="noreferrer">
                      Marigold documentation ↗
                    </a>
                  </div>
                ))}
              </aside>
            </div>
            <footer>
              <button className="mi-reset" onClick={() => setDraft({ ...defaults })}>
                <ArrowCounterClockwiseIcon />
                Reset to defaults
              </button>
              <button
                className="btn btn-primary"
                onClick={() => {
                  setSaved({ ...draft });
                  setChanged(true);
                  close();
                }}
              >
                Save settings
              </button>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
