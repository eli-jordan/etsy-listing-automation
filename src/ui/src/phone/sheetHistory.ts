/**
 * Back closes the phone's open sheet, the way it closes a native one, rather
 * than leaving the page under it. Used through `usePhoneModal`.
 *
 * Opening a sheet pushes one history entry: the same URL, with React
 * Router's own state copied so the router reads it as the page it is on,
 * plus a `phoneSheet` token. Back pops it; the listener below sees that
 * before React Router does (a capture listener on the window, registered
 * when this module loads, ahead of the router's), keeps the router from
 * hearing about it, and closes the sheet. The page never navigates.
 *
 * A sheet closed any other way (Done, a swipe, an action) drops its entry
 * with `history.back()`, again unheard by the router. It waits a tick first,
 * because an action may navigate as it closes: React Router pushes the new
 * page a microtask later, and going back then would undo the navigation.
 * When something else is on top by then, the entry stays where it is, an
 * orphan: Back from the new page lands on it and the router shows the old
 * page, and the next Back skips the duplicate of that page beneath it.
 */

/** Tells this page load's tokens from those of an earlier load, which a
 * reload leaves in history. */
const SESSION = Date.now().toString(36);
let counter = 0;

interface OpenSheet {
  token: string;
  /** The history state under this sheet's entry. */
  base: unknown;
  close: () => void;
}

const open: OpenSheet[] = [];
/** The entry a `history.back()` of ours is going to land on. */
let expecting: { state: unknown } | null = null;
/** The entry the last traversal landed on. */
let landed: unknown = typeof window === "undefined" ? null : window.history.state;

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
  const from = landed;
  landed = state;
  if (expecting !== null) {
    const { state: wanted } = expecting;
    expecting = null;
    if (sameEntry(state, wanted)) {
      event.stopImmediatePropagation();
      return;
    }
  }
  const top = open[open.length - 1];
  if (top !== undefined && tokenOf(state) !== top.token) {
    // Left the top sheet's entry: back onto its page, which the router is
    // already showing, or further, which the router handles as usual.
    if (sameEntry(state, top.base)) event.stopImmediatePropagation();
    top.close();
    return;
  }
  // Back from an orphaned entry onto the page it duplicates: skip it, so
  // that one Back still goes one page back.
  const orphan = tokenOf(from);
  if (
    orphan !== undefined &&
    !isOpen(orphan) &&
    tokenOf(state) === undefined &&
    field(state, "key") === field(from, "key")
  ) {
    event.stopImmediatePropagation();
    window.history.back();
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", onPopState, true);
}

/** Gives an opening sheet its history entry; the returned function drops
 * it again when the sheet closes by any means. `close` is what Back calls. */
export function pushSheetEntry(close: () => void): () => void {
  counter += 1;
  const token = `${SESSION}-${counter}`;
  const base: unknown = window.history.state;
  const state = typeof base === "object" && base !== null ? { ...base } : {};
  window.history.pushState({ ...state, phoneSheet: token }, "", window.location.href);
  landed = window.history.state;
  const sheet: OpenSheet = { token, base, close };
  open.push(sheet);

  return () => {
    const at = open.indexOf(sheet);
    if (at >= 0) open.splice(at, 1);
    window.setTimeout(() => {
      if (tokenOf(window.history.state) !== token) return;
      expecting = { state: base };
      window.history.back();
    }, 0);
  };
}
