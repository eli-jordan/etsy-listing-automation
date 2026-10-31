import { useRef, useState } from "react";
import { useWorkspaceSettings } from "./useWorkspaceSettings";
import { MarketWeights } from "./MarketWeights";
import { AiSettingsSections } from "./AiTimeLimits";
import "./settings.css";

export function SettingsPanel() {
  const state = useWorkspaceSettings();
  const { settings, status } = state;
  if (state.loadError)
    return (
      <div className="adm-warn" role="alert">
        <span>{state.loadError}</span>
        <button className="btn btn-secondary" onClick={() => void state.reload()}>
          Check file again
        </button>
      </div>
    );
  if (!settings) return <p role="status">Loading settings…</p>;
  return (
    <div className="settings-panels">
      {state.locked && (
        <div className="adm-warn" role="alert">
          <span>
            Settings changed on disk. Nothing was overwritten. Reload, then make your change again.
          </span>
          <button className="btn btn-secondary" onClick={() => void state.reload()}>
            Reload settings
          </button>
        </div>
      )}
      <div role="status" className="adm-save settings-save">
        {status.kind === "saving"
          ? "Saving…"
          : status.kind === "saved"
            ? "Saved"
            : status.kind === "error"
              ? status.message
              : ""}
      </div>
      {status.kind === "error" && (
        <button className="btn btn-secondary" onClick={state.retry}>
          Retry save
        </button>
      )}
      <fieldset disabled={state.locked} className="settings-fields">
        <AiSettingsSections
          key={`ai-${state.loadedVersion}`}
          providers={settings.providers}
          limits={{ step: settings.step_limit_minutes, run: settings.run_limit_minutes }}
          locked={state.locked}
          fieldErrors={state.fieldErrors}
          onSave={state.save}
        />
        <Batch
          key={state.loadedVersion}
          initial={settings.concurrency}
          onSave={(concurrency) => state.save({ concurrency })}
        />
        {state.fieldErrors["batch_ai.concurrency"] && (
          <p role="alert">{state.fieldErrors["batch_ai.concurrency"]}</p>
        )}
        <MarketWeights
          key={`market-${state.loadedVersion}`}
          weights={settings.weights}
          defaults={settings.default_weights}
          locked={state.locked}
          onSave={(weights) => state.save({ weights })}
        />
        {Object.entries(state.fieldErrors)
          .filter(([key]) => key.startsWith("market_seo"))
          .map(([key, message]) => (
            <p role="alert" key={key}>
              {key}: {message}
            </p>
          ))}
      </fieldset>
    </div>
  );
}

function Batch({ initial, onSave }: { initial: number; onSave: (value: number) => void }) {
  const [value, setValue] = useState(initial);
  const completed = useRef(initial);
  const commit = () => {
    if (value === completed.current) return;
    completed.current = value;
    onSave(value);
  };
  return (
    <section className="b-panel" aria-labelledby="settings-batch">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="settings-batch">
            Batch AI
          </h2>
          <p className="b-panel__lede">
            How many batch listings draft at once. The next dispatch uses this limit; already
            running drafts finish. Editor runs don't count against it.
          </p>
        </div>
      </div>
      <div className="sp-slider">
        <span className="sp-slider__value" aria-hidden="true">
          <strong>{value}</strong> {value === 1 ? "listing" : "listings"} at once
        </span>
        <input
          type="range"
          min={1}
          max={8}
          step={1}
          value={value}
          aria-label="Listings drafted at once"
          aria-valuetext={`${value} at once`}
          style={{ ["--sp-fill" as string]: `${((value - 1) / 7) * 100}%` }}
          onChange={(event) => setValue(Number(event.target.value))}
          onPointerUp={commit}
          onKeyUp={commit}
          onBlur={commit}
        />
        <div className="sp-slider__ticks" aria-hidden="true">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
            <span key={n} className={n === value ? "is-on" : undefined}>
              {n}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
