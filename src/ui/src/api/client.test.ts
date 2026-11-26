import { describe, expect, it } from "vitest";
import { api, detailMessage, formBody, withTuples } from "./client";
import type { BoundingBox } from "../types";

describe("formBody", () => {
  it("reaches the server as multipart, with the browser's boundary", async () => {
    const form = new FormData();
    form.append("file", new File(["x"], "a.png", { type: "image/png" }));
    let sent: Request | undefined;

    await api.POST("/api/designs", {
      baseUrl: "http://ui.test",
      body: formBody(form),
      fetch: (request: Request) => {
        sent = request;
        return Promise.resolve(Response.json({ id: "a", name: "a" }));
      },
    });

    expect(sent?.headers.get("Content-Type")).toMatch(/^multipart\/form-data; boundary=/);
    const received = await sent?.formData();
    expect((received?.get("file") as File).name).toBe("a.png");
  });
});

describe("detailMessage", () => {
  it("answers the server's sentence, and the fallback for a validation list", () => {
    expect(detailMessage({ detail: "name taken" }, "failed")).toBe("name taken");
    expect(detailMessage({ detail: [{ msg: "bad" }] }, "failed")).toBe("failed");
    expect(detailMessage(undefined, "failed")).toBe("failed");
  });
});

describe("withTuples", () => {
  it("hands the response back as it came", () => {
    const corners = [
      { x: 0, y: 0 },
      { x: 1, y: 0 },
      { x: 1, y: 1 },
      { x: 0, y: 1 },
    ];
    expect(withTuples<BoundingBox>(corners)).toBe(corners);
  });
});
