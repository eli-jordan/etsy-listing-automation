import { useEffect, useRef, useState } from "react";
import {
  getTemplatePositionImpact,
  type TemplatePositionImpact,
} from "../../api/workspaceSettings";
import { type LimitDraft, ROWS, toLimits } from "./templateLimits";
import { AlarmDialog } from "./AlarmDialog";

type Impact =
  | { kind: "loading" }
  | { kind: "read"; impact: TemplatePositionImpact }
  | { kind: "failed"; message: string };

export function TemplateLimitsDialog({
  saved,
  draft,
  onCancel,
  onSave,
}: {
  saved: LimitDraft;
  draft: LimitDraft;
  onCancel: () => void;
  /** The refusal to show, or null once saved. */
  onSave: () => Promise<string | null>;
}) {
  const [impact, setImpact] = useState<Impact>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keep = useRef<HTMLButtonElement>(null);
  const candidate = useRef(toLimits(draft));

  useEffect(() => keep.current?.focus(), []);
  useEffect(() => {
    let active = true;
    getTemplatePositionImpact(candidate.current).then(
      (read) => active && setImpact({ kind: "read", impact: read }),
      (reason: unknown) =>
        active &&
        setImpact({
          kind: "failed",
          message: reason instanceof Error ? reason.message : "the read failed",
        }),
    );
    return () => {
      active = false;
    };
  }, []);

  const inference = impact.kind === "read" ? impact.impact.templates_needing_inference : [];
  const changes = ROWS.filter(({ key }) => saved[key] !== draft[key]).map(
    ({ key, label, unit }) => `${label}: ${saved[key]}${unit} → ${draft[key]}${unit}`,
  );

  const confirm = async () => {
    setBusy(true);
    setError(null);
    const failure = await onSave().catch((reason: unknown) =>
      reason instanceof Error ? reason.message : "Could not save settings.yaml",
    );
    if (failure !== null) {
      setError(failure);
      setBusy(false);
    }
  };

  return (
    <AlarmDialog
      titleId="tl-confirm"
      title={inference.length > 0 ? `Refit ${templates(inference.length)}?` : "Save new limits?"}
      lede={
        inference.length > 0
          ? "It runs in the background. You can keep working."
          : "Listings are checked against them the next time they render or deploy."
      }
      onCancel={onCancel}
    >
      <div className="sa-modal__body">
        <ul className="sp-modal__facts">
          <li>
            <strong>{changes.join("; ")}.</strong>
            {inference.length > 0 && (
              <>
                {" "}
                {listed(inference)} {inference.length === 1 ? "needs its" : "need their"}{" "}
                preparation extended to cover the wider limits; the Marigold model runs once per
                template in the background.
              </>
            )}
          </li>
          <li>
            <Outside impact={impact} />
          </li>
        </ul>
        {error !== null && (
          <p className="adm-error-text" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="sa-modal__foot sd-foot">
        <button ref={keep} type="button" className="btn btn-ghost" onClick={onCancel}>
          Keep current limits
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || impact.kind === "loading"}
          onClick={() => void confirm()}
        >
          {inference.length > 0 ? "Save and refit" : "Save"}
        </button>
      </div>
    </AlarmDialog>
  );
}

function Outside({ impact }: { impact: Impact }) {
  if (impact.kind === "loading") return <span role="status">Checking saved positions…</span>;
  if (impact.kind === "failed")
    return (
      <>
        <strong>Could not check saved positions.</strong> {impact.message}. The next plan still
        blocks any listing outside the new limits.
      </>
    );
  const { outside } = impact.impact;
  if (outside.length === 0)
    return (
      <>
        <strong>Nothing else changes.</strong> Saved positions stay as they are; none fall outside
        the new limits.
      </>
    );
  return (
    <>
      <strong>
        {outside.length === 1 ? "1 listing falls" : `${outside.length} listings fall`} outside the
        new limits:
      </strong>{" "}
      {listed(outside.map((row) => row.listing))}; they will block deploying until edited.
    </>
  );
}

function templates(count: number): string {
  return count === 1 ? "1 Marigold template" : `${count} Marigold templates`;
}

const listFormat = new Intl.ListFormat("en-GB", { type: "conjunction" });

function listed(names: readonly string[]): string {
  return listFormat.format(names);
}
