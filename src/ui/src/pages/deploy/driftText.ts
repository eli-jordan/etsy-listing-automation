import { sequenceDiff, wordDiff, type WordDiffToken } from "./wordDiff";

/**
 * Pure text comparison for a drifted field: which characters differ and which
 * paragraphs can fold away. Presentation only, as in `wordDiff.ts`: the engine
 * already decided the field drifted.
 */

export interface DiffSegment {
  kind: "same" | "del" | "ins";
  text: string;
}

export type DiffSide = "live" | "after";

function sharedEnds(a: string, b: string): { start: number; end: number } {
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  const limit = Math.min(a.length, b.length) - start;
  let end = 0;
  while (end < limit && a[a.length - 1 - end] === b[b.length - 1 - end]) end++;
  return { start, end };
}

/** One word swapped for another, marked only where the two differ, so a
 * single changed character is findable in a long description. */
function narrowed(del: string, ins: string): DiffSegment[] {
  const { start, end } = sharedEnds(del, ins);
  const parts: DiffSegment[] = [
    { kind: "same", text: del.slice(0, start) },
    { kind: "del", text: del.slice(start, del.length - end) },
    { kind: "ins", text: ins.slice(start, ins.length - end) },
    { kind: "same", text: `${del.slice(del.length - end)} ` },
  ];
  return parts.filter((part) => part.text.length > 0);
}

function isLoneSwap(tokens: WordDiffToken[], index: number): boolean {
  return (
    tokens[index]?.type === "del" &&
    tokens[index + 1]?.type === "ins" &&
    tokens[index - 1]?.type !== "del" &&
    tokens[index + 2]?.type !== "ins"
  );
}

function allSegments(live: string, after: string): DiffSegment[] {
  const tokens = wordDiff(live, after);
  const segments: DiffSegment[] = [];
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    const next = tokens[index + 1];
    if (token === undefined) continue;
    if (next !== undefined && isLoneSwap(tokens, index)) {
      segments.push(...narrowed(token.text, next.text));
      index++;
    } else {
      segments.push({ kind: token.type, text: `${token.text} ` });
    }
  }
  return segments;
}

/** One side of the comparison: unchanged text, plus what only that side has. */
export function diffSegments(live: string, after: string, side: DiffSide): DiffSegment[] {
  const own = side === "live" ? "del" : "ins";
  return allSegments(live, after).filter(({ kind }) => kind === "same" || kind === own);
}

export type ParagraphGroup =
  { type: "same"; paragraphs: string[] } | { type: "diff"; live: string; after: string };

type DraftDiff = { type: "diff"; live: string[]; after: string[] };
type DraftGroup = Extract<ParagraphGroup, { type: "same" }> | DraftDiff;

function addToken(groups: DraftGroup[], token: WordDiffToken): void {
  const last = groups[groups.length - 1];
  if (token.type === "same") {
    if (last?.type === "same") last.paragraphs.push(token.text);
    else groups.push({ type: "same", paragraphs: [token.text] });
    return;
  }
  const diff = last?.type === "diff" ? last : { type: "diff" as const, live: [], after: [] };
  if (diff !== last) groups.push(diff);
  (token.type === "del" ? diff.live : diff.after).push(token.text);
}

/** Paragraphs in order: matching runs that can fold, and the changed ones. An
 * added or removed paragraph leaves everything around it matched. */
export function paragraphGroups(live: string, after: string): ParagraphGroup[] {
  const groups: DraftGroup[] = [];
  for (const token of sequenceDiff(live.split("\n\n"), after.split("\n\n"))) {
    addToken(groups, token);
  }
  return groups.map((group) =>
    group.type === "same"
      ? group
      : { type: "diff", live: group.live.join("\n\n"), after: group.after.join("\n\n") },
  );
}

const withoutSpace = (text: string) => text.replace(/\s+/g, "");

/** The comparison's one-sentence answer to "what really differs?". */
export function driftVerdict(
  live: string,
  after: string,
  where: "on Etsy" | "in Printify",
): string {
  if (live === after) return "This plan already matches this text.";
  if (withoutSpace(live) === withoutSpace(after)) return "Only spacing or line breaks differ.";
  return `The wording was edited ${where}.`;
}
