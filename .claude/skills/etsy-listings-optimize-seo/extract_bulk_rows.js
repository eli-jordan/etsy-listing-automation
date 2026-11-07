// Run on eRank's Bulk Keyword Tool after Analyze. Prints rows in the audits.txt format:
// a header with the month, then term|last month|searches|clicks|ctr|competition.
var seen = new Set();
var month = '';
var rows = [...document.querySelectorAll('table tbody tr')]
  .map((r) => [...r.cells].map((c) => c.innerText.replace(/\s+/g, ' ').trim()))
  .filter((c) => c.length > 7 && c[2] && !seen.has(c[2]) && seen.add(c[2]))
  .map((c) => {
    var trend = c[3].match(/^([A-Z][a-z]{2} \d{4}) ?(.*)$/) || ['', '', c[3]];
    month = trend[1] || month;
    return [c[2], trend[2], c[4], c[5], c[6], c[7]].join('|');
  });
'# bulk | ' + ((document.body.innerText.match(/\d+\/100/) || [''])[0]) + ' | ' + month + '\n' + rows.join('\n');
