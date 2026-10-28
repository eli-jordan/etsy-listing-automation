import { useId } from "react";

const BODY =
  "M140 34 C160 56 240 56 260 34 L344 70 L384 158 L322 184 L312 156 L314 402 L86 402 L88 156 L78 184 L16 158 L56 70 Z";

/**
 * A plain shirt drawing in `cloth` with `artwork` on the chest: the design
 * strip judges a file on the shirt it prints on, so light ink on a light
 * shirt reads as the problem it is. `artwork` is an image URL, or `null` for
 * an empty slot.
 */
export function ShirtThumb({
  cloth,
  artwork,
  className = "shirt-thumb",
}: {
  cloth: string;
  artwork: string | null;
  className?: string;
}) {
  const shade = useId();
  return (
    <svg className={className} viewBox="0 0 400 420" aria-hidden="true">
      <defs>
        <linearGradient id={shade} x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.14" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0" />
          <stop offset="1" stopColor="#000" stopOpacity="0.18" />
        </linearGradient>
      </defs>
      {/* An outline, so a light shirt still has an edge on a light card. */}
      <path d={BODY} fill={cloth} stroke="#000" strokeOpacity="0.14" strokeWidth="5" />
      <path d={BODY} fill={`url(#${shade})`} />
      <path
        d="M140 34 C156 70 244 70 260 34"
        fill="none"
        stroke="#000"
        strokeOpacity="0.18"
        strokeWidth="5"
      />
      {artwork !== null && <image href={artwork} x="130" y="104" width="140" height="140" />}
    </svg>
  );
}
