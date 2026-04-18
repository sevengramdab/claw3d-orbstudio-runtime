import fs from "node:fs";
import path from "node:path";

import { resolveStateDir } from "@/lib/clawdbot/paths";
import {
  defaultStudioSettings,
  mergeStudioSettings,
  normalizeStudioSettings,
  type StudioGatewayAdapterType,
  type StudioGatewayConnectionState,
  type StudioGatewayProfile,
  type StudioGatewaySettings,
  type StudioSettings,
  type StudioSettingsPatch,
} from "@/lib/studio/settings";

// Studio settings are intentionally stored as a local JSON file for a single-user workflow.
// That includes gateway connection details, so treat the state directory as plaintext secret
// storage and document any changes to this threat model in README.md and SECURITY.md.
const SETTINGS_DIRNAME = "claw3d";
const SETTINGS_FILENAME = "settings.json";
const OPENCLAW_CONFIG_FILENAME = "openclaw.json";
const DEFAULT_LOCAL_GATEWAY_PORT = 18789;
const DEFAULT_DEMO_ADAPTER_FALLBACK_PORT = 18890;
const DEFAULT_CUSTOM_GATEWAY_URL = "http://localhost:7770";
const FORCE_SELECTION_ENV = "CLAW3D_GATEWAY_FORCE_SELECTION";

const stripUtf8Bom = (raw: string) =>
  raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;

export const resolveStudioSettingsPath = () =>
  path.join(resolveStateDir(), SETTINGS_DIRNAME, SETTINGS_FILENAME);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === "object");

const buildGatewaySettings = (params: {
  adapterType: StudioGatewayAdapterType;
  url: string;
  token?: string;
  profiles?: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>>;
}): StudioGatewaySettings => ({
  url: params.url,
  token: params.token ?? "",
  adapterType: params.adapterType,
  ...(params.profiles ? { profiles: params.profiles } : {}),
});

const buildLocalProfile = (url: string, token = ""): StudioGatewayProfile => ({ url, token });

const mergeGatewayProfileMaps = (
  persisted: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> | undefined,
  defaults: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> | undefined
): Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> | undefined => {
  const merged: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> = {
    ...(defaults ?? {}),
    ...(persisted ?? {}),
  };
  return Object.keys(merged).length > 0 ? merged : undefined;
};

const resolveGatewayTokenForAdapter = (
  adapterType: StudioGatewayAdapterType,
  currentToken: string,
  profiles: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> | undefined,
  defaults: StudioGatewaySettings | null
) => {
  if (currentToken) {
    return currentToken;
  }
  if (adapterType !== "openclaw") {
    return profiles?.[adapterType]?.token ?? "";
  }
  return (
    profiles?.openclaw?.token ??
    (defaults?.adapterType === "openclaw" ? defaults.token : "")
  );
};

const mergeGatewayConnectionStateWithDefaults = (
  state: StudioGatewayConnectionState | undefined,
  defaults: StudioGatewaySettings | null,
  profiles: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> | undefined
): StudioGatewayConnectionState | undefined => {
  if (!state) {
    return undefined;
  }
  return {
    ...state,
    token: resolveGatewayTokenForAdapter(state.adapterType, state.token, profiles, defaults),
  };
};

const mergePersistedGatewaySettingsWithDefaults = (
  persisted: StudioGatewaySettings,
  defaults: StudioGatewaySettings | null
): StudioGatewaySettings => {
  const profiles = mergeGatewayProfileMaps(persisted.profiles, defaults?.profiles);
  const selectedProfile = profiles?.[persisted.adapterType];
  return {
    ...persisted,
    url: persisted.url.trim() || selectedProfile?.url || defaults?.url || "",
    token: resolveGatewayTokenForAdapter(
      persisted.adapterType,
      persisted.token,
      profiles,
      defaults
    ),
    ...(profiles ? { profiles } : {}),
    ...(mergeGatewayConnectionStateWithDefaults(
      persisted.lastKnownGood,
      defaults,
      profiles
    )
      ? {
          lastKnownGood: mergeGatewayConnectionStateWithDefaults(
            persisted.lastKnownGood,
            defaults,
            profiles
          ),
        }
      : {}),
  };
};

