import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

const makeTempDir = (name: string) => fs.mkdtempSync(path.join(os.tmpdir(), `${name}-`));

describe("server studio upstream gateway settings", () => {
  const priorStateDir = process.env.OPENCLAW_STATE_DIR;
  let tempDir: string | null = null;

  afterEach(() => {
    process.env.OPENCLAW_STATE_DIR = priorStateDir;
    delete process.env.CLAW3D_GATEWAY_URL;
    delete process.env.CLAW3D_GATEWAY_TOKEN;
    delete process.env.CLAW3D_GATEWAY_ADAPTER_TYPE;
    delete process.env.HERMES_ADAPTER_PORT;
    delete process.env.DEMO_ADAPTER_PORT;
    vi.resetModules();
    if (tempDir) {
      fs.rmSync(tempDir, { recursive: true, force: true });
      tempDir = null;
    }
  });

  it("falls back to openclaw.json token/port when studio settings are missing", async () => {
    tempDir = makeTempDir("studio-upstream-openclaw-defaults");
    process.env.OPENCLAW_STATE_DIR = tempDir;

    fs.writeFileSync(
      path.join(tempDir, "openclaw.json"),
      JSON.stringify({ gateway: { port: 18790, auth: { token: "tok" } } }, null, 2),
      "utf8"
    );

    const { loadUpstreamGatewaySettings } = await import("../../server/studio-settings");
    const settings = loadUpstreamGatewaySettings(process.env);
    expect(settings.url).toBe("ws://localhost:18790");
    expect(settings.token).toBe("tok");
  });

  it("keeps a configured url and fills token from openclaw.json when missing", async () => {
    tempDir = makeTempDir("studio-upstream-url-keep");
    process.env.OPENCLAW_STATE_DIR = tempDir;

    fs.mkdirSync(path.join(tempDir, "claw3d"), { recursive: true });
    fs.writeFileSync(
      path.join(tempDir, "claw3d", "settings.json"),
      JSON.stringify({ gateway: { url: "ws://gateway.example:18789", token: "" } }, null, 2),
      "utf8"
    );
    fs.writeFileSync(
      path.join(tempDir, "openclaw.json"),
      JSON.stringify({ gateway: { port: 18789, auth: { token: "tok-local" } } }, null, 2),
      "utf8"
    );

    const { loadUpstreamGatewaySettings } = await import("../../server/studio-settings");
    const settings = loadUpstreamGatewaySettings(process.env);
    expect(settings.url).toBe("ws://gateway.example:18789");
    expect(settings.token).toBe("tok-local");
  });

  it("accepts a BOM-prefixed settings file", async () => {
    tempDir = makeTempDir("studio-upstream-bom-settings");
    process.env.OPENCLAW_STATE_DIR = tempDir;

    fs.mkdirSync(path.join(tempDir, "claw3d"), { recursive: true });
    fs.writeFileSync(
      path.join(tempDir, "claw3d", "settings.json"),
      "\ufeff" + JSON.stringify({ gateway: { url: "ws://localhost:18789", token: "", adapterType: "demo" } }, null, 2),
      "utf8"
    );

    const { loadUpstreamGatewaySettings } = await import("../../server/studio-settings");
    const settings = loadUpstreamGatewaySettings(process.env);
    expect(settings.url).toBe("ws://localhost:18789");
    expect(settings.token).toBe("");
    expect(settings.adapterType).toBe("demo");
  });

  it("uses CLAW3D_GATEWAY_URL when studio settings are missing", async () => {
    tempDir = makeTempDir("studio-upstream-env-defaults");
    process.env.OPENCLAW_STATE_DIR = tempDir;
    process.env.CLAW3D_GATEWAY_URL = "ws://localhost:19500";
    process.env.CLAW3D_GATEWAY_TOKEN = "env-token";
    process.env.CLAW3D_GATEWAY_ADAPTER_TYPE = "demo";

    const { loadUpstreamGatewaySettings } = await import("../../server/studio-settings");
    const settings = loadUpstreamGatewaySettings(process.env);
    expect(settings.url).toBe("ws://localhost:19500");
    expect(settings.token).toBe("env-token");
    expect(settings.adapterType).toBe("demo");
  });

  it("uses detected local adapter ports when no explicit gateway url exists", async () => {
    tempDir = makeTempDir("studio-upstream-adapter-port-defaults");
    process.env.OPENCLAW_STATE_DIR = tempDir;
    process.env.HERMES_ADAPTER_PORT = "19444";

    const { loadUpstreamGatewaySettings } = await import("../../server/studio-settings");
    const settings = loadUpstreamGatewaySettings(process.env);
    expect(settings.url).toBe("ws://localhost:19444");
    expect(settings.token).toBe("");
    expect(settings.adapterType).toBe("hermes");
  });
});
