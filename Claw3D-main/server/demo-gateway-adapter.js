"use strict";

const http = require("http");
const { randomUUID } = require("crypto");
const { WebSocketServer } = require("ws");

const DEFAULT_ADAPTER_PORT = 18890;
const FALLBACK_ADAPTER_PORT = 18891;
const ADAPTER_PORT = parseInt(process.env.DEMO_ADAPTER_PORT || `${DEFAULT_ADAPTER_PORT}`, 10);
const HAS_EXPLICIT_PORT = Boolean(process.env.DEMO_ADAPTER_PORT?.trim());
const MAIN_KEY = "main";
const MODELS = [{ id: "demo/mock-office", name: "Mock Office", provider: "demo" }];

const agents = new Map([
  [
    "demo-orchestrator",
    {
      id: "demo-orchestrator",
      name: "Avery",
      role: "Orchestrator",
      workspace: "/demo/orchestrator",
    },
  ],
  [
    "demo-researcher",
    {
      id: "demo-researcher",
      name: "Mika",
      role: "Research",
      workspace: "/demo/research",
    },
  ],
  [
    "demo-builder",
    {
      id: "demo-builder",
      name: "Rune",
      role: "Builder",
      workspace: "/demo/builder",
    },
  ],
  [
    "video-trend-scout",
    {
      id: "video-trend-scout",
      name: "Scout",
      role: "Trend Research",
      workspace: "/demo/video/scout",
    },
  ],
  [
    "video-content-forge",
    {
      id: "video-content-forge",
      name: "Forge",
      role: "Content Generation",
      workspace: "/demo/video/forge",
    },
  ],
  [
    "video-tiktok-publisher",
    {
      id: "video-tiktok-publisher",
      name: "Nova",
      role: "TikTok Publisher",
      workspace: "/demo/video/publisher",
    },
  ],
]);

const files = new Map();
const sessionSettings = new Map();
const conversationHistory = new Map();
const activeRuns = new Map();
const activeSendEventFns = new Set();

const EMPTY_REQUIREMENTS = {
  bins: [],
  anyBins: [],
  env: [],
  config: [],
  os: [],
};

const DEMO_SKILLS = [
  {
    name: "task-manager",
    description:
      "Capture actionable requests as persistent tasks and keep a shared Kanban task store in sync.",
    source: "openclaw-bundled",
    bundled: true,
    filePath: "/demo/skills/task-manager/SKILL.md",
    baseDir: "/demo/skills/task-manager",
    skillKey: "task-manager",
    always: true,
    disabled: false,
    blockedByAllowlist: false,
    eligible: true,
    requirements: EMPTY_REQUIREMENTS,
    missing: EMPTY_REQUIREMENTS,
    configChecks: [],
    install: [],
  },
];

function randomId() {
  return randomUUID().replace(/-/g, "");
}

function sessionKeyFor(agentId) {
  return `agent:${agentId}:${MAIN_KEY}`;
}

function getHistory(sessionKey) {
  if (!conversationHistory.has(sessionKey)) {
    conversationHistory.set(sessionKey, []);
  }
  return conversationHistory.get(sessionKey);
}

function clearHistory(sessionKey) {
  conversationHistory.delete(sessionKey);
}

function resOk(id, payload) {
  return { type: "res", id, ok: true, payload: payload ?? {} };
}

function resErr(id, code, message) {
  return { type: "res", id, ok: false, error: { code, message } };
}

function broadcastEvent(frame) {
  for (const send of activeSendEventFns) {
    try {
      send(frame);
    } catch {}
  }
}

function agentListPayload() {
  return [...agents.values()].map((agent) => ({
    id: agent.id,
    name: agent.name,
    workspace: agent.workspace,
    identity: { name: agent.name, emoji: "🤖" },
    role: agent.role,
  }));
}