const mergePersistedGatewaySettingsWithExplicitEnvOverride = (
  persisted: StudioGatewaySettings,
  defaults: StudioGatewaySettings | null,
  explicitEnvDefaults: StudioGatewaySettings
): StudioGatewaySettings => {
  const profiles = mergeGatewayProfileMaps(persisted.profiles, defaults?.profiles);
  const selectedProfile =
    explicitEnvDefaults.profiles?.[explicitEnvDefaults.adapterType] ??
    buildLocalProfile(explicitEnvDefaults.url, explicitEnvDefaults.token);
  const mergedProfiles: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> = {
    ...(profiles ?? {}),
    [explicitEnvDefaults.adapterType]: selectedProfile,
  };
  return {
    ...persisted,
    url: explicitEnvDefaults.url,
    token: explicitEnvDefaults.token,
    adapterType: explicitEnvDefaults.adapterType,
    profiles: mergedProfiles,
    lastKnownGood: {
      url: explicitEnvDefaults.url,
      token: explicitEnvDefaults.token,
      adapterType: explicitEnvDefaults.adapterType,
    },
  };
};

const readOpenclawGatewayDefaults = (): StudioGatewaySettings | null => {
  try {
    const configPath = path.join(resolveStateDir(), OPENCLAW_CONFIG_FILENAME);
    if (!fs.existsSync(configPath)) return null;
    const raw = stripUtf8Bom(fs.readFileSync(configPath, "utf8"));
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed)) return null;
    const gateway = isRecord(parsed.gateway) ? parsed.gateway : null;
    if (!gateway) return null;
    const auth = isRecord(gateway.auth) ? gateway.auth : null;
    const token = typeof auth?.token === "string" ? auth.token.trim() : "";
    const port = typeof gateway.port === "number" && Number.isFinite(gateway.port) ? gateway.port : null;
    if (!token) return null;
    const url = port ? `ws://localhost:${port}` : `ws://localhost:${DEFAULT_LOCAL_GATEWAY_PORT}`;
    if (!url) return null;
    return buildGatewaySettings({
      adapterType: "openclaw",
      url,
      token,
      profiles: {
        openclaw: buildLocalProfile(url, token),
      },
    });
  } catch {
    return null;
  }
};

const normalizeAdapterType = (value: string | undefined): StudioGatewayAdapterType | null => {
  const normalized = value?.trim().toLowerCase();
  if (normalized === "openclaw" || normalized === "hermes" || normalized === "demo" || normalized === "custom") {
    return normalized;
  }
  return null;
};

const isTruthyEnvValue = (value: string | undefined) => {
  const normalized = value?.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
};

const readPortBasedGatewayProfile = (
  adapterType: Extract<StudioGatewayAdapterType, "hermes" | "demo">,
  envKey: "HERMES_ADAPTER_PORT" | "DEMO_ADAPTER_PORT"
): StudioGatewayProfile | null => {
  const rawPort = process.env[envKey]?.trim();
  if (!rawPort) return null;
  const port = Number.parseInt(rawPort, 10);
  if (!Number.isFinite(port) || port <= 0) return null;
  return buildLocalProfile(`ws://localhost:${port}`);
};

const buildImplicitDemoFallbackProfile = (
  openclawDefaults: StudioGatewaySettings | null
): StudioGatewayProfile | null => {
  if (!openclawDefaults) return null;
  const openclawUrl = openclawDefaults.url.trim();
  if (!openclawUrl) return null;
  try {
    const parsed = new URL(openclawUrl);
    const port = Number.parseInt(parsed.port || `${DEFAULT_LOCAL_GATEWAY_PORT}`, 10);
    if (port !== DEFAULT_LOCAL_GATEWAY_PORT) return null;
  } catch {
    return null;
  }
  return buildLocalProfile(`ws://localhost:${DEFAULT_DEMO_ADAPTER_FALLBACK_PORT}`);
};

