# ADR-0006: Require an explicit currency on every price

Status: accepted.

Every price is a `Money` value with an explicit currency, such as `349 NOK`; bare numbers and currencies that disagree with their field are rejected. Retail revenue and production cost can be in different currencies, so treating a number as an amount without its currency can silently set the wrong selling price.

First recorded 2026-09-03 in [commit 086df20](https://github.com/eli-jordan/etsy-listing-automation/commit/086df2096d7b293ccbad394c9891b661a9a194b9).
