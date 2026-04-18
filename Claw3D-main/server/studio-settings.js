const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const LEGACY_STATE_DIRNAMES = [".clawdbot", ".moltbot"];
const NEW_STATE_DIRNAME = ".openclaw";

const resolveUserPath = (input) => {
  const trimmed = String(input ?? "").trim();
  if (!trimmed) return trimmed;
  if (trimmed.startsWith("~")) {
    const expanded = trimmed.replace(/^~(?=$|[\\/])/, os.homedir());
    return path.resolve(expanded);
  }
  return path.resolve(trimmed);
};

const resolveDefaultHomeDir = () => {
  const home = os.homedir();
  if (home) {
    try {
      if (fs.existsSync(home)) return home;
    } catch {}
  }
  return os.tmpdir();
};

const resolveStateDir = (env = process.env) => {
  const override =
    env.OPENCLAW_STATE_DIR?.trim() ||
    env.MOLTBOT_STATE_DIR?.trim() ||
    env.CLAWDBOT_STATE_DIR?.trim();
  if (override) return resolveUserPath(override);

  const home = resolveDefaultHomeDir();
  const newDir = path.join(home, NEW_STATE_DIRNAME);
  const legacyDirs = LEGACY_STATE_DIRNAMES.map((dir) => path.join(home, dir));
  try {
    if (fs.existsSync(newDir)) return newDir;
  } catch {}
  for (const dir of legacyDirs) {
    try {
      if (fs.existsSync(dir)) return dir;
    } catch {}
  }
  return newDir;
};

const resolveStudioSettingsPath = (env = process.env) => {
  return path.join(resolveStateDir(env), "claw3d", "settings.json");
};

const stripUtf8Bom = (raw) =>
  typeof raw === "string" && raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;

const readJsonFile = (filePath) => {
  if (!fs.existsSync(filePath)) return null;
  const raw = stripUtf8Bom(fs.readFileSync(filePath, "utf8"));
  return JSON.parse(raw);
};

const DEFAULT_GATEWAY_URL = "ws://localhost:18789";
const OPENCLAW_CONFIG_FILENAME = "openclaw.json";
const DEFAULT_LOCAL_GATEWAY_PORT = 18789;
const DEFAULT_DEMO_ADAPTER_FALLBACK_PORT = 18890;
const DEFAULT_CUSTOM_GATEWAY_URL = "http://localhost:7770";
const FORCE_SELECTION_ENV = "CLAW3D_GATEWAY_FORCE_SELECTION";

const isRecord = (value) => Boolean(value && typeof value === "object");

const normalizeAdapterType = (value) => {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (
    normalized === "openclaw" ||
    normalized === "hermes" ||
    normalized === "demo" ||
    normalized === "custom"
  ) {
    return normalized;
  }
  return null;
};

const isTruthyEnvValue = (value) => {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
};

const readOpenclawGatewayDefaults = (env = process.env) => {
  try {
    const stateDir = resolveStateDir(env);
    const configPath = path.join(stateDir, OPENCLAW_CONFIG_FILENAME);
    const parsed = readJsonFile(configPath);
    if (!isRecord(parsed)) return null;
    const gateway = isRecord(parsed.gateway) ? parsed.gateway : null;
    if (!gateway) return null;
    const auth = isRecord(gateway.auth) ? gateway.auth : null;
    const token = typeof auth?.token === "string" ? auth.token.trim() : "";
    const port =
      typeof gateway.port === "number" && Number.isFinite(gateway.port) ? gateway.port : null;
    if (!token) return null;
    const url = port
      ? `ws://localhost:${port}`
      : `ws://localhost:${DEFAULT_LOCAL_GATEWAY_PORT}`;
    if (!url) return null;
    return { url, token, adapterType: "openclaw" };
  } catch {
    return null;
  }
};

const readPortBasedGatewayProfile = (env, adapterType, envVarName) => {
  const raw = String(env?.[envVarName] ?? "").trim();
  if (!raw) return null;
  const port = Number.parseInt(raw, 10);
  if (!Number.isFinite(port) || port <= 0) return null;
  return { url: `ws://localhost:${port}`, token: "", adapterType };
};