const buildEnvGatewayDefaults = (
  openclawDefaults: StudioGatewaySettings | null = null
): StudioGatewaySettings | null => {
  const envUrl = process.env.CLAW3D_GATEWAY_URL?.trim();
  const envToken = process.env.CLAW3D_GATEWAY_TOKEN?.trim() ?? "";
  const envAdapterType =
    normalizeAdapterType(process.env.CLAW3D_GATEWAY_ADAPTER_TYPE) ?? "openclaw";

  const hermesProfile = readPortBasedGatewayProfile("hermes", "HERMES_ADAPTER_PORT");
  const demoProfile =
    readPortBasedGatewayProfile("demo", "DEMO_ADAPTER_PORT") ??
    buildImplicitDemoFallbackProfile(openclawDefaults);

  const profiles: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> = {};
  if (hermesProfile) profiles.hermes = hermesProfile;
  if (demoProfile) profiles.demo = demoProfile;

  if (envUrl) {
    profiles[envAdapterType] = buildLocalProfile(envUrl, envToken);
    return buildGatewaySettings({
      adapterType: envAdapterType,
      url: envUrl,
      token: envToken,
      profiles,
    });
  }

  const fallbackProfile = profiles.hermes ?? profiles.demo ?? null;
  if (!fallbackProfile) return null;
  const fallbackAdapterType = profiles.hermes ? "hermes" : "demo";
  return buildGatewaySettings({
    adapterType: fallbackAdapterType,
    url: fallbackProfile.url,
    token: fallbackProfile.token,
    profiles,
  });
};

const buildExplicitEnvGatewaySelection = (
  openclawDefaults: StudioGatewaySettings | null = null
): StudioGatewaySettings | null => {
  if (!isTruthyEnvValue(process.env[FORCE_SELECTION_ENV])) {
    return null;
  }

  const adapterType = normalizeAdapterType(process.env.CLAW3D_GATEWAY_ADAPTER_TYPE);
  if (!adapterType) {
    return null;
  }

  const envUrl = process.env.CLAW3D_GATEWAY_URL?.trim();
  const envToken = process.env.CLAW3D_GATEWAY_TOKEN?.trim() ?? "";
  if (envUrl) {
    return buildGatewaySettings({
      adapterType,
      url: envUrl,
      token: envToken,
      profiles: {
        [adapterType]: buildLocalProfile(envUrl, envToken),
      },
    });
  }

  if (adapterType === "openclaw") {
    const url = openclawDefaults?.url ?? `ws://localhost:${DEFAULT_LOCAL_GATEWAY_PORT}`;
    const token = openclawDefaults?.token ?? envToken;
    return buildGatewaySettings({
      adapterType,
      url,
      token,
      profiles: {
        openclaw: buildLocalProfile(url, token),
      },
    });
  }

  if (adapterType === "hermes") {
    const hermesProfile =
      readPortBasedGatewayProfile("hermes", "HERMES_ADAPTER_PORT") ??
      buildLocalProfile(`ws://localhost:${DEFAULT_LOCAL_GATEWAY_PORT}`);
    return buildGatewaySettings({
      adapterType,
      url: hermesProfile.url,
      token: hermesProfile.token,
      profiles: {
        hermes: hermesProfile,
      },
    });
  }

  if (adapterType === "demo") {
    const demoProfile =
      readPortBasedGatewayProfile("demo", "DEMO_ADAPTER_PORT") ??
      buildImplicitDemoFallbackProfile(openclawDefaults) ??
      buildLocalProfile(`ws://localhost:${DEFAULT_DEMO_ADAPTER_FALLBACK_PORT}`);
    return buildGatewaySettings({
      adapterType,
      url: demoProfile.url,
      token: demoProfile.token,
      profiles: {
        demo: demoProfile,
      },
    });
  }

  return buildGatewaySettings({
    adapterType,
    url: envUrl ?? DEFAULT_CUSTOM_GATEWAY_URL,
    token: envToken,
    profiles: {
      custom: buildLocalProfile(envUrl ?? DEFAULT_CUSTOM_GATEWAY_URL, envToken),
    },
  });
};

