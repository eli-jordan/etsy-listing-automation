export interface WordDiffToken {
  type: "same" | "ins" | "del";
  text: string;
}

export function wordDiff(before: string, after: string): WordDiffToken[] {
  return sequenceDiff(before.length ? before.split(" ") : [], after.length ? after.split(" ") : []);
}

const word = (words: string[], i: number): string => words[i] ?? "";

/** `cell(i, j)`: the longest common subsequence of `from[i:]` and `to[j:]`. */
function lcsTable(from: string[], to: string[]): (i: number, j: number) => number {
  const width = to.length + 1;
  const lcs = new Int32Array((from.length + 1) * width);
  const cell = (i: number, j: number): number => lcs[i * width + j] ?? 0;
  for (let i = from.length - 1; i >= 0; i--) {
    for (let j = to.length - 1; j >= 0; j--) {
      lcs[i * width + j] =
        word(from, i) === word(to, j)
          ? cell(i + 1, j + 1) + 1
          : Math.max(cell(i + 1, j), cell(i, j + 1));
    }
  }
  return cell;
}

export function sequenceDiff(from: string[], to: string[]): WordDiffToken[] {
  const n = from.length;
  const m = to.length;
  const cell = lcsTable(from, to);

  const tokens: WordDiffToken[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && word(from, i) === word(to, j)) {
      tokens.push({ type: "same", text: word(from, i) });
      i++;
      j++;
    } else if (i < n && (j === m || cell(i + 1, j) >= cell(i, j + 1))) {
      // Ties favour `del` before `ins`: a substitution reads "remove this, add that".
      tokens.push({ type: "del", text: word(from, i) });
      i++;
    } else {
      tokens.push({ type: "ins", text: word(to, j) });
      j++;
    }
  }
  return tokens;
}
