import { describe, expect, it } from "vitest";

import {
  getPackagedSkillById,
  getPackagedSkillBySkillKey,
  listPackagedSkills,
  buildPackagedSkillStatusEntry,
} from "@/lib/skills/catalog";
import { resolveSkillMarketplaceMetadata } from "@/lib/skills/marketplace";
import {
  listPackagedSkillTriggerDefinitions,
  resolveTriggeredSkillDefinition,
} from "@/lib/skills/triggers";
import { readPackagedSkillFiles } from "@/lib/skills/packaged";

describe("tiktok-video-pipeline skill", () => {
  it("is registered in the packaged skill catalog", () => {
    const skill = getPackagedSkillById("tiktok-video-pipeline");
    expect(skill).not.toBeNull();
    expect(skill?.skillKey).toBe("tiktok-video-pipeline");
    expect(skill?.name).toBe("tiktok-video-pipeline");
    expect(skill?.creatorName).toBeTruthy();
    expect(skill?.creatorUrl).toBeTruthy();
  });

  it("is findable by skill key", () => {
    const skill = getPackagedSkillBySkillKey("tiktok-video-pipeline");
    expect(skill).not.toBeNull();
    expect(skill?.packageId).toBe("tiktok-video-pipeline");
  });

  it("appears in the full packaged skills list", () => {
    const all = listPackagedSkills();
    const found = all.find((s) => s.packageId === "tiktok-video-pipeline");
    expect(found).toBeDefined();
  });

  it("has marketplace metadata with correct category", () => {
    const skill = getPackagedSkillById("tiktok-video-pipeline")!;
    const entry = buildPackagedSkillStatusEntry(skill);
    const meta = resolveSkillMarketplaceMetadata(entry);
    expect(meta.category).toBe("Content");
    expect(meta.tagline).toContain("Three-agent");
    expect(meta.hideStats).toBe(true);
    expect(meta.poweredByName).toBe(skill.creatorName);
  });

  it("has packaged files that can be read", () => {
    const files = readPackagedSkillFiles("tiktok-video-pipeline");
    expect(files.length).toBeGreaterThanOrEqual(1);
    const skillMd = files.find((f) => f.relativePath === "SKILL.md");
    expect(skillMd).toBeDefined();
    expect(skillMd?.content).toContain("tiktok-video-pipeline");
  });

  it("has trigger definitions for video pipeline phrases", () => {
    const triggers = listPackagedSkillTriggerDefinitions();
    const pipelineTrigger = triggers.find(
      (t) => t.skillKey === "tiktok-video-pipeline",
    );
    expect(pipelineTrigger).toBeDefined();
    expect(pipelineTrigger?.movementTarget).toBe("github");
    expect(pipelineTrigger?.activationPhrases).toContain("find viral trends");
    expect(pipelineTrigger?.activationPhrases).toContain("generate video");
    expect(pipelineTrigger?.activationPhrases).toContain("upload to tiktok");
  });

  it("matches trigger when agent asks about viral trends", () => {
    const triggers = listPackagedSkillTriggerDefinitions();
    const pipelineTrigger = triggers.find(
      (t) => t.skillKey === "tiktok-video-pipeline",
    );

    const matched = resolveTriggeredSkillDefinition({
      isAgentRunning: true,
      lastUserMessage: "Find viral trends for our next TikTok video",
      transcriptEntries: [],
      triggers: pipelineTrigger ? [pipelineTrigger] : [],
    });

    expect(matched?.skillKey).toBe("tiktok-video-pipeline");
    expect(matched?.movementTarget).toBe("github");
  });

  it("does not match trigger when agent is idle", () => {
    const triggers = listPackagedSkillTriggerDefinitions();
    const pipelineTrigger = triggers.find(
      (t) => t.skillKey === "tiktok-video-pipeline",
    );

    const matched = resolveTriggeredSkillDefinition({
      isAgentRunning: false,
      lastUserMessage: "Find viral trends",
      transcriptEntries: [],
      triggers: pipelineTrigger ? [pipelineTrigger] : [],
    });

    expect(matched).toBeNull();
  });
});
