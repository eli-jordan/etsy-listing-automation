// Run on an Etsy listing page. Scrolls so the lazy sections load, then prints a header and the
// listing's related search terms, one per line. New listings have none yet.
for (var step = 1; step <= 6; step++) {
  window.scrollTo(0, (document.body.scrollHeight * step) / 6);
  await new Promise((r) => setTimeout(r, 800));
}
var links = [...document.querySelectorAll('a[href*="/market/"]')];
var terms = [...new Set(links.map((a) => decodeURIComponent(new URL(a.href).pathname.split('/market/')[1]).replace(/_/g, ' ')))];
'# ' + location.pathname.split('/listing/')[1].split('/')[0] + '\n' + terms.join('\n');
