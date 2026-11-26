import { describe, expect, it } from "vitest";
import { bytes, bytesProgress, when } from "./backupText";

describe("when", () => {
  it("names the weekday, day, month and time", () => {
    expect(when("2026-11-23T09:12:00")).toBe("Mon 23 Nov, 09:12");
  });
});

describe("bytes", () => {
  it("keeps a tenth below 100 of a unit, then rounds", () => {
    expect(bytes(16_800_000)).toBe("16.8 MB");
    expect(bytes(41_000_000)).toBe("41 MB");
    expect(bytes(312_400_000)).toBe("312 MB");
    expect(bytes(null)).toBe("—");
  });
});

describe("bytesProgress", () => {
  it("names a shared unit once", () => {
    expect(bytesProgress(7_600_000_000, 20_100_000_000)).toBe("7.6 of 20.1 GB");
    expect(bytesProgress(312_000_000, 20_100_000_000)).toBe("312 MB of 20.1 GB");
  });
});