const repairLikelyOpenclawGatewaySelection = (
  gateway: StudioGatewaySettings,
  openclawDefaults: StudioGatewaySettings | null
): StudioGatewaySettings => {
  if (gateway.adapterType === "openclaw") {
    return gateway;
  }
  const persistedUrl = gateway.url.trim();
  const openclawUrl = openclawDefaults?.url.trim() ?? "";
  if (!persistedUrl || !openclawUrl || persistedUrl !== openclawUrl) {
    return gateway;
  }
  const persistedToken = gateway.token.trim();
  const openclawToken = openclawDefaults?.token.trim() ?? "";
  if (!persistedToken && !openclawToken) {
    return gateway;
  }
  const repairedLastKnownGood =
    gateway.lastKnownGood && gateway.lastKnownGood.url.trim() === openclawUrl
      ? {
          ...gateway.lastKnownGood,
          adapterType: "openclaw" as const,
          token: gateway.lastKnownGood.token.trim() || persistedToken || openclawToken,
        }
      : gateway.lastKnownGood;
  return {
    ...gateway,
    adapterType: "openclaw",
    token: persistedToken || openclawToken,
    ...(repairedLastKnownGood ? { lastKnownGood: repairedLastKnownGood } : {}),
  };
};

const mergeGatewayProfiles = (
  base: StudioGatewaySettings,
  extra: StudioGatewaySettings | null
): StudioGatewaySettings => {
  if (!extra?.profiles) {
    return base;
  }
  const mergedProfiles: Partial<Record<StudioGatewayAdapterType, StudioGatewayProfile>> = {
    ...(base.profiles ?? {}),
  };
  for (const [adapterType, profile] of Object.entries(extra.profiles) as Array<
    [StudioGatewayAdapterType, StudioGatewayProfile | undefined]
  >) {
    if (!profile || mergedProfiles[adapterType]) {
      continue;
    }
    mergedProfiles[adapterType] = profile;
  }
  return {
    ...base,
    profiles: mergedProfiles,
  };
};

const loadGatewayDefaultSources = () => {
  const fromFile = readOpenclawGatewayDefaults();
  const fromEnv = buildEnvGatewayDefaults(fromFile);
  const explicitEnv = buildExplicitEnvGatewaySelection(fromFile);
  return {
    merged: fromFile ? mergeGatewayProfiles(fromFile, fromEnv) : fromEnv,
    explicitEnv,
  };
};

export const loadLocalGatewayDefaults = (): StudioGatewaySettings | null => {
  const { merged } = loadGatewayDefaultSources();
  // Fall back to env vars so operators can configure the gateway URL at
  // runtime without openclaw.json and without a rebuild. If no explicit
  // URL is provided, also expose local Hermes/Demo adapter ports when set.
  return merged;
};

export const loadStudioSettings = (): StudioSettings => {
  const settingsPath = resolveStudioSettingsPath();
  const { merged: gatewayDefaults, explicitEnv } = loadGatewayDefaultSources();
  if (!fs.existsSync(settingsPath)) {
    const defaults = defaultStudioSettings();
    return gatewayDefaults ? { ...defaults, gateway: gatewayDefaults } : defaults;
  }
  const raw = stripUtf8Bom(fs.readFileSync(settingsPath, "utf8"));
  const parsed = JSON.parse(raw) as unknown;
  const settings = normalizeStudioSettings(parsed);
  const repairedGateway =
    settings.gateway && gatewayDefaults
      ? repairLikelyOpenclawGatewaySelection(settings.gateway, gatewayDefaults)
      : settings.gateway;
  if (!repairedGateway) {
    return gatewayDefaults ? { ...settings, gateway: gatewayDefaults } : settings;
  }
  return explicitEnv
    ? {
        ...settings,
        gateway: mergePersistedGatewaySettingsWithExplicitEnvOverride(
          repairedGateway,
          gatewayDefaults,
          explicitEnv
        ),
      }
    : gatewayDefaults
    ? {
        ...settings,
        gateway: mergePersistedGatewaySettingsWithDefaults(repairedGateway, gatewayDefaults),
      }
    : { ...settings, gateway: repairedGateway };
};

export const saveStudioSettings = (next: StudioSettings) => {
  const settingsPath = resolveStudioSettingsPath();
  const dir = path.dirname(settingsPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(settingsPath, JSON.stringify(next, null, 2), "utf8");
};

export const applyStudioSettingsPatch = (patch: StudioSettingsPatch): StudioSettings => {
  const current = loadStudioSettings();
  const next = mergeStudioSettings(current, patch);
  saveStudioSettings(next);
  return next;
};
