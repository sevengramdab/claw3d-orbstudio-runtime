import { afterEach, describe, expect, it, vi } from "vitest";

describe("probeCustomRuntime", () => {
  afterEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("accepts a runtime that responds to /health", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

    const { probeCustomRuntime } = await import("@/lib/runtime/custom/http");

    await expect(probeCustomRuntime("http://127.0.0.1:7770")).resolves.toBeUndefined();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("falls back to /v1/models for OpenAI-compatible runtimes", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("not found", { status: 404 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: [{ id: "qwen/qwen2.5-coder-14b-instruct" }],
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        )
      );

    const { probeCustomRuntime } = await import("@/lib/runtime/custom/http");

    await expect(probeCustomRuntime("http://127.0.0.1:1234/v1")).resolves.toBeUndefined();
  });

  it("strips a trailing /v1 from OpenAI-compatible base URLs", async () => {
    const { normalizeCustomBaseUrl } = await import("@/lib/runtime/custom/http");

    expect(normalizeCustomBaseUrl("http://127.0.0.1:1234/v1")).toBe("http://127.0.0.1:1234");
    expect(normalizeCustomBaseUrl("http://127.0.0.1:1234/v1/")).toBe("http://127.0.0.1:1234");
    expect(normalizeCustomBaseUrl("http://127.0.0.1:1234/api")).toBe("http://127.0.0.1:1234");
    expect(normalizeCustomBaseUrl("http://127.0.0.1:1234/api/v1")).toBe("http://127.0.0.1:1234");
    expect(normalizeCustomBaseUrl("http://127.0.0.1:1234/api/v1/")).toBe("http://127.0.0.1:1234");
  });
});