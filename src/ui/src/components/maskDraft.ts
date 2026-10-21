import type { MaskOperation } from "../api/preparation";
type Stroke = Extract<MaskOperation, { type: "stroke" }>;
export function maskDraft(operations: MaskOperation[]): {
  automatic: boolean;
  strokes: Stroke[];
  undoSaved: number;
} {
  let automatic = false;
  let undoSaved = 0;
  const strokes: Stroke[] = [];
  for (const op of operations) {
    if (op.type === "reset") {
      automatic = true;
      strokes.length = 0;
      undoSaved = 0;
    } else if (op.type === "undo") {
      if (strokes.length) strokes.pop();
      else if (!automatic) undoSaved++;
    } else strokes.push(op);
  }
  return { automatic, strokes, undoSaved };
}
