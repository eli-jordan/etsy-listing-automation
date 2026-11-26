import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import * as batchesApi from "../../api/batches";
import { useListingBatch } from "./useListingBatch";

afterEach(() => vi.restoreAllMocks());

const MEMBER = { batch_id: "b1", reviewed: false } as unknown as batchesApi.ListingBatch;

it("asks again under the new name after a rename, which carries the batch row", async () => {
  const get = vi.spyOn(batchesApi, "getListingBatch").mockResolvedValue(MEMBER);
  const { rerender } = renderHook(({ name }) => useListingBatch(name), {
    initialProps: { name: "take-a-hike" },
  });
  await waitFor(() => expect(get).toHaveBeenCalledWith("take-a-hike"));

  rerender({ name: "trail-ready" });

  await waitFor(() => expect(get).toHaveBeenCalledWith("trail-ready"));
});

it("offers no batch when the batch cannot be loaded", async () => {
  vi.spyOn(batchesApi, "getListingBatch").mockRejectedValue(new Error("500"));
  const { result } = renderHook(() => useListingBatch("take-a-hike"));

  await waitFor(() => expect(batchesApi.getListingBatch).toHaveBeenCalled());
  expect(result.current[0]).toBeNull();
});
