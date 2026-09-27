### Recent batches: one status per batch

Derived from the batch, never set by hand. The title opens it: a **Staging** row reopens staging, every other row opens the batch summary.

| Status | Means |
|---|---|
| Staging | Uploaded, not confirmed. Nothing created yet |
| Drafting | Listings exist, AI queue still working |
| In review | Drafting done, not every listing marked reviewed |
| Complete | Every created listing marked reviewed |
| Stopped | Cancel batch left work undrafted; Resume on the summary |

Failures don't get a status. They show as a red count beside the progress, so a batch with one failed row still reads as "In review".

*Complete* needs only every listing marked reviewed; deploying is separate.
