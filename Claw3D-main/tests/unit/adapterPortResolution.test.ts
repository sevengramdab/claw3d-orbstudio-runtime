import { describe, expect, it } from "vitest";

const { resolveManagedAdapterPort } = require("../../server/adapter-port");

describe("resolveManagedAdapterPort", () => {
  it("uses HERMES_ADAPTER_PORT when provided", () => {
    expect(resolveManagedAdapterPort("hermes", { HERMES_ADAPTER_PORT: "19444" })).toBe(19444);
  });

  it("uses DEMO_ADAPTER_PORT when provided", () => {
    expect(resolveManagedAdapterPort("demo", { DEMO_ADAPTER_PORT: "19990" })).toBe(19990);
  });

  it("falls back to default ports when env vars are missing", () => {
    expect(resolveManagedAdapterPort("hermes", {})).toBe(18789);
    expect(resolveManagedAdapterPort("demo", {})).toBe(18890);
  });
});