const buildImplicitDemoFallbackProfile = (openclawDefaults) => {
  if (!openclawDefaults?.url) return null;
  try {
    const parsed = new URL(openclawDefaults.url);
    const port = Number.parseInt(parsed.port || `${DEFAULT_LOCAL_GATEWAY_PORT}`, 10);
    if (port !== DEFAULT_LOCAL_GATEWAY_PORT) return null;
  } catch {
    return null;
  }
  return {
    url: `ws://localhost:${DEFAULT_DEMO_ADAPTER_FALLBACK_PORT}`,
    token: "",
    adapterType: "demo",
  };
};

const buildEnvGatewayDefaults = (env = process.env, openclawDefaults = null) => {
  const envUrl = String(env?.CLAW3D_GATEWAY_URL ?? "").trim();
  const envToken = String(env?.CLAW3D_GATEWAY_TOKEN ?? "").trim();
  const envAdapterType = normalizeAdapterType(env?.CLAW3D_GATEWAY_ADAPTER_TYPE) || "openclaw";

  const hermesProfile = readPortBasedGatewayProfile(env, "hermes", "HERMES_ADAPTER_PORT");
  const demoProfile =
    readPortBasedGatewayProfile(env, "demo", "DEMO_ADAPTER_PORT") ||
    buildImplicitDemoFallbackProfile(openclawDefaults);

  if (envUrl) {
    return { url: envUrl, token: envToken, adapterType: envAdapterType };
  }
  if (hermesProfile) {
    return hermesProfile;
  }
  if (demoProfile) {
    return demoProfile;
  }
  return null;
};

const buildExplicitEnvGatewaySelection = (env = process.env, openclawDefaults = null) => {
  if (!isTruthyEnvValue(env?.[FORCE_SELECTION_ENV])) {
    return null;
  }

  const adapterType = normalizeAdapterType(env?.CLAW3D_GATEWAY_ADAPTER_TYPE);
  if (!adapterType) {
    return null;
  }

  const envUrl = String(env?.CLAW3D_GATEWAY_URL ?? "").trim();
  const envToken = String(env?.CLAW3D_GATEWAY_TOKEN ?? "").trim();
  if (envUrl) {
    return { url: envUrl, token: envToken, adapterType };
  }

  if (adapterType === "openclaw") {
    return {
      url: openclawDefaults?.url || DEFAULT_GATEWAY_URL,
      token: openclawDefaults?.token || envToken,
      adapterType,
    };
  }

  if (adapterType === "hermes") {
    return readPortBasedGatewayProfile(env, "hermes", "HERMES_ADAPTER_PORT") || {
      url: DEFAULT_GATEWAY_URL,
      token: "",
      adapterType,
    };
  }

  if (adapterType === "demo") {
    return (
      readPortBasedGatewayProfile(env, "demo", "DEMO_ADAPTER_PORT") ||
      buildImplicitDemoFallbackProfile(openclawDefaults) || {
        url: `ws://localhost:${DEFAULT_DEMO_ADAPTER_FALLBACK_PORT}`,
        token: "",
        adapterType,
      }
    );
  }

  return {
    url: DEFAULT_CUSTOM_GATEWAY_URL,
    token: envToken,
    adapterType,
  };
};

const repairLikelyOpenclawGatewaySelection = (gateway, openclawDefaults) => {
  if (!isRecord(gateway)) {
    return gateway;
  }
  const adapterType = normalizeAdapterType(gateway.adapterType);
  if (!adapterType || adapterType === "openclaw") {
    return gateway;
  }
  const persistedUrl = typeof gateway.url === "string" ? gateway.url.trim() : "";
  const openclawUrl = typeof openclawDefaults?.url === "string" ? openclawDefaults.url.trim() : "";
  if (!persistedUrl || !openclawUrl || persistedUrl !== openclawUrl) {
    return gateway;
  }
  const persistedToken = typeof gateway.token === "string" ? gateway.token.trim() : "";
  const openclawToken = typeof openclawDefaults?.token === "string" ? openclawDefaults.token.trim() : "";
  if (!persistedToken && !openclawToken) {
    return gateway;
  }
  const nextGateway = {
    ...gateway,
    adapterType: "openclaw",
    token: persistedToken || openclawToken,
  };
  if (isRecord(gateway.lastKnownGood)) {
    const lastKnownGoodUrl = typeof gateway.lastKnownGood.url === "string" ? gateway.lastKnownGood.url.trim() : "";
    if (lastKnownGoodUrl === openclawUrl) {
      nextGateway.lastKnownGood = {
        ...gateway.lastKnownGood,
        adapterType: "openclaw",
        token:
          typeof gateway.lastKnownGood.token === "string" && gateway.lastKnownGood.token.trim()
            ? gateway.lastKnownGood.token.trim()
            : persistedToken || openclawToken,
      };
    }
  }
  return nextGateway;
};