function buildDemoReply(agent, message) {
  const normalized = message.trim().toLowerCase();

  // --- Company builder planning prompts ---
  if (normalized.includes("designing an ai company org structure") || normalized.includes("return only valid json")) {
    return JSON.stringify({
      companyName: "ViralForge Studios",
      summary: "An AI-powered content studio that researches viral trends, generates short-form videos, and publishes them to TikTok for maximum engagement.",
      sharedRules: [
        "Keep updates concise and action-oriented.",
        "Hand off work clearly when another role should take over.",
        "Prioritize high-engagement content formats.",
        "Track and report performance metrics after every upload cycle."
      ],
      plannerNotes: [
        "Scout feeds trend briefs to Forge, who renders and passes to Nova for upload.",
        "All three roles share a pipeline state file for coordination.",
        "Treat the user's content brief as the source of truth."
      ],
      roles: [
        {
          id: "scout",
          name: "Scout",
          purpose: "Monitor TikTok trending feeds, analyze engagement patterns, and identify high-potential video formats and hashtag clusters.",
          soul: "Obsessively curious trend-spotter who lives in the data and always knows what's about to blow up.",
          responsibilities: ["Sweep TikTok trending feeds daily", "Analyze hashtag engagement tiers", "Produce trend briefs with format recommendations", "Track competitor content performance"],
          collaborators: ["Forge", "Nova"],
          tools: ["Web scraping", "Trend analysis APIs", "Hashtag research"],
          heartbeat: ["Check trending feeds for new high-potential formats", "Update the trend brief if patterns shifted"],
          emoji: "🔍",
          creature: "hawk",
          vibe: "sharp, data-driven, always one step ahead",
          userContext: "",
          commandMode: "auto"
        },
        {
          id: "forge",
          name: "Forge",
          purpose: "Generate short-form AI videos using ComfyUI for key frames and FFmpeg for assembly, matching the latest trend brief from Scout.",
          soul: "Relentless creative engine that turns concepts into polished visual content at machine speed.",
          responsibilities: ["Generate key frames via ComfyUI", "Assemble frames into videos with FFmpeg", "Apply Ken Burns effects and transitions", "Overlay background audio from session library"],
          collaborators: ["Scout", "Nova"],
          tools: ["ComfyUI", "FFmpeg", "Image generation pipelines"],
          heartbeat: ["Check render queue for pending jobs", "Report any failed generations"],
          emoji: "🔥",
          creature: "phoenix",
          vibe: "intense, creative, fast-moving",
          userContext: "",
          commandMode: "auto"
        },
        {
          id: "nova",
          name: "Nova",
          purpose: "Upload rendered videos to TikTok via the Content Posting API, monitor processing status, and track engagement metrics.",
          soul: "Methodical publisher who treats every upload as a launch event and obsesses over timing and metrics.",
          responsibilities: ["Upload videos to TikTok via Content Posting API", "Monitor upload processing status", "Track engagement metrics across published videos", "Optimize posting schedule based on performance data"],
          collaborators: ["Scout", "Forge"],
          tools: ["TikTok Content Posting API", "Analytics dashboards"],
          heartbeat: ["Check for videos ready to upload", "Report latest engagement metrics"],
          emoji: "🚀",
          creature: "falcon",
          vibe: "precise, metrics-obsessed, launch-day energy",
          userContext: "",
          commandMode: "ask"
        }
      ]
    });
  }

  if (normalized.includes("helping a user describe the company") || normalized.includes("rewrite their brief")) {
    return `## Company\nViralForge Studios — an AI-powered content studio that turns trending topics into viral short-form videos.\n\n## Goals\n- Research and identify high-engagement TikTok content formats daily\n- Generate AI-powered videos using ComfyUI and FFmpeg pipelines\n- Publish content to TikTok with optimized timing and hashtag strategy\n- Track performance metrics and feed learnings back into trend research\n\n## Constraints\n- Videos must be 5–15 seconds for optimal TikTok engagement\n- Content must be original AI-generated material, not reposts\n- Posting frequency: 1–3 videos per day maximum\n- All uploads go through the TikTok Content Posting API v2\n\n## Suggested Roles\n- **Scout** — Trend researcher who monitors TikTok feeds and produces briefs\n- **Forge** — Content generator who renders videos from ComfyUI + FFmpeg\n- **Nova** — Publisher who uploads to TikTok and tracks engagement metrics`;
  }

  // --- Role-aware replies for dynamically created agents ---
  if (!agent.id.startsWith("demo-") && !agent.id.startsWith("video-")) {
    const roleLower = (agent.role || "").toLowerCase();
    if (roleLower.includes("trend") || roleLower.includes("research") || roleLower.includes("scout")) {
      return `${agent.name} online — ready for trend research. I'll monitor feeds, analyze engagement patterns, and produce actionable briefs. Send me "find viral trends" to begin the first sweep.`;
    }
    if (roleLower.includes("content") || roleLower.includes("generation") || roleLower.includes("forge") || roleLower.includes("build")) {
      return `${agent.name} initialized — content generation pipeline standing by. My render queue is empty and ComfyUI is warmed up. Tell me to "generate a video" with a style prompt to kick off the first render.`;
    }
    if (roleLower.includes("publish") || roleLower.includes("tiktok") || roleLower.includes("nova") || roleLower.includes("social")) {
      return `${agent.name} reporting — TikTok publishing desk is live. API credentials are loaded and I'm monitoring for videos to upload. Send "upload to tiktok" when content is ready, or ask for "performance metrics" to check our numbers.`;
    }
    return `${agent.name} reporting in as ${agent.role || "team member"}. I'm configured and ready to work. You said: "${message.trim()}". Tell me what to focus on first.`;
  }

  // --- Video pipeline agent replies ---
  if (agent.id === "video-trend-scout") {
    if (normalized.includes("trend") || normalized.includes("viral") || normalized.includes("research")) {
      return `${agent.name} here — trend sweep complete. Top 3 viral formats right now:\n\n` +
        `1. **"Satisfying Process" loops** — 15s clips of AI-generated fluid simulations or morphing geometry. ` +
        `Avg 2.4M views. Tags: #satisfying #oddlysatisfying #ai #process\n` +
        `2. **"AI Art Transformation"** — before/after reveals with dramatic music. ` +
        `Avg 1.8M views. Tags: #aiart #transformation #beforeafter\n` +
        `3. **"Glitch Aesthetic" edits** — rapid-cut montages with chromatic aberration and data-moshing. ` +
        `Avg 1.1M views. Tags: #glitchart #aesthetic #fyp #digitalart\n\n` +
        `Recommendation: Go with format #1. Highest engagement-to-effort ratio. ` +
        `I'll pass the brief to Forge for generation.`;
    }
    if (normalized.includes("hashtag") || normalized.includes("tag")) {
      return `${agent.name} — hashtag analysis for current cycle:\n\n` +
        `Tier 1 (>500M views): #fyp #foryou #viral #ai\n` +
        `Tier 2 (>100M views): #aiart #satisfying #aesthetic #techtok\n` +
        `Tier 3 (niche, high engagement): #generativeart #comfyui #proceduralart #aivideo\n\n` +
        `Optimal tag count: 4-6 per post. Mix one Tier 1, two Tier 2, and one Tier 3 for best reach.`;
    }
    return `${agent.name} reporting from trend research. You said: "${message.trim()}". ` +
      `I monitor TikTok trending feeds, analyze engagement patterns, and identify high-potential video formats. ` +
      `Ask me to "find viral trends" or "analyze hashtags" to get started.`;
  }

  if (agent.id === "video-content-forge") {
    if (normalized.includes("generate") || normalized.includes("create") || normalized.includes("render") || normalized.includes("make")) {
      return `${agent.name} — generation pipeline initialized.\n\n` +
        `**Pipeline status:**\n` +
        `- Key frames: Generating 8 frames via ComfyUI (384×384, euler_ancestral, 8 steps)\n` +
        `- Style: Satisfying process loop — fluid metallic morphing\n` +
        `- Duration target: 12 seconds @ 30fps\n` +
        `- Post-processing: Ken Burns zoom + crossfade transitions via FFmpeg\n` +
        `- Background audio: ambient synth pad from session library\n\n` +
        `⏳ Estimated completion: ~45 seconds. I'll notify Nova when the video is ready for upload.`;
    }
    if (normalized.includes("status") || normalized.includes("progress")) {
      return `${agent.name} — current render status:\n\n` +
        `✅ Key frames: 8/8 complete\n` +
        `✅ Frame interpolation: Done\n` +
        `✅ Audio overlay: Applied\n` +
        `✅ Final encode: MP4 ready\n\n` +
        `Output: \`generated-videos/satisfying-morph-001.mp4\` (12.4s, 1080×1080, 8.2MB)\n` +
        `Video is queued for Nova to upload.`;
    }
    return `${agent.name} at the content forge. You said: "${message.trim()}". ` +
      `I generate short-form videos using ComfyUI for key frames and FFmpeg for assembly. ` +
      `Tell me to "generate a video" with a style prompt, or ask for "render status".`;
  }

  if (agent.id === "video-tiktok-publisher") {
    if (normalized.includes("upload") || normalized.includes("publish") || normalized.includes("post")) {
      return `${agent.name} — initiating TikTok upload.\n\n` +
        `**Upload details:**\n` +
        `- File: \`satisfying-morph-001.mp4\` (8.2MB)\n` +
        `- Title: "Watch this satisfying AI morph loop 🌊✨"\n` +
        `- Tags: #satisfying #aiart #fyp #generativeart #oddlysatisfying\n` +
        `- Privacy: Public\n\n` +
        `✅ Upload complete! Video is processing on TikTok servers.\n` +
        `📎 Link: https://www.tiktok.com/@yourchannel/video/demo-001\n` +
        `📊 Initial metrics will be available in ~30 minutes.`;
    }
    if (normalized.includes("metric") || normalized.includes("stat") || normalized.includes("performance") || normalized.includes("analytics")) {
      return `${agent.name} — TikTok performance report:\n\n` +
        `**Last 24h across 3 videos:**\n` +
        `- Total views: 47,200\n` +
        `- Likes: 3,840 (8.1% rate)\n` +
        `- Shares: 612\n` +
        `- Comments: 284\n` +
        `- New followers: +127\n` +
        `- Best performer: "Satisfying AI Morph #1" — 28,400 views\n\n` +
        `Engagement is above average for the niche. Recommend posting at 6PM EST for next upload.`;
    }
    return `${agent.name} here, TikTok publishing desk. You said: "${message.trim()}". ` +
      `I handle video uploads to TikTok via the Content Posting API, track engagement metrics, and optimize posting schedules. ` +
      `Tell me to "upload to TikTok" or ask for "performance metrics".`;
  }

  // --- Original demo agent replies ---
  const opening =
    agent.role === "Orchestrator"
      ? `${agent.name} here. Demo office is live and the team is synced.`
      : `${agent.name} reporting in from the ${agent.role.toLowerCase()} desk.`;
  const action =
    agent.role === "Research"
      ? "I would break this down into sources, constraints, and next questions."
      : agent.role === "Builder"
        ? "I would turn that into concrete implementation steps and validation."
        : "I can coordinate the team, route work, and summarize progress.";
  return `${opening} You said: "${message.trim()}". ${action}`;
}

