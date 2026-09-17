/**
 * Word-level formatting of one `FieldChange`'s before/after (docs/deploy-changes.md
 * decision 4, spec's "Change highlighting" element).
 *
 * This is presentation over a decision the engine already made: a title only
 * reaches here because a `FieldChange(path="title", ...)` already says it
 * changed (A2 -- the page never decides *whether* something changed, only how
 * to show it). Word-level marking formats that one field's own before and
 * after and compares nothing else, exactly as the spec says.
 *
 * A longest-common-subsequence over whitespace-split words, the same
 * algorithm the design mock used -- diffing text is a solved, symmetric
 * problem, and multiplying it into `Comparison.tsx` (which merely renders the
 * tokens) would be the second copy the mock warns against with `path`-keyed
 * `Change` lookups elsewhere in this module set.
 */

export interface WordDiffToken {
  type: "same" | "ins" | "del";
  text: string;
}

export function wordDiff(before: string, after: string): WordDiffToken[] {
  const from = before.length ? before.split(" ") : [];
  const to = after.length ? after.split(" ") : [];
  const n = from.length;
  const m = to.length;

  // `cell(i, j)`: the length of the longest common subsequence of `from[i:]`
  // and `to[j:]`, cached by key rather than a nested array -- a `Map` needs
  // no indexed assignment, so every lookup here stays a plain function call
  // instead of a non-null assertion at each of the table's four corners.
  // Built lazily, outside-in from `(n, m)`, so `cell(0, 0)` -- read at the
  // start of the walk below -- recurses through exactly the cells the walk
  // itself will also visit.
  const table = new Map<string, number>();
  const word = (words: string[], i: number): string => words[i] ?? "";
  function cell(i: number, j: number): number {
    if (i >= n || j >= m) return 0;
    const key = `${i},${j}`;
    const cached = table.get(key);
    if (cached !== undefined) return cached;
    const value =
      word(from, i) === word(to, j)
        ? cell(i + 1, j + 1) + 1
        : Math.max(cell(i + 1, j), cell(i, j + 1));
    table.set(key, value);
    return value;
  }

  const tokens: WordDiffToken[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && word(from, i) === word(to, j)) {
      tokens.push({ type: "same", text: word(from, i) });
      i++;
      j++;
    } else if (i < n && (j === m || cell(i + 1, j) >= cell(i, j + 1))) {
      // Ties (an equal-length LCS either way) favour `del` before `ins`, so a
      // straight word substitution reads as "remove this, add that" -- the
      // order the spec's own sample markup shows and every ordinary diff
      // tool uses, rather than the mathematically arbitrary other order.
      tokens.push({ type: "del", text: word(from, i) });
      i++;
    } else {
      tokens.push({ type: "ins", text: word(to, j) });
      j++;
    }
  }
  return tokens;
}
