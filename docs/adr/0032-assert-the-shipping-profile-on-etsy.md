# ADR-0032: Assert the shipping profile on Etsy

Read the actual Etsy shipping profile and converge it to the configured profile. Printify's `shipping_template: false` is a hint: first publish was measured attaching a US-origin profile with USD rates interpreted as NOK numerals. Treating that attachment as ordinary drift lets plan report and apply correct it, without an always-rewrite exception or trusting a flag that is not reliably honoured.

First recorded 2026-09-10 in [commit de9728e](https://github.com/eli-jordan/etsy-listing-automation/commit/de9728e46c88a8da0f59674f1c20831867f75ec9).
