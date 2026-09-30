import { useEffect, useState } from "react";
import { getListingBatch, type ListingBatch } from "../../api/batches";

/** The listing's batch, if one made it: what Back to batch and Mark
 * reviewed need (`GET /api/listings/{name}/batch`). Asked again when the
 * name changes, since a rename carries the batch row with it (A42). */
export function useListingBatch(listing: string) {
  const [member, setMember] = useState<ListingBatch | null>(null);
  useEffect(() => {
    if (listing === "") return;
    let current = true;
    getListingBatch(listing)
      .then((found) => current && setMember(found))
      // The batch is extra: an editor whose batch will not load is still an
      // editor, so this says nothing and offers nothing.
      .catch(() => current && setMember(null));
    return () => {
      current = false;
    };
  }, [listing]);
  return [member, setMember] as const;
}
