# ADR-0019: Send channel-currency minor units to Printify

Printify variant prices are integer minor units of the connected sales channel's currency. The web application's fixed USD badge does not determine how Etsy interprets the number, and Printify does not convert it on publish. Preserve the configured retail currency when serialising the price; the earlier USD-cent interpretation attached a currency inferred from the UI to otherwise correctly measured integers.

First recorded 2026-09-08 in [commit 869ab0e](https://github.com/eli-jordan/etsy-listing-automation/commit/869ab0e0e58dd438062de601b1ffd0fcde718ad0).
