# ADR-0046: Use workspace and owner roots for path references

Unprefixed listing file references resolve from the workspace root; `./` resolves from the listing's own directory. Permit subdirectories but refuse `..`. This replaces fragile `../../` references whose meaning changed when a listing moved. The migration rewrites design, price-plan and media references once; shared media can upload again because its ref keys stored Etsy ids, while byte-keyed render and Printify uploads remain unchanged. Listing templates use their own owner directory for `./`.

First recorded 2026-09-26 in [commit 4fa8983](https://github.com/eli-jordan/etsy-listing-automation/commit/4fa8983e5ea489f8b102177f4073ae138ab39492).
