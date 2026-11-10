// Text comparison for the drift directions: the app's own word diff, narrowed
// so a changed word marks only the characters that differ, and paragraphs that
// match folded away.
import { wordDiff, type WordDiffToken } from "../../../src/pages/deploy/wordDiff";

type Segment = { kind: "same" | "del" | "ins"; text: string };

function sharedEnds(a: string, b: string): { start: number; end: number } {
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let end = 0;
  while (
    end < a.length - start &&
    end < b.length - start &&
    a[a.length - 1 - end] === b[b.length - 1 - end]
  ) {
    end++;
  }
  return { start, end };
}

/** A one-word substitution, marked only where the two words differ. */
function narrowed(del: string, ins: string): Segment[] {
  const { start, end } = sharedEnds(del, ins);
  const parts: Segment[] = [
    { kind: "same", text: del.slice(0, start) },
    { kind: "del", text: del.slice(start, del.length - end) },
    { kind: "ins", text: ins.slice(start, ins.length - end) },
    { kind: "same", text: del.slice(del.length - end) + " " },
  ];
  return parts.filter((part) => part.text.length > 0);
}

function segments(tokens: WordDiffToken[]): Segment[] {
  const out: Segment[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i] as WordDiffToken;
    const next = tokens[i + 1];
    const prev = tokens[i - 1];
    const lonePair =
      token.type === "del" && next?.type === "ins" && tokens[i + 2]?.type !== "ins" && prev?.type !== "del";
    if (lonePair) {
      out.push(...narrowed(token.text, next.text));
      i++;
    } else {
      out.push({ kind: token.type, text: `${token.text} ` });
    }
  }
  return out;
}

export type DiffSide = "from" | "to" | "unified";

function visible(kind: Segment["kind"], side: DiffSide): boolean {
  if (side === "unified" || kind === "same") return true;
  return side === "from" ? kind === "del" : kind === "ins";
}

export function DiffText({ from, to, side }: { from: string; to: string; side: DiffSide }) {
  return segments(wordDiff(from, to))
    .filter((segment) => visible(segment.kind, side))
    .map((segment, index) => (
      <span key={index} className={segment.kind === "same" ? undefined : `dv-${segment.kind}`}>
        {segment.text}
      </span>
    ));
}

export type ParagraphGroup =
  | { type: "same"; paragraphs: string[] }
  | { type: "diff"; from: string; to: string };

/** Paragraphs in order, consecutive matching ones grouped so they can fold. */
export function groupParagraphs(from: string, to: string): ParagraphGroup[] {
  const before = from.split("\n\n");
  const after = to.split("\n\n");
  if (before.length !== after.length) return [{ type: "diff", from, to }];
  const groups: ParagraphGroup[] = [];
  before.forEach((paragraph, index) => {
    const other = after[index] ?? "";
    const last = groups.at(-1);
    if (paragraph !== other) groups.push({ type: "diff", from: paragraph, to: other });
    else if (last?.type === "same") last.paragraphs.push(paragraph);
    else groups.push({ type: "same", paragraphs: [paragraph] });
  });
  return groups;
}

export function foldLabel(count: number): string {
  return `${count} identical ${count === 1 ? "paragraph" : "paragraphs"}`;
}
