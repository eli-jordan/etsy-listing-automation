import type { PriceRow } from "./comparison";

/**
 * Per-size price table, shown only when a price changed (spec's "Price
 * table" element). Rows come straight from `comparison.ts`'s `priceRows` --
 * built from the engine's own `PriceChange`s, grouped by size -- so a red
 * "below cost" mark here is never a second copy of `publish`'s own rule
 * (A30).
 */

function difference(before: string | null, after: string | null): string {
  if (before === null || after === null) return "no change";
  const currency = after.split(" ").pop() ?? "";
  const delta = Number.parseFloat(after) - Number.parseFloat(before);
  if (delta === 0) return "no change";
  const sign = delta > 0 ? "+" : "−";
  return `${sign}${Math.abs(delta)} ${currency}`;
}

export function PriceTable({ rows }: { rows: PriceRow[] }) {
  if (rows.length === 0) return null;

  return (
    <div className="dv-prices">
      <table>
        <thead>
          <tr>
            <th scope="col">Size</th>
            <th scope="col">On Etsy now</th>
            <th scope="col">After apply</th>
            <th scope="col">Difference</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.size}>
              <th scope="row">{row.size}</th>
              <td className="dv-tnum">{row.before ?? "—"}</td>
              <td className={`dv-tnum${row.belowCost ? " dv-bad" : row.changed ? " dv-up" : ""}`}>
                {row.after ?? "—"}
                {row.belowCost && " · below cost"}
              </td>
              <td className="dv-tnum">{difference(row.before, row.after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
