import { describe, expect, it } from "vitest";

import { resolveGatewayBackedFallbackProfile } from "../../src/lib/gateway/GatewayClient";

describe("resolveGatewayBackedFallbackProfile", () => {
  it("prefers a saved demo profile before other gateway-backed adapters", () => {
    const result = resolveGatewayBackedFallbackProfile(
      {
        custom: { url: "http://localhost:1234", token: "" },
        demo: { url: "ws://localhost:19500", token: "" },
        openclaw: { url: "ws://localhost:18789", token: "tok" },
      },
      null
    );

    expect(result).toEqual({
      adapterType: "demo",
      url: "ws://localhost:19500",
      token: "",
    });
  });

  it("falls back to openclaw defaults when no saved gateway-backed profile exists", () => {
    const result = resolveGatewayBackedFallbackProfile(
      {
        custom: { url: "http://localhost:1234", token: "" },
      },
      {
        url: "ws://localhost:18789",
        token: "tok",
        adapterType: "openclaw",
        profiles: {
          openclaw: { url: "ws://localhost:18789", token: "tok" },
        },
      }
    );

    expect(result).toEqual({
      adapterType: "openclaw",
      url: "ws://localhost:18789",
      token: "tok",
    });
  });

  it("does not leak a custom runtime URL into the openclaw fallback", () => {
    const result = resolveGatewayBackedFallbackProfile(
      {
        custom: { url: "http://localhost:1234", token: "" },
      },
      {
        url: "http://localhost:1234",
        token: "",
        adapterType: "custom",
        profiles: {
          custom: { url: "http://localhost:1234", token: "" },
        },
      }
    );

    expect(result).toEqual({
      adapterType: "openclaw",
      url: "ws://localhost:18789",
      token: "",
    });
  });
});