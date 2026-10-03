// marver config - OPTIONAL. Delete this file and everything still works on defaults.
// Theme lives in design/theme.css (it imports your app's real stylesheet) - not here.
// Sharp edges (native Node TS import): erasable syntax only (no enums/namespaces),
// relative imports need extensions, tsconfig paths are ignored here.
export default {
  mode: "studio",
  // One sentence on what this product is and for whom. It lands in design/manifest.json
  // as the project's description - the first thing a new agent session reads.
  description:
    "A calm control room for print-on-demand sellers to turn a t-shirt design into a reviewable Etsy listing.",
  // Device widths for frames and the Devices view. Rename, retune, or uncomment tv.
  viewports: {
    mobile: { width: 390, height: 844 },
    tablet: { width: 768, height: 1024 },
    laptop: { width: 1280, height: 800 },
    monitor: { width: 1920, height: 1080 },
    // tv: { width: 3840, height: 2160 },
  },
  themes: ["light", "dark"],
  port: 5199,
  // Canvas zoom feel: 1 = default, 1.2 = 20% faster, 0.8 = 20% slower.
  // zoomSpeed: 1,
  // Live Jam - tag @marver in a canvas comment and this agent picks the job up, edits the
  // real frame, and replies in the thread. Detected at init; change the agent if it named
  // the wrong tool, raise concurrency for more frames at once, `jam: false` to turn it off.
  jam: { agent: "codex", concurrency: 6 },
  // Publishing (`marver build` + `marver serve`): gate identity + branding footer.
  // name/logo default to the host package.json name and design/logo.svg (then public/).
  // branding is the small "Powered by Marver.design" line under the gate. Marver is
  // free, and that line is how it spreads - we'd love it if you leave it on, but it
  // is yours to remove, no strings: share: { branding: false }.
  // share: { name: "My App", logo: "design/logo.svg", branding: true },
};