const loadUpstreamGatewaySettings = (env = process.env) => {
  const settingsPath = resolveStudioSettingsPath(env);
  const parsed = readJsonFile(settingsPath);
  const openclawDefaults = readOpenclawGatewayDefaults(env);
  const rawGateway = parsed && typeof parsed === "object" ? parsed.gateway : null;
  const gateway = repairLikelyOpenclawGatewaySelection(rawGateway, openclawDefaults);
  const envDefaults = buildEnvGatewayDefaults(env, openclawDefaults);
  const explicitEnvSelection = buildExplicitEnvGatewaySelection(env, openclawDefaults);

  const envAdapterTypeOverride = explicitEnvSelection?.adapterType || null;
  const envUrlOverride = explicitEnvSelection?.url || "";
  const envTokenOverride = explicitEnvSelection?.token || "";

  const persistedUrl = typeof gateway?.url === "string" ? gateway.url.trim() : "";
  const persistedToken = typeof gateway?.token === "string" ? gateway.token.trim() : "";
  const hasPersistedGateway = isRecord(gateway);
  const persistedAdapterType = normalizeAdapterType(gateway?.adapterType);

  // Adapter type: forced launcher selection > env defaults (.env.local) > persisted > openclaw defaults > fallback
  // env defaults (.env.local) now win over persisted UI state so stale
  // settings.json entries cannot override explicit developer configuration.
  const adapterType =
    envAdapterTypeOverride ||
    envDefaults?.adapterType ||
    persistedAdapterType ||
    (hasPersistedGateway || openclawDefaults ? "openclaw" : "openclaw");

  // When the resolved adapter type differs from the persisted one the
  // persisted URL likely points to the old adapter's port (e.g. demo on
  // 18890).  Prefer envDefaults which contain the correct port for the
  // newly-selected adapter type.  This covers both explicit force-selection
  // overrides AND plain .env.local env-var defaults winning over stale state.
  const envOverrodeAdapter =
    adapterType !== persistedAdapterType && (envAdapterTypeOverride || envDefaults?.adapterType);

  // URL: env override > (env-default when adapter switched) > persisted > env defaults > openclaw defaults > fallback
  const resolvedUrl =
    envUrlOverride ||
    (envOverrodeAdapter ? (envDefaults?.url || persistedUrl) : persistedUrl) ||
    envDefaults?.url || openclawDefaults?.url || DEFAULT_GATEWAY_URL;

  // Token: env override > persisted > env defaults > openclaw defaults
  const resolvedToken =
    envTokenOverride ||
    persistedToken ||
    ((envDefaults?.adapterType || "") === adapterType ? envDefaults?.token || "" : "") ||
    (adapterType === "openclaw" ? openclawDefaults?.token || "" : "");

  return {
    url: resolvedUrl,
    token: resolvedToken,
    adapterType,
    settingsPath,
  };
};

const clearPersistedGatewaySettings = (env = process.env) => {
  const settingsPath = resolveStudioSettingsPath(env);
  try {
    const parsed = readJsonFile(settingsPath);
    if (parsed && typeof parsed === "object" && parsed.gateway) {
      delete parsed.gateway;
      fs.writeFileSync(settingsPath, JSON.stringify(parsed, null, 2), "utf8");
      return true;
    }
  } catch {}
  return false;
};

module.exports = {
  resolveStateDir,
  resolveStudioSettingsPath,
  loadUpstreamGatewaySettings,
  clearPersistedGatewaySettings,
};
