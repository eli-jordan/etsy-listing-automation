// Run on an eRank Listing Audit page. Prints a header, then tag|last month|searches|clicks|ctr|competition.
// An empty result means the page is still loading: wait and run it again.
var rows = [...document.querySelectorAll('table tbody tr')]
  .filter((r) => r.cells.length > 4)
  .map((r) => [...r.cells].map((c) => c.innerText.replace(/\s+/g, ' ').trim()));
var month = rows.length ? (rows[0][1].match(/^[A-Z][a-z]{2} \d{4}/) || [''])[0] : '';
var quota = (document.body.innerText.match(/Quota \d+\/50/) || [''])[0];
'# ' + location.pathname.split('/').pop() + ' | ' + quota + ' | ' + month + '\n' +
  rows.map((c) => [c[0], c[1].replace(month, '').trim(), c[2], c[3], c[4], c[5]].join('|')).join('\n');
