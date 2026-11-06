import { describe, expect, it } from "vitest";
import { labelRefusal, tidiedLabel } from "./labelRules";

// The server's words (core/config/template_labels.py): the field explains what
// a save would be refused for, so the two must read the same.
const CHARACTERS = "Letters, numbers, spaces, hyphens and colons only";
const LENGTH = "Labels can be up to 30 characters";
const COLON = "Use one colon with text on both sides, like theme:christmas";

describe("tidiedLabel", () => {
  it("lower-cases, trims and collapses repeated spaces", () => {
    expect(tidiedLabel("  Road   Trip ")).toBe("road trip");
  });
});

describe("labelRefusal", () => {
  it.each(["cosy", "shot:flat lay", "t-shirt 2", "a".repeat(30)])("accepts %s", (label) => {
    expect(labelRefusal(label)).toBeNull();
  });

  it.each([
    ["xmas!", CHARACTERS],
    ["café", CHARACTERS],
    ["a".repeat(31), LENGTH],
    ["a:b:c", COLON],
    [":christmas", COLON],
    ["theme:", COLON],
    ["theme: ", COLON],
  ])("refuses %s", (label, message) => {
    expect(labelRefusal(label)).toBe(message);
  });

  it("checks length before characters, as the server does", () => {
    expect(labelRefusal("!".repeat(31))).toBe(LENGTH);
  });
});
