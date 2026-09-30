import { describe, expect, it } from "vitest";
import { dayMonth } from "./dates";

describe("dayMonth", () => {
  it("abbreviates every month to three letters, September included", () => {
    const months = Array.from({ length: 12 }, (_, month) => dayMonth(new Date(2026, month, 3)));

    expect(months).toEqual([
      "3 Jan",
      "3 Feb",
      "3 Mar",
      "3 Apr",
      "3 May",
      "3 Jun",
      "3 Jul",
      "3 Aug",
      "3 Sep",
      "3 Oct",
      "3 Nov",
      "3 Dec",
    ]);
  });
});
