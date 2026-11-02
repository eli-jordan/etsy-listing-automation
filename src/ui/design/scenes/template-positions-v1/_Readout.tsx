import { deg, outOfRange, partsAtLimit, pct, signedPct, type Bounds, type Part, type Pose } from "./_geometry";

interface Row {
  part: Part;
  label: string;
  value: string;
  range: string;
  /** 0..1 along the allowed range; may fall outside when the pose is stale. */
  at: number;
}

function rows(p: Pose, b: Bounds): Row[] {
  const along = (v: number, lo: number, hi: number) => (v - lo) / (hi - lo);
  return [
    { part: "scale", label: "Size", value: pct(p.scale), range: `${pct(b.scaleMin)}–${pct(b.scaleMax)}`, at: along(p.scale, b.scaleMin, b.scaleMax) },
    { part: "dx", label: "Across", value: signedPct(p.dx), range: `±${pct(b.offset)}`, at: along(p.dx, -b.offset, b.offset) },
    { part: "dy", label: "Up/down", value: signedPct(p.dy), range: `±${pct(b.offset)}`, at: along(p.dy, -b.offset, b.offset) },
    { part: "rotation", label: "Tilt", value: deg(p.rotation), range: `±${b.rotation}°`, at: along(p.rotation, -b.rotation, b.rotation) },
  ];
}

/** Each part of the pose against its limit. A part on its limit says so in
 * words, not just colour; a part past it (a stale position) turns red. */
export function Readout({ pose, limits, layout }: { pose: Pose; limits: Bounds; layout: "row" | "column" }) {
  const atLimit = partsAtLimit(pose, limits);
  const out = outOfRange(pose, limits);
  return (
    <dl className={`tp-readout tp-readout--${layout}`}>
      {rows(pose, limits).map((r) => {
        const state = out.has(r.part) ? "out" : atLimit.has(r.part) ? "limit" : "ok";
        return (
          <div key={r.part} className={`tp-read tp-read--${state}`}>
            <dt>{r.label}</dt>
            <dd>
              <span className="tp-read__value">{r.value}</span>
              <span className="tp-meter" aria-hidden="true">
                <span className="tp-meter__mid" />
                <span className="tp-meter__dot" style={{ left: `${Math.min(1, Math.max(0, r.at)) * 100}%` }} />
              </span>
              <span className="tp-read__range">
                {state === "limit" ? "at limit" : state === "out" ? `outside ${r.range}` : r.range}
              </span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
