import { useId } from "react";

/** A plain garment drawing with the resolved artwork on the chest -- stands in
 * for the profile's colour-matrix preview template, so each frame shows the
 * actual ink on the actual cloth. */
export function ShirtPreview({
  colour,
  artwork,
  label,
}: {
  colour: string;
  artwork: string | null;
  label: string;
}) {
  const shade = useId();
  return (
    <svg className="ma-shirt" viewBox="0 0 400 420" role="img" aria-label={label}>
      <defs>
        <linearGradient id={shade} x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.14" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0" />
          <stop offset="1" stopColor="#000" stopOpacity="0.18" />
        </linearGradient>
      </defs>
      <path
        d="M140 34 C160 56 240 56 260 34 L344 70 L384 158 L322 184 L312 156 L314 402 L86 402 L88 156 L78 184 L16 158 L56 70 Z"
        fill={colour}
      />
      <path
        d="M140 34 C160 56 240 56 260 34 L344 70 L384 158 L322 184 L312 156 L314 402 L86 402 L88 156 L78 184 L16 158 L56 70 Z"
        fill={`url(#${shade})`}
      />
      <path d="M140 34 C156 70 244 70 260 34" fill="none" stroke="#000" strokeOpacity="0.18" strokeWidth="5" />
      {artwork !== null && <image href={artwork} x="130" y="104" width="140" height="140" />}
    </svg>
  );
}
