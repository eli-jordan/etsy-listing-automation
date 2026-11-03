// Run on an etsy.com search results page via the Claude in Chrome javascript_tool.
//
// The tool keeps only about the first 1,000 characters of a result and withholds
// any that carry a query string, so the output is compact text, not JSON or a URL:
//
//   q=christmas tee|page=1|order=date_desc|filters=is_star_seller|count=59|part=1/1
//   4600718395aP 4603465966a 4461670463P 1758595872B ...
//
// Line 2 lists the main results grid in page order (recommendation carousels such
// as "Because you viewed" are left out). Each token is a listing ID followed by
// flags: a = ad, B = Bestseller, P = Popular now, S = Star Seller badge,
// E = Etsy's Pick. When the header says part=1/2, run again with PART = 2.
(() => {
  const PART = 1;
  const PER_PART = 70;
  const p = new URLSearchParams(location.search);
  const filters = ["is_star_seller", "is_best_seller"].filter((f) => p.get(f) === "true");
  const grid = document.querySelector("[data-search-results]");
  if (!grid) return "error: no search results grid on this page";
  const flags = [
    ["Bestseller", "B"],
    ["Popular now", "P"],
    ["Star Seller", "S"],
    ["Etsy's Pick", "E"],
  ];
  const tokens = [];
  const seen = new Set();
  for (const card of grid.querySelectorAll("[data-listing-id]")) {
    const id = card.getAttribute("data-listing-id");
    if (!id || seen.has(id) || !card.querySelector('a[href*="/listing/"]')) continue;
    seen.add(id);
    const text = card.innerText;
    const ad = /(^|\n)Ad[・ ]/.test(text) ? "a" : "";
    tokens.push(id + ad + flags.filter(([label]) => text.includes(label)).map(([, f]) => f).join(""));
  }
  const parts = Math.max(1, Math.ceil(tokens.length / PER_PART));
  const header = [
    `q=${p.get("q")}`,
    `page=${p.get("page") || 1}`,
    `order=${p.get("order") || "relevance"}`,
    `filters=${filters.join(",")}`,
    `count=${tokens.length}`,
    `part=${PART}/${parts}`,
  ].join("|");
  return header + "\n" + tokens.slice((PART - 1) * PER_PART, PART * PER_PART).join(" ");
})();
