import { describe, expect, it, vi, afterEach } from "vitest";

describe("CustomRuntimeProvider", () => {
  afterEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("builds models and runtime metadata from an OpenAI-compatible endpoint", async () => {
    const fetchJson = vi.fn(async (_runtimeUrl: string, pathname: string) => {
      if (pathname === "/v1/models") {
        return {
          data: [{ id: "qwen/qwen2.5-coder-14b-instruct" }],
        };
      }
      throw new Error(`missing ${pathname}`);
    });

    vi.doMock("@/lib/runtime/custom/http", () => ({
      normalizeCustomBaseUrl: (value: string) => value,
      requestCustomRuntime: vi.fn(),
      fetchCustomRuntimeJson: fetchJson,
    }));

    const { CustomRuntimeProvider } = await import("@/lib/runtime/custom/provider");
    const provider = new CustomRuntimeProvider({} as never, "http://127.0.0.1:1234/v1");

    await expect(provider.fetchHealth()).resolves.toMatchObject({ ok: true, status: "ok" });
    await expect(provider.fetchState()).resolves.toMatchObject({
      runtime: {
        name: "OpenAI-Compatible Runtime",
        active_model: "qwen/qwen2.5-coder-14b-instruct",
      },
    });
    await expect(provider.call("models.list", {})).resolves.toEqual({
      models: [
        {
          id: "qwen/qwen2.5-coder-14b-instruct",
          name: "qwen/qwen2.5-coder-14b-instruct",
          provider: "custom",
        },
      ],
    });
  });
});