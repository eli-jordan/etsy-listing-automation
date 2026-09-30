import { afterEach, describe, expect, it } from "vitest";
import { purgeLegacyProposals } from "./legacyProposals";

afterEach(() => localStorage.clear());

describe("purgeLegacyProposals", () => {
  it("drops every browser-local proposal and received marker, and nothing else", () => {
    localStorage.setItem("ai-seo-proposal:workspace-1:take-a-hike", "{}");
    localStorage.setItem("ai-seo-proposal:workspace-2:other", "{}");
    localStorage.setItem("ai-seo-received:workspace-1:take-a-hike", "2026-09-23T00:00:00Z");
    localStorage.setItem("deploy-view:take-a-hike", "kept");

    purgeLegacyProposals(localStorage);

    expect(Object.keys(localStorage)).toEqual(["deploy-view:take-a-hike"]);
  });

  it("is harmless with nothing to purge", () => {
    purgeLegacyProposals(localStorage);

    expect(localStorage.length).toBe(0);
  });
});
