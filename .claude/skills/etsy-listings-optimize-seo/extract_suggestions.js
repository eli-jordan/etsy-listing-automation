// Template for `seo_review.py suggest`, which fills in TERMS and writes RUN/suggest_batch.js.
// Run on any etsy.com page. It returns at once and keeps working in the tab, one term every
// 7 to 11 seconds, sending no cookies, so results aren't personalised or tied to the shop.
// It stops at the first refused or unreadable response and records why in window.__ac.stopped.
// Each row is term|1 or 0 for whether the term suggests itself|suggestion count|a;b;c
var TERMS = "__TERMS__";
var state = (window.__ac = { rows: [], total: TERMS.length, stopped: '', finished: false });
var pause = () => new Promise((r) => setTimeout(r, 7000 + Math.random() * 4000));
(async () => {
  for (var term of TERMS) {
    var query = new URLSearchParams({ search_query: term, search_type: 'all' });
    var response = await fetch('/suggestions_ajax.php?' + query, {
      credentials: 'omit',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
    var body = await response.json().catch(() => null);
    if (!response.ok || !body) {
      state.stopped = 'status ' + response.status + ' at ' + term;
      return;
    }
    var found = body.results.map((x) => x.query).filter((q) => !/<span/.test(q));
    var hit = found.some((q) => q.toLowerCase() === term.toLowerCase()) ? 1 : 0;
    state.rows.push([term, hit, found.length, found.join(';')].join('|'));
    await pause();
  }
  state.finished = true;
})().catch((error) => {
  state.stopped = String(error);
});
'started ' + TERMS.length;
