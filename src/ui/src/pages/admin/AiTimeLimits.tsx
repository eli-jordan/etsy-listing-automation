import { useRef, useState } from "react";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import type { ProviderPreference, SettingsChanges } from "../../api/workspaceSettings";
import { AiProviders } from "./AiProviders";

const STEP_MIN = 1;
const STEP_MAX = 15;
const RUN_MIN = 5;
const RUN_MAX = 60;

/** ADR-0057: the whole run must cover every enabled provider's step. */
const runFloor = (enabled: number, step: number) => Math.max(RUN_MIN, enabled * step);

type Limits = { step: number; run: number };
const enabledCount = (providers: ProviderPreference[]) =>
  providers.filter((p) => p.enabled ?? true).length;

/** AI providers and AI time limits share one coordinator, because an
 * enabled provider or a larger step can raise the run limit. The raise is
 * saved in the same write as its cause, so settings.yaml never holds a run
 * limit below the floor. Lowering either never lowers the run limit.
 */
export function AiSettingsSections({
  providers,
  limits,
  locked,
  fieldErrors,
  onSave,
}: {
  providers: ProviderPreference[];
  limits: Limits;
  locked: boolean;
  fieldErrors: Record<string, string>;
  onSave: (changes: SettingsChanges) => void;
}) {
  const [enabled, setEnabled] = useState(() => enabledCount(providers));
  const [live, setLive] = useState(limits);
  const committed = useRef(limits);
  const [notice, setNotice] = useState("");

  const saveProviders = (next: ProviderPreference[]) => {
    const count = enabledCount(next);
    setEnabled(count);
    const floor = runFloor(count, committed.current.step);
    if (floor <= committed.current.run) {
      onSave({ providers: next });
      return;
    }
    setNotice(
      `Run limit increased from ${committed.current.run} to ${floor} minutes because another provider is on.`,
    );
    committed.current = { ...committed.current, run: floor };
    setLive((current) => ({ ...current, run: Math.max(current.run, floor) }));
    onSave({ providers: next, run_limit_minutes: floor });
  };

  const change = (step: number, run: number) => {
    const floor = runFloor(enabled, step);
    const saved = committed.current.run;
    if (step !== live.step)
      setNotice(
        floor > saved
          ? `Run limit increased from ${saved} to ${floor} minutes to allow ${enabled} ${
              enabled === 1 ? "provider" : "providers"
            } × ${step} minutes.`
          : "",
      );
    setLive({ step, run: Math.max(run, floor) });
  };

  const commit = () => {
    const changes: SettingsChanges = {};
    if (live.step !== committed.current.step) changes.step_limit_minutes = live.step;
    if (live.run !== committed.current.run) changes.run_limit_minutes = live.run;
    if (!Object.keys(changes).length || locked) return;
    committed.current = live;
    onSave(changes);
  };

  return (
    <>
      <AiProviders initial={providers} locked={locked} onSave={saveProviders} />
      <Errors errors={fieldErrors} prefix="ai.providers" />
      <TimeLimits
        step={live.step}
        run={live.run}
        enabled={enabled}
        notice={notice}
        onChange={change}
        onCommit={commit}
        errors={fieldErrors}
      />
    </>
  );
}

function Errors({ errors, prefix }: { errors: Record<string, string>; prefix: string }) {
  return (
    <>
      {Object.entries(errors)
        .filter(([key]) => key.startsWith(prefix) || (prefix === "ai.providers" && key === "ai"))
        .map(([key, message]) => (
          <p role="alert" key={key}>
            {key}: {message}
          </p>
        ))}
    </>
  );
}

function TimeLimits({
  step,
  run,
  enabled,
  notice,
  onChange,
  onCommit,
  errors,
}: {
  step: number;
  run: number;
  enabled: number;
  notice: string;
  onChange: (step: number, run: number) => void;
  onCommit: () => void;
  errors: Record<string, string>;
}) {
  const floor = runFloor(enabled, step);
  return (
    <section className="b-panel" aria-labelledby="settings-limits">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="settings-limits">
            AI time limits
          </h2>
          <p className="b-panel__lede">
            Applies to every AI run, including briefs, market queries and batch drafts. Changes
            start with the next run.
          </p>
        </div>
      </div>
      <div className="sp-limits">
        <div className="sp-slider">
          <label className="sp-slider__value" htmlFor="settings-step-limit">
            Per step <strong>{step} min</strong>
          </label>
          <p className="sp-limit-hint">
            One provider attempt and its repair share this time. A fallback provider gets a fresh
            allowance.
          </p>
          <input
            id="settings-step-limit"
            type="range"
            min={STEP_MIN}
            max={STEP_MAX}
            step={1}
            value={step}
            aria-valuetext={`${step} minutes per step`}
            style={{
              ["--sp-fill" as string]: `${((step - STEP_MIN) / (STEP_MAX - STEP_MIN)) * 100}%`,
            }}
            onChange={(event) => onChange(Number(event.target.value), run)}
            onPointerUp={onCommit}
            onKeyUp={onCommit}
            onBlur={onCommit}
          />
          <div className="sp-slider__ticks" aria-hidden="true">
            <span>{STEP_MIN} min</span>
            <span>{STEP_MAX} min</span>
          </div>
        </div>
        <div className="sp-slider">
          <label className="sp-slider__value" htmlFor="settings-run-limit">
            Whole run <strong>{run} min</strong>
          </label>
          <p className="sp-limit-hint">
            The upper bound for all attempts and research together. Running jobs keep their current
            limit.
          </p>
          <input
            id="settings-run-limit"
            type="range"
            min={floor}
            max={RUN_MAX}
            step={1}
            value={run}
            aria-valuetext={`${run} minutes for the whole run; minimum ${floor}`}
            style={{
              ["--sp-fill" as string]: `${
                floor === RUN_MAX ? 100 : ((run - floor) / (RUN_MAX - floor)) * 100
              }%`,
            }}
            onChange={(event) => onChange(step, Number(event.target.value))}
            onPointerUp={onCommit}
            onKeyUp={onCommit}
            onBlur={onCommit}
          />
          <div className="sp-slider__ticks" aria-hidden="true">
            <span>{floor} min</span>
            <span>{RUN_MAX} min</span>
          </div>
        </div>
      </div>
      <p className="sp-floor">
        Minimum whole run: <strong>{floor} minutes</strong> with {enabled} enabled{" "}
        {enabled === 1 ? "provider" : "providers"} × {step} minutes per step
        {enabled * step < RUN_MIN ? ` (${RUN_MIN}-minute minimum)` : ""}.
      </p>
      <div role="status" className={notice ? "adm-warn sp-notice" : undefined}>
        {notice && (
          <>
            <WarningIcon size={18} />
            <span>{notice} Both values save together.</span>
          </>
        )}
      </div>
      <p className="sp-limit-hint">
        Turning a provider off or lowering the step limit leaves your whole-run limit where you set
        it.
      </p>
      <Errors errors={errors} prefix="ai.step_limit_minutes" />
      <Errors errors={errors} prefix="ai.run_limit_minutes" />
    </section>
  );
}