async function handleMethod(method, params, id, sendEvent) {
  const p = params || {};

  switch (method) {
    case "agents.list":
      return resOk(id, { defaultId: "demo-orchestrator", mainKey: MAIN_KEY, agents: agentListPayload() });

    case "agents.create": {
      const name = typeof p.name === "string" && p.name.trim() ? p.name.trim() : "Demo Agent";
      const role = typeof p.role === "string" ? p.role.trim() : "";
      const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "demo-agent";
      const agentId = `${slug}-${randomId().slice(0, 6)}`;
      agents.set(agentId, {
        id: agentId,
        name,
        role,
        workspace: `/demo/${slug}`,
      });
      broadcastEvent({
        type: "event",
        event: "presence",
        payload: { sessions: { recent: [], byAgent: [] } },
      });
      return resOk(id, { agentId, name, workspace: `/demo/${slug}` });
    }

    case "agents.update": {
      const agentId = typeof p.agentId === "string" ? p.agentId.trim() : "";
      const agent = agents.get(agentId);
      if (!agent) return resErr(id, "not_found", `Agent ${agentId} not found`);
      if (typeof p.name === "string" && p.name.trim()) agent.name = p.name.trim();
      if (typeof p.role === "string") agent.role = p.role.trim();
      return resOk(id, { ok: true, removedBindings: 0 });
    }

    case "agents.delete": {
      const agentId = typeof p.agentId === "string" ? p.agentId.trim() : "";
      if (agentId && agents.has(agentId) && agentId !== "demo-orchestrator") {
        agents.delete(agentId);
        clearHistory(sessionKeyFor(agentId));
      }
      return resOk(id, { ok: true, removedBindings: 0 });
    }

    case "agents.files.get": {
      const key = `${p.agentId || "demo-orchestrator"}/${p.name || ""}`;
      const content = files.get(key);
      return resOk(id, { file: content !== undefined ? { content } : { missing: true } });
    }

    case "agents.files.set": {
      const key = `${p.agentId || "demo-orchestrator"}/${p.name || ""}`;
      files.set(key, typeof p.content === "string" ? p.content : "");
      return resOk(id, {});
    }

    case "config.get":
      return resOk(id, {
        config: { gateway: { reload: { mode: "hot" } } },
        hash: "demo-gateway",
        exists: true,
        path: "/demo/config.json",
      });

    case "config.patch":
    case "config.set":
      return resOk(id, { hash: "demo-gateway" });

    case "exec.approvals.get":
      return resOk(id, {
        path: "",
        exists: true,
        hash: "demo-approvals",
        file: { version: 1, defaults: { security: "full", ask: "off", autoAllowSkills: true }, agents: {} },
      });

    case "exec.approvals.set":
      return resOk(id, { hash: "demo-approvals" });

    case "exec.approval.resolve":
      return resOk(id, { ok: true });

    case "models.list":
      return resOk(id, { models: MODELS });

    case "skills.status":
      return resOk(id, {
        workspaceDir: "/demo/workspace/demo-orchestrator",
        managedSkillsDir: "/demo/skills",
        skills: DEMO_SKILLS,
      });

    case "cron.list":
      return resOk(id, { jobs: [] });

    case "cron.add":
    case "cron.run":
    case "cron.remove":
      return resErr(id, "unsupported_method", `Demo runtime does not support ${method}.`);

    case "sessions.list": {
      const sessions = [...agents.values()].map((agent) => {
        const sessionKey = sessionKeyFor(agent.id);
        const history = getHistory(sessionKey);
        const settings = sessionSettings.get(sessionKey) || {};
        return {
          key: sessionKey,
          agentId: agent.id,
          updatedAt: history.length > 0 ? Date.now() : null,
          displayName: "Main",
          origin: { label: agent.name, provider: "demo" },
          model: settings.model || MODELS[0].id,
          modelProvider: "demo",
        };
      });
      return resOk(id, { sessions });
    }

    case "sessions.preview": {
      const keys = Array.isArray(p.keys) ? p.keys : [];
      const limit = typeof p.limit === "number" ? p.limit : 8;
      const maxChars = typeof p.maxChars === "number" ? p.maxChars : 240;
      const previews = keys.map((key) => {
        const history = getHistory(key);
        if (history.length === 0) return { key, status: "empty", items: [] };
        const items = history.slice(-limit).map((msg) => ({
          role: msg.role === "assistant" ? "assistant" : "user",
          text: String(msg.content || "").slice(0, maxChars),
          timestamp: Date.now(),
        }));
        return { key, status: "ok", items };
      });
      return resOk(id, { ts: Date.now(), previews });
    }

    case "sessions.patch": {
      const key = typeof p.key === "string" ? p.key : sessionKeyFor("demo-orchestrator");
      const current = sessionSettings.get(key) || {};
      const next = { ...current };
      if (p.model !== undefined) next.model = p.model;
      if (p.thinkingLevel !== undefined) next.thinkingLevel = p.thinkingLevel;
      sessionSettings.set(key, next);
      return resOk(id, {
        ok: true,
        key,
        entry: { thinkingLevel: next.thinkingLevel },
        resolved: { model: next.model || MODELS[0].id, modelProvider: "demo" },
      });
    }

    case "sessions.reset": {
      const key = typeof p.key === "string" ? p.key : sessionKeyFor("demo-orchestrator");
      clearHistory(key);
      return resOk(id, { ok: true });
    }

    case "chat.send": {
      const sessionKey = typeof p.sessionKey === "string" ? p.sessionKey : sessionKeyFor("demo-orchestrator");
      const agentId = sessionKey.startsWith("agent:") ? sessionKey.split(":")[1] : "demo-orchestrator";
      const agent = agents.get(agentId) || agents.get("demo-orchestrator");
      const message = typeof p.message === "string" ? p.message.trim() : String(p.message || "").trim();
      const runId = typeof p.idempotencyKey === "string" && p.idempotencyKey ? p.idempotencyKey : randomId();
      if (!message) return resOk(id, { status: "no-op", runId });

      const reply = buildDemoReply(agent, message);
      let aborted = false;
      activeRuns.set(runId, {
        runId,
        sessionKey,
        agentId,
        abort() {
          aborted = true;
        },
      });

      setImmediate(async () => {
        let seq = 0;
        const emitChat = (state, extra) => {
          sendEvent({
            type: "event",
            event: "chat",
            seq: seq++,
            payload: { runId, sessionKey, state, ...extra },
          });
        };

        try {
          const words = reply.split(" ");
          let partial = "";
          for (const word of words) {
            if (aborted) break;
            partial = partial ? `${partial} ${word}` : word;
            emitChat("delta", { message: { role: "assistant", content: partial } });
            await new Promise((resolve) => setTimeout(resolve, 45));
          }

          if (aborted) {
            emitChat("aborted", {});
            return;
          }

          const history = getHistory(sessionKey);
          history.push({ role: "user", content: message });
          history.push({ role: "assistant", content: reply });
          emitChat("final", { stopReason: "end_turn", message: { role: "assistant", content: reply } });
          sendEvent({
            type: "event",
            event: "presence",
            seq: seq++,
            payload: {
              sessions: {
                recent: [{ key: sessionKey, updatedAt: Date.now() }],
                byAgent: [{ agentId, recent: [{ key: sessionKey, updatedAt: Date.now() }] }],
              },
            },
          });
        } finally {
          activeRuns.delete(runId);
        }
      });

      return resOk(id, { status: "started", runId });
    }

    case "chat.abort": {
      const runId = typeof p.runId === "string" ? p.runId.trim() : "";
      const sessionKey = typeof p.sessionKey === "string" ? p.sessionKey.trim() : "";
      let aborted = 0;
      if (runId) {
        const handle = activeRuns.get(runId);
        if (handle) {
          handle.abort();
          activeRuns.delete(runId);
          aborted += 1;
        }
      } else if (sessionKey) {
        for (const [activeRunId, handle] of activeRuns.entries()) {
          if (handle.sessionKey !== sessionKey) continue;
          handle.abort();
          activeRuns.delete(activeRunId);
          aborted += 1;
        }
      }
      return resOk(id, { ok: true, aborted });
    }

    case "chat.history": {
      const sessionKey = typeof p.sessionKey === "string" ? p.sessionKey : sessionKeyFor("demo-orchestrator");
      return resOk(id, { sessionKey, messages: getHistory(sessionKey) });
    }

    case "agent.wait": {
      const runId = typeof p.runId === "string" ? p.runId : "";
      const timeoutMs = typeof p.timeoutMs === "number" ? p.timeoutMs : 30000;
      const start = Date.now();
      while (activeRuns.has(runId) && Date.now() - start < timeoutMs) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      return resOk(id, { status: activeRuns.has(runId) ? "running" : "done" });
    }

    case "status": {
      const recent = [...agents.keys()].flatMap((agentId) => {
        const key = sessionKeyFor(agentId);
        const history = getHistory(key);
        return history.length > 0 ? [{ key, updatedAt: Date.now() }] : [];
      });
      return resOk(id, {
        sessions: {
          recent,
          byAgent: [...agents.keys()].map((agentId) => ({
            agentId,
            recent: recent.filter((entry) => entry.key.includes(`:${agentId}:`)),
          })),
        },
      });
    }

    case "wake":
      return resOk(id, { ok: true });

    default:
      return resOk(id, {});
  }
}

