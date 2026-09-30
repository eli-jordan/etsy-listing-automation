# ADR-0031: Sync media by hashes and an ordered image-id manifest

Status: accepted.

Upload only images whose content hash changed, overwrite an occupied rank when possible, then patch one comma-separated `image_ids` value to order our images and detach the rest. This preserves full-replacement gallery semantics without re-uploading unchanged files merely to reorder them. The earlier upload-everything mechanism was superseded after measurement; repeated form keys are specifically wrong because Etsy accepts them but keeps only one image.

First recorded 2026-09-10 in [commit de9728e](https://github.com/eli-jordan/etsy-listing-automation/commit/de9728e46c88a8da0f59674f1c20831867f75ec9).
