/**
 * Back closes the phone's open sheet (docs/architecture.md, *Phone sheets and Back*).
 *
 * The popstate listener must run before React Router's: it is a capture listener
 * registered when this module loads, ahead of the router's.
 */

const PAGE_LOAD_ID = Date.now().toString(36);
let counter = 0;

interface OpenSheet {
  token: string;
  stateBeneath: unknown;
  close: () => void;
}

const open: OpenSheet[] = [];
let ownBackLandsOn: { state: unknown } | null = null;
let currentEntry: unknown = typeof window === "undefined" ? null : window.history.state;

function field(state: unknown, name: string): unknown {
  return typeof state === "object" && state !== null
    ? (state as Record<string, unknown>)[name]
    : undefined;
}

const tokenOf = (state: unknown) => field(state, "phoneSheet");

function sameEntry(a: unknown, b: unknown): boolean {
  return field(a, "key") === field(b, "key") && tokenOf(a) === tokenOf(b);
}

function isOpen(token: unknown): boolean {
  return open.some((sheet) => sheet.token === token);
}

function onPopState(event: PopStateEvent) {
  const state: unknown = event.state;
  const from = currentEntry;
  currentEntry = state;
  if (ownBackLandsOn !== null) {
    const { state: wanted } = ownBackLandsOn;
    ownBackLandsOn = null;
    if (sameEntry(state, wanted)) {
      event.stopImmediatePropagation();
      return;
    }
  }
  const top = open[open.length - 1];
  if (top !== undefined && tokenOf(state) !== top.token) {
    const ontoThePageTheRouterShows = sameEntry(state, top.stateBeneath);
    if (ontoThePageTheRouterShows) event.stopImmediatePropagation();
    top.close();
    return;
  }
  if (isBackFromOrphanOntoItsDuplicate(from, state)) {
    event.stopImmediatePropagation();
    window.history.back();
  }
}

function isBackFromOrphanOntoItsDuplicate(from: unknown, to: unknown): boolean {
  const orphan = tokenOf(from);
  return (
    orphan !== undefined &&
    !isOpen(orphan) &&
    tokenOf(to) === undefined &&
    field(to, "key") === field(from, "key")
  );
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", onPopState, true);
}

/** Back calls `close`; call the returned function when the sheet closes by any means. */
export function pushSheetEntry(close: () => void): () => void {
  counter += 1;
  const token = `${PAGE_LOAD_ID}-${counter}`;
  const base: unknown = window.history.state;
  const state = typeof base === "object" && base !== null ? { ...base } : {};
  window.history.pushState({ ...state, phoneSheet: token }, "", window.location.href);
  currentEntry = window.history.state;
  const sheet: OpenSheet = { token, stateBeneath: base, close };
  open.push(sheet);

  return () => {
    const at = open.indexOf(sheet);
    if (at >= 0) open.splice(at, 1);
    // A tick later: an action closing the sheet may navigate, and the router pushes a microtask later.
    window.setTimeout(() => {
      if (tokenOf(window.history.state) !== token) return;
      ownBackLandsOn = { state: base };
      window.history.back();
    }, 0);
  };
}
