# ADR-0051: Bound uploads and inspect archive entries

Status: accepted.

Stream uploads to disk with byte counts and read ZIP entries individually instead of extracting blindly. Refuse escaping names, symlinks, encryption, duplicates and invalid PNG content; bound compressed and expanded bytes, entry count and compression ratio. These are resource and path-safety boundaries before listing creation, not extension-based hints. A refused staging operation leaves no files behind; the 25-design limit counts unique content hashes, so duplicate content does not consume extra rows.

First recorded 2026-09-27 in [commit c963e78](https://github.com/eli-jordan/etsy-listing-automation/commit/c963e78aa65ea254ac02886421a1b1607cce8845).
