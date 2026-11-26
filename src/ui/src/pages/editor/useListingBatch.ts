import { useEffect, useState } from "react";
import { getListingBatch, type ListingBatch } from "../../api/batches";

export function useListingBatch(listing: string) {
  const [member, setMember] = useState<ListingBatch | null>(null);
  useEffect(() => {
    if (listing === "") return;
    let current = true;
    getListingBatch(listing)
      .then((found) => current && setMember(found))
      .catch(() => current && setMember(null));
    return () => {
      current = false;
    };
  }, [listing]);
  return [member, setMember] as const;
}
