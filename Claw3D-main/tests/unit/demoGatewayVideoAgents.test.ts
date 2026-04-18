import { describe, expect, it } from "vitest";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { handleMethod } = require("../../server/demo-gateway-adapter");

// Direct access to buildDemoReply for synchronous testing
// eslint-disable-next-line @typescript-eslint/no-require-imports
const gatewayModule = require("../../server/demo-gateway-adapter");

async function callMethod(method: string, params: Record<string, unknown> = {}) {
  const id = "test-" + Math.random().toString(36).slice(2);
  const result = await handleMethod(method, params, id, () => {});
  return result as { ok: boolean; payload?: unknown };
}

describe("demo gateway video agents", () => {
  it("returns all 6 agents including video pipeline agents", async () => {
    const res = await callMethod("agents.list");
    expect(res.ok).toBe(true);
    const agentsList = res.payload as { agents: { id: string; name: string; role: string }[] };
    expect(agentsList.agents.length).toBeGreaterThanOrEqual(6);

    const ids = agentsList.agents.map((a: { id: string }) => a.id);
    expect(ids).toContain("demo-orchestrator");
    expect(ids).toContain("demo-researcher");
    expect(ids).toContain("demo-builder");
    expect(ids).toContain("video-trend-scout");
    expect(ids).toContain("video-content-forge");
    expect(ids).toContain("video-tiktok-publisher");
  });

  it("video agents have correct roles", async () => {
    const res = await callMethod("agents.list");
    const agentsList = res.payload as { agents: { id: string; role: string }[] };

    const scout = agentsList.agents.find((a: { id: string }) => a.id === "video-trend-scout");
    const forge = agentsList.agents.find((a: { id: string }) => a.id === "video-content-forge");
    const nova = agentsList.agents.find((a: { id: string }) => a.id === "video-tiktok-publisher");

    expect(scout?.role).toBe("Trend Research");
    expect(forge?.role).toBe("Content Generation");
    expect(nova?.role).toBe("TikTok Publisher");
  });

  it("video agents have correct names", async () => {
    const res = await callMethod("agents.list");
    const agentsList = res.payload as { agents: { id: string; name: string }[] };

    const scout = agentsList.agents.find((a: { id: string }) => a.id === "video-trend-scout");
    const forge = agentsList.agents.find((a: { id: string }) => a.id === "video-content-forge");
    const nova = agentsList.agents.find((a: { id: string }) => a.id === "video-tiktok-publisher");

    expect(scout?.name).toBe("Scout");
    expect(forge?.name).toBe("Forge");
    expect(nova?.name).toBe("Nova");
  });

  it("returns a valid company plan JSON when given a planning prompt", async () => {
    const planningPrompt =
      "You are designing an AI company org structure for Claw3D.\n" +
      "Return only valid JSON with no markdown fence.\n" +
      "Company brief:\nA TikTok content studio that makes viral videos.";

    // Get the orchestrator agent info
    const res = await callMethod("agents.list");
    const agentsList = res.payload as { agents: { id: string; name: string; role: string }[] };
    const orchestrator = agentsList.agents.find((a: { id: string }) => a.id === "demo-orchestrator");
    expect(orchestrator).toBeDefined();

    // Call buildDemoReply directly (synchronous, no streaming delay)
    const reply = gatewayModule.buildDemoReply(orchestrator, planningPrompt);
    const parsed = JSON.parse(reply);

    expect(parsed.companyName).toBe("ViralForge Studios");
    expect(parsed.roles).toHaveLength(3);
    expect(parsed.roles[0].name).toBe("Scout");
    expect(parsed.roles[1].name).toBe("Forge");
    expect(parsed.roles[2].name).toBe("Nova");
    expect(parsed.roles[0].commandMode).toBe("auto");
    expect(parsed.roles[2].commandMode).toBe("ask");
    expect(parsed.sharedRules).toBeInstanceOf(Array);
    expect(parsed.plannerNotes).toBeInstanceOf(Array);
  });

  it("returns improved brief markdown when given an improve-brief prompt", async () => {
    const briefPrompt =
      "You are helping a user describe the company they want to build inside Claw3D.\n" +
      "Rewrite their brief so another connected runtime agent can generate a clean org structure from it.\n" +
      "User brief:\nI want to make TikTok videos.";

    // Get the orchestrator agent
    const res = await callMethod("agents.list");
    const agentsList = res.payload as { agents: { id: string; name: string; role: string }[] };
    const orchestrator = agentsList.agents.find((a: { id: string }) => a.id === "demo-orchestrator");
    expect(orchestrator).toBeDefined();

    const reply = gatewayModule.buildDemoReply(orchestrator, briefPrompt);
    expect(reply).toContain("## Company");
    expect(reply).toContain("## Goals");
    expect(reply).toContain("## Constraints");
    expect(reply).toContain("## Suggested Roles");
  });
});
