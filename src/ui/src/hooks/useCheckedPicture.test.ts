import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { listingScenePreviewUrl, scenePreviewChanged } from "../api/listings";
import { useCheckedPicture } from "./useCheckedPicture";

/** A scene the server found under remembered pixel digests is checked behind
 * the picture: shown at once, and asked for again only if it was stale. */

function answer(changed: boolean) {
  return {
    data: { changed },
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as never;
}

const SCENE = listingScenePreviewUrl("take-a-hike", "flat-lay-01", "black", "v1");

afterEach(() => vi.restoreAllMocks());

describe("scenePreviewChanged", () => {
  it("asks the check endpoint for the scene the URL names", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue(answer(true));

    await expect(scenePreviewChanged(SCENE)).resolves.toBe(true);
    expect(get).toHaveBeenCalledWith("/api/listings/{name}/scene-preview/check", {
      params: {
        path: { name: "take-a-hike" },
        query: { template: "flat-lay-01", colour: "black" },
      },
    });
  });

  it("leaves out the colour of a scene that has none", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue(answer(false));

    await scenePreviewChanged(listingScenePreviewUrl("take-a-hike", "chart", null, "v1"));

    expect(get).toHaveBeenCalledWith("/api/listings/{name}/scene-preview/check", {
      params: { path: { name: "take-a-hike" }, query: { template: "chart" } },
    });
  });

  it("reads a check that fails as unchanged", async () => {
    vi.spyOn(api, "GET").mockResolvedValue({
      data: undefined,
      error: { detail: "boom" },
      response: new Response(null, { status: 500 }),
    } as never);

    await expect(scenePreviewChanged(SCENE)).resolves.toBe(false);
  });

  it("asks nothing about a picture that is not a listing scene", async () => {
    const get = vi.spyOn(api, "GET");

    await expect(scenePreviewChanged("/api/common-media/sizing.png")).resolves.toBe(false);
    expect(get).not.toHaveBeenCalled();
  });
});

describe("useCheckedPicture", () => {
  it("keeps the picture when the check finds it unchanged", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue(answer(false));

    const { result } = renderHook(() => useCheckedPicture(SCENE));

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(result.current).toBe(SCENE);
  });

  it("asks for the picture again when the check finds it stale", async () => {
    vi.spyOn(api, "GET").mockResolvedValue(answer(true));

    const { result } = renderHook(() => useCheckedPicture(SCENE));

    await waitFor(() => expect(result.current).not.toBe(SCENE));
    expect(result.current.startsWith(SCENE)).toBe(true);
  });
});
