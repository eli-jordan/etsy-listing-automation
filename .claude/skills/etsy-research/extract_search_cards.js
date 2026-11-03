// Run on an etsy.com search results page via the Claude in Chrome javascript_tool.
// Returns JSON: one row per listing in the main results grid (recommendation
// carousels such as "Because you viewed" are excluded), in page order.
(() => {
  const grid = document.querySelector("[data-search-results]");
  if (!grid) return JSON.stringify({ error: "no search results grid on this page", url: location.href });
  const badges = ["Bestseller", "Popular now", "Star Seller", "Etsy's Pick"];
  const rows = [];
  const seen = new Set();
  for (const card of grid.querySelectorAll("[data-listing-id]")) {
    const id = card.getAttribute("data-listing-id");
    if (!id || seen.has(id) || !card.querySelector('a[href*="/listing/"]')) continue;
    seen.add(id);
    const text = card.innerText;
    rows.push({
      listing_id: Number(id),
      shop_id: Number(card.getAttribute("data-shop-id")) || null,
      position: rows.length + 1,
      ad: /(^|\n)Ad[・ ]/.test(text),
      badges: badges.filter((b) => text.includes(b)),
    });
  }
  return JSON.stringify({ url: location.href, count: rows.length, rows });
})();
