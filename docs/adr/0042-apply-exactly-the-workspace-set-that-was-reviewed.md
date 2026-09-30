# ADR-0042: Apply exactly the workspace set that was reviewed

Resolve and record the ordered workspace listing names when accepting WorkspacePlan. WorkspaceApply carries those exact names, their fingerprints and the reviewed run id; it does not rediscover all listings at apply time. Reuse the existing run resource and frontend event projection for individual and workspace deploys, with workspace runs conflicting with all listing runs. This avoids an empty-list sentinel, duplicate batch execution machinery and applying listings that were never reviewed.

First recorded 2026-09-21 in [commit 8c066ab](https://github.com/eli-jordan/etsy-listing-automation/commit/8c066ab6c2ceadc5ccd84d08bdb9758a110bf5ce).