function startAdapter() {
  const httpServer = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("Claw3D Demo Gateway Adapter\n");
  });
  let currentPort = ADAPTER_PORT;
  let retriedWithFallback = false;
  let hasStartedListening = false;
  let startupErrorHandled = false;

  const wss = new WebSocketServer({ server: httpServer });
  wss.on("connection", (ws) => {
    let connected = false;
    let globalSeq = 0;

    const send = (frame) => {
      if (ws.readyState !== ws.OPEN) return;
      ws.send(JSON.stringify(frame));
    };

    const sendEventFn = (frame) => {
      if (frame.type === "event" && typeof frame.seq !== "number") {
        frame.seq = globalSeq++;
      }
      send(frame);
    };

    activeSendEventFns.add(sendEventFn);
    send({ type: "event", event: "connect.challenge", payload: { nonce: randomId() } });

    ws.on("message", async (raw) => {
      let frame;
      try {
        frame = JSON.parse(raw.toString("utf8"));
      } catch {
        return;
      }
      if (!frame || typeof frame !== "object" || frame.type !== "req") return;
      const { id, method, params } = frame;
      if (typeof id !== "string" || typeof method !== "string") return;

      if (method === "connect") {
        connected = true;
        send({
          type: "res",
          id,
          ok: true,
          payload: {
            type: "hello-ok",
            protocol: 3,
            adapterType: "demo",
            features: {
              methods: [
                "agents.list",
                "agents.create",
                "agents.delete",
                "agents.update",
                "sessions.list",
                "sessions.preview",
                "sessions.patch",
                "sessions.reset",
                "chat.send",
                "chat.abort",
                "chat.history",
                "agent.wait",
                "status",
                "config.get",
                "config.set",
                "config.patch",
                "agents.files.get",
                "agents.files.set",
                "exec.approvals.get",
                "exec.approvals.set",
                "exec.approval.resolve",
                "wake",
                "skills.status",
                "models.list",
                "cron.list",
              ],
              events: ["chat", "presence", "heartbeat"],
            },
            snapshot: {
              health: {
                agents: [...agents.values()].map((agent) => ({
                  agentId: agent.id,
                  name: agent.name,
                  isDefault: agent.id === "demo-orchestrator",
                })),
                defaultAgentId: "demo-orchestrator",
              },
              sessionDefaults: { mainKey: MAIN_KEY },
            },
            auth: { role: "operator", scopes: ["operator.admin"] },
            policy: { tickIntervalMs: 30000 },
          },
        });
        return;
      }

      if (!connected) {
        send(resErr(id, "not_connected", "Send connect first."));
        return;
      }

      try {
        send(await handleMethod(method, params, id, sendEventFn));
      } catch (error) {
        send(resErr(id, "internal_error", error instanceof Error ? error.message : "Internal error"));
      }
    });

    ws.on("close", () => activeSendEventFns.delete(sendEventFn));
    ws.on("error", () => activeSendEventFns.delete(sendEventFn));
  });

  const listen = (port) => {
    currentPort = port;
    startupErrorHandled = false;
    httpServer.listen(port, "127.0.0.1", () => {
      if (hasStartedListening) {
        return;
      }
      hasStartedListening = true;
      console.log(`[demo-gateway] Listening on ws://localhost:${currentPort}`);
      if (retriedWithFallback) {
        console.log(`[demo-gateway] Port ${DEFAULT_ADAPTER_PORT} is busy, so demo mode moved to ${currentPort}.`);
      }
      console.log(`[demo-gateway] Connect Claw3D to ws://localhost:${currentPort}`);
      console.log("[demo-gateway] No OpenClaw or Hermes required.");
    });
  };

  const handleStartupError = (err) => {
    if (startupErrorHandled) {
      return;
    }
    startupErrorHandled = true;
    if (
      err?.code === "EADDRINUSE" &&
      !HAS_EXPLICIT_PORT &&
      !retriedWithFallback &&
      currentPort === DEFAULT_ADAPTER_PORT
    ) {
      retriedWithFallback = true;
      hasStartedListening = false;
      console.warn(
        `[demo-gateway] Port ${DEFAULT_ADAPTER_PORT} is already in use, likely by a local OpenClaw gateway. Retrying on ${FALLBACK_ADAPTER_PORT}.`
      );
      setImmediate(() => listen(FALLBACK_ADAPTER_PORT));
      return;
    }

    if (err?.code === "EADDRINUSE") {
      console.error(`[demo-gateway] Port ${currentPort} in use. Set DEMO_ADAPTER_PORT to change it.`);
    } else {
      console.error("[demo-gateway] Server error:", err instanceof Error ? err.message : String(err));
    }
    process.exit(1);
  };

  httpServer.on("error", handleStartupError);
  wss.on("error", (err) => {
    if (!hasStartedListening) {
      handleStartupError(err);
      return;
    }
    console.error("[demo-gateway] WebSocket server error:", err instanceof Error ? err.message : String(err));
  });

  listen(ADAPTER_PORT);
}

if (require.main === module) {
  startAdapter();
}

module.exports = {
  handleMethod,
  startAdapter,
  buildDemoReply,
};
