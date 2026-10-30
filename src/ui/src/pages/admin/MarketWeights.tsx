import { useRef, useState, type PointerEvent } from "react";
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { METRICS, sharesOf, weightsOf } from "./marketShares";

const SEG = [
  "var(--color-accent-600)",
  "var(--color-accent-400)",
  "var(--color-accent-2-600)",
  "var(--color-accent-2-400)",
  "var(--color-neutral-600)",
  "var(--color-neutral-400)",
];
const edgesOf = (shares: number[]) =>
  shares.slice(0, -1).map((_, i) => shares.slice(0, i + 1).reduce((a, b) => a + b, 0));

export function MarketWeights({
  weights,
  defaults,
  locked,
  onSave,
}: {
  weights: Record<string, number>;
  defaults: Record<string, number>;
  locked: boolean;
  onSave: (weights: Record<string, number>) => void;
}) {
  const [shares, setShares] = useState(() => sharesOf(weights));
  const current = useRef(shares);
  const completed = useRef(shares);
  const [active, setActive] = useState<number | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    stack: number[];
    x: number;
    index: number | null;
    before: number[];
  } | null>(null);
  const edges = edgesOf(shares);
  const fallback = sharesOf(defaults);
  const update = (next: number[]) => {
    current.current = next;
    setShares(next);
  };
  const commit = () => {
    if (locked || current.current.every((value, i) => value === completed.current[i])) return;
    completed.current = current.current;
    onSave(weightsOf(current.current));
  };
  const move = (index: number, percent: number) => {
    const limits = edgesOf(current.current);
    const lo = index === 0 ? 0 : (limits[index - 1] ?? 0);
    const hi = limits[index + 1] ?? 100;
    const at = Math.round(Math.min(hi, Math.max(lo, percent)));
    const next = [...current.current];
    next[index] = at - lo;
    next[index + 1] = hi - at;
    update(next);
  };
  const onDown = (event: PointerEvent<HTMLSpanElement>, index: number) => {
    if (locked || event.button !== 0 || drag.current) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    const stack = edges.map((edge, i) => (edge === edges[index] ? i : -1)).filter((i) => i >= 0);
    drag.current = {
      stack,
      x: event.clientX,
      index: stack.length === 1 ? index : null,
      before: current.current,
    };
    setActive(drag.current.index);
  };
  const onMove = (event: PointerEvent<HTMLSpanElement>) => {
    const pending = drag.current;
    const rect = bar.current?.getBoundingClientRect();
    if (locked || !pending || !rect?.width) return;
    if (pending.index === null) {
      const dx = event.clientX - pending.x;
      if (Math.abs(dx) < 2) return;
      // Stacked zero shares: either outward direction restores a neighbor.
      // Every divider remains separately reachable with Tab and arrow keys.
      pending.index = dx < 0 ? Math.min(...pending.stack) : Math.max(...pending.stack);
      setActive(pending.index);
    }
    move(pending.index, ((event.clientX - rect.left) / rect.width) * 100);
  };
  const finish = () => {
    if (!drag.current) return;
    drag.current = null;
    setActive(null);
    commit();
  };
  const cancel = () => {
    if (drag.current) update(drag.current.before);
    drag.current = null;
    setActive(null);
  };

  return (
    <section className="b-panel" aria-labelledby="settings-market">
      <div className="b-panel__head">
        <div>
          <h2 className="b-panel__title" id="settings-market">
            Market SEO scoring
          </h2>
          <p className="b-panel__lede">
            How much each signal counts when ranking comparable Etsy listings. Drag the dividers to
            share out 100%; the arrow keys move a focused divider by 1 (Shift for 5).
          </p>
        </div>
      </div>
      <div className="sp-weights" ref={bar}>
        {shares.map((share, i) => (
          <span
            key={METRICS[i]?.key}
            className="sp-weights__seg"
            style={{ width: `${share}%`, background: SEG[i] }}
            title={`${METRICS[i]?.label}: ${share}%`}
          >
            {share >= 9 ? `${share}%` : ""}
          </span>
        ))}
        {edges.map((edge, i) => (
          <span
            key={i}
            role="separator"
            tabIndex={locked ? -1 : 0}
            aria-disabled={locked}
            aria-orientation="vertical"
            aria-label={`Between ${METRICS[i]?.label} and ${METRICS[i + 1]?.label}`}
            aria-valuenow={edge}
            aria-valuemin={edges[i - 1] ?? 0}
            aria-valuemax={edges[i + 1] ?? 100}
            aria-valuetext={`${METRICS[i]?.label} ${shares[i]}%, ${METRICS[i + 1]?.label} ${shares[i + 1]}%`}
            className={`sp-weights__divider${active === i ? " is-active" : ""}`}
            style={{ left: `${edge}%`, zIndex: active === i ? 20 : 10 + i }}
            onPointerDown={(event) => onDown(event, i)}
            onPointerMove={onMove}
            onPointerUp={finish}
            onPointerCancel={cancel}
            onLostPointerCapture={finish}
            onKeyDown={(event) => {
              if (locked || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
              event.preventDefault();
              move(
                i,
                (edgesOf(current.current)[i] ?? 0) +
                  (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 5 : 1),
              );
              commit();
            }}
          >
            <span className="sp-weights__grip" />
          </span>
        ))}
      </div>
      <ul className="sp-legend">
        {METRICS.map((metric, i) => (
          <li key={metric.key} className={shares[i] === 0 ? "is-zero" : undefined}>
            <span
              className="b-share__key"
              style={{ background: shares[i] ? SEG[i] : "transparent" }}
            />
            <span className="sp-legend__text">
              <span className="b-weight__label">{metric.label}</span>
              <span className="b-weight__pct">{metric.hint}</span>
            </span>
            <span className="sp-legend__pct">
              {shares[i] === 0 ? "Not counted" : `${shares[i]}%`}
            </span>
          </li>
        ))}
      </ul>
      <div className="sp-market-foot">
        <span className="s-muted">
          A signal at 0% is not counted. Drag its divider out to bring it back.
        </span>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={locked || shares.every((value, i) => value === fallback[i])}
          onClick={() => {
            update(fallback);
            commit();
          }}
        >
          <ArrowCounterClockwiseIcon size={15} /> Reset to defaults
        </button>
      </div>
    </section>
  );
}
