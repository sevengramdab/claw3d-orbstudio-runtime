const http = require("node:http");
const https = require("node:https");
const net = require("node:net");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const next = require("next");

const { createAccessGate } = require("./access-gate");
const { resolveManagedAdapterPort } = require("./adapter-port");
const { createGatewayProxy } = require("./gateway-proxy");
const { assertPublicHostAllowed, resolveHosts } = require("./network-policy");
const { loadUpstreamGatewaySettings, clearPersistedGatewaySettings } = require("./studio-settings");

const resolvePort = () => {
  const raw = process.env.PORT?.trim() || "3000";
  const port = Number(raw);
  if (!Number.isFinite(port) || port <= 0) return 3000;
  return port;
};

const resolvePathname = (url) => {
  const raw = typeof url === "string" ? url : "";
  const idx = raw.indexOf("?");
  return (idx === -1 ? raw : raw.slice(0, idx)) || "/";
};

const CERT_DIR = path.join(__dirname, "..", ".certs");
const CERT_PATH = path.join(CERT_DIR, "localhost.crt");
const KEY_PATH = path.join(CERT_DIR, "localhost.key");
const GATEWAY_PROXY_LOG_PATH = path.join(__dirname, "..", "outputs", "gateway_proxy.log");

const sanitizeLogChunk = (value) => {
  if (value instanceof Error) {
    return value.stack || value.message;
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const appendGatewayProxyLog = (entry) => {
  try {
    const line = JSON.stringify({
      timestamp: new Date().toISOString(),
      ...entry,
    });
    fs.mkdirSync(path.dirname(GATEWAY_PROXY_LOG_PATH), { recursive: true });
    fs.appendFileSync(GATEWAY_PROXY_LOG_PATH, `${line}\n`, "utf8");
  } catch {}
};

const generateHttpsCert = async () => {
  const fs = require("node:fs");

  // Re-use a saved cert so the browser only needs to trust it once.
  if (fs.existsSync(CERT_PATH) && fs.existsSync(KEY_PATH)) {
    return {
      key: fs.readFileSync(KEY_PATH, "utf8"),
      cert: fs.readFileSync(CERT_PATH, "utf8"),
    };
  }

  const selfsigned = require("selfsigned");
  const attrs = [{ name: "commonName", value: "localhost" }];
  const pems = await selfsigned.generate(attrs, {
    days: 825,
    keySize: 2048,
    algorithm: "sha256",
    extensions: [
      {
        name: "subjectAltName",
        altNames: [
          { type: 2, value: "localhost" },
          { type: 7, ip: "127.0.0.1" },
        ],
      },
    ],
  });

  fs.mkdirSync(CERT_DIR, { recursive: true });
  fs.writeFileSync(CERT_PATH, pems.cert);
  fs.writeFileSync(KEY_PATH, pems.private);

  console.info(`\nCert saved to ${CERT_DIR}`);
  console.info("To make browsers trust it (macOS), run:");
  console.info(`  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "${CERT_PATH}"\n`);

  return { key: pems.private, cert: pems.cert };
};

// ---------------------------------------------------------------------------
// Gateway adapter auto-start — spawn the correct adapter child process
// if no upstream is already listening on the target port.
// ---------------------------------------------------------------------------

const probePort = (port, host = "127.0.0.1", timeoutMs = 1500) =>
  new Promise((resolve) => {
    const socket = new net.Socket();
    const cleanup = () => { try { socket.destroy(); } catch {} };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => { cleanup(); resolve(true); });
    socket.once("timeout", () => { cleanup(); resolve(false); });
    socket.once("error", () => { cleanup(); resolve(false); });
    socket.connect(port, host);
  });

const ADAPTER_SCRIPTS = {
  hermes: require("node:path").join(__dirname, "hermes-gateway-adapter.js"),
  demo: require("node:path").join(__dirname, "demo-gateway-adapter.js"),
};

let adapterChildProcess = null;
let adapterRestartAttempts = 0;
const MAX_ADAPTER_RESTART_ATTEMPTS = 5;
const ADAPTER_RESTART_BASE_DELAY_MS = 2000;

const autoStartAdapter = async (adapterType) => {
  const script = ADAPTER_SCRIPTS[adapterType];
  if (!script) return; // openclaw / custom — don't auto-start
  const port = resolveManagedAdapterPort(adapterType, process.env);
  const adapterEnv = { ...process.env };
  if (adapterType === "hermes") {
    adapterEnv.HERMES_ADAPTER_PORT = String(port);
  } else if (adapterType === "demo") {
    adapterEnv.DEMO_ADAPTER_PORT = String(port);
  }

  const alreadyUp = await probePort(port);
  if (alreadyUp) {
    console.info(`[auto-start] ${adapterType} adapter already listening on port ${port}, skipping spawn.`);
    adapterRestartAttempts = 0; // Reset since something is healthy
    return;
  }

  console.info(`[auto-start] Spawning ${adapterType} adapter (port ${port})…`);
  const child = spawn(process.execPath, [script], {
    stdio: ["ignore", "pipe", "pipe"],
    env: adapterEnv,
    detached: false,
  });

  child.stdout.on("data", (chunk) => process.stdout.write(`[${adapterType}] ${chunk}`));
  child.stderr.on("data", (chunk) => process.stderr.write(`[${adapterType}] ${chunk}`));
  child.on("exit", (code) => {
    console.warn(`[auto-start] ${adapterType} adapter exited with code ${code}`);
    adapterChildProcess = null;

    // Auto-restart with capped exponential backoff
    if (code !== 0 && adapterRestartAttempts < MAX_ADAPTER_RESTART_ATTEMPTS) {
      adapterRestartAttempts++;
      const delay = ADAPTER_RESTART_BASE_DELAY_MS * Math.pow(1.5, adapterRestartAttempts - 1);
      console.info(
        `[auto-start] Scheduling ${adapterType} adapter restart (attempt ${adapterRestartAttempts}/${MAX_ADAPTER_RESTART_ATTEMPTS}) in ${Math.round(delay)}ms…`
      );
      setTimeout(() => {
        autoStartAdapter(adapterType).catch((err) => {
          console.error(`[auto-start] Failed to restart ${adapterType} adapter:`, err);
        });
      }, delay);
    } else if (adapterRestartAttempts >= MAX_ADAPTER_RESTART_ATTEMPTS) {
      console.error(
        `[auto-start] ${adapterType} adapter exhausted ${MAX_ADAPTER_RESTART_ATTEMPTS} restart attempts. Manual intervention required.`
      );
    }
  });
  adapterChildProcess = child;

  // Wait up to 8s for the adapter to start listening.
  for (let i = 0; i < 16; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await probePort(port)) {
      console.info(`[auto-start] ${adapterType} adapter is ready on port ${port}.`);
      adapterRestartAttempts = 0; // Reset on successful start
      return;
    }
  }
  console.warn(`[auto-start] ${adapterType} adapter did not become ready within 8s.`);
};

async function main() {
  // Load .env / .env.local BEFORE any adapter-start decisions — Next.js
  // normally defers this to app.prepare(), but we need the env vars earlier.
  try {
    require("@next/env").loadEnvConfig(require("node:path").join(__dirname, ".."));
  } catch {}

  const dev = process.argv.includes("--dev");
  const useHttps = process.argv.includes("--https") || process.env.HTTPS === "true";
  const hostnames = Array.from(new Set(resolveHosts(process.env)));
  const hostname = hostnames[0] ?? "127.0.0.1";
  const port = resolvePort();
  for (const host of hostnames) {
    assertPublicHostAllowed({
      host,
      studioAccessToken: process.env.STUDIO_ACCESS_TOKEN,
    });
  }

  const app = next({
    dev,
    hostname,
    port,
    ...(dev ? { webpack: true } : null),
  });
  const handle = app.getRequestHandler();

  // --- Auto-start gateway adapter if configured and not already running ---
  const initialSettings = loadUpstreamGatewaySettings(process.env);
  if (initialSettings.adapterType === "hermes" || initialSettings.adapterType === "demo") {
    await autoStartAdapter(initialSettings.adapterType);
  }

  const accessGate = createAccessGate({
    token: process.env.STUDIO_ACCESS_TOKEN,
  });

  const proxy = createGatewayProxy({
    loadUpstreamSettings: async () => {
      const settings = loadUpstreamGatewaySettings(process.env);
      return { url: settings.url, token: settings.token, adapterType: settings.adapterType };
    },
    log: (message) => {
      console.info(message);
      appendGatewayProxyLog({ level: "INFO", event: "proxy_log", message });
    },
    logError: (message, error) => {
      console.error(message, error);
      appendGatewayProxyLog({
        level: "ERROR",
        event: "proxy_error",
        message,
        details: sanitizeLogChunk(error),
      });
    },
    logEvent: (event, metadata = {}) => {
      appendGatewayProxyLog({
        level: "INFO",
        event,
        ...metadata,
      });
    },
    allowWs: (req) => {
      if (resolvePathname(req.url) !== "/api/gateway/ws") return false;
      return true;
    },
    verifyClient: (info) => accessGate.allowUpgrade(info.req),
  });

  await app.prepare();
  const handleUpgrade = app.getUpgradeHandler();
  const handleServerUpgrade = (req, socket, head) => {
    const pathname = resolvePathname(req.url);
    console.info(`[upgrade] ${pathname}`);
    if (pathname === "/api/gateway/ws") {
      proxy.handleUpgrade(req, socket, head);
      return;
    }
    handleUpgrade(req, socket, head);
  };

  const httpsCert = useHttps ? await generateHttpsCert() : null;

  const createServer = () =>
    useHttps
      ? https.createServer(httpsCert, (req, res) => {
          if (accessGate.handleHttp(req, res)) return;
          if (resolvePathname(req.url) === "/api/studio/reset-adapter" && req.method === "POST") {
            const cleared = clearPersistedGatewaySettings(process.env);
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ ok: true, cleared }));
            return;
          }
          handle(req, res);
        })
      : http.createServer((req, res) => {
          if (accessGate.handleHttp(req, res)) return;
          if (resolvePathname(req.url) === "/api/studio/reset-adapter" && req.method === "POST") {
            const cleared = clearPersistedGatewaySettings(process.env);
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ ok: true, cleared }));
            return;
          }
          handle(req, res);
        });

  const servers = hostnames.map(() => createServer());

  const attachUpgradeHandlers = (server) => {
    server.on("upgrade", handleServerUpgrade);
    server.on("newListener", (eventName, listener) => {
      if (eventName !== "upgrade") return;
      if (listener === handleServerUpgrade) return;
      process.nextTick(() => {
        server.removeListener("upgrade", listener);
      });
    });
  };

  for (const server of servers) {
    attachUpgradeHandlers(server);
  }

  const listenOnHost = (server, host) =>
    new Promise((resolve, reject) => {
      const onError = (err) => {
        server.off("error", onError);
        reject(err);
      };
      server.once("error", onError);
      server.listen(port, host, () => {
        server.off("error", onError);
        resolve();
      });
    });

  const closeServer = (server) =>
    new Promise((resolve) => {
      if (!server.listening) return resolve();
      server.close(() => resolve());
    });

  try {
    await Promise.all(servers.map((server, index) => listenOnHost(server, hostnames[index])));
  } catch (err) {
    await Promise.all(servers.map((server) => closeServer(server)));
    throw err;
  }

  const hostForBrowser = hostnames.some((value) => value === "127.0.0.1" || value === "::1")
    ? "localhost"
    : hostname === "0.0.0.0" || hostname === "::"
      ? "localhost"
      : hostname;

  const protocol = useHttps ? "https" : "http";
  const browserUrl = `${protocol}://${hostForBrowser}:${port}`;
  console.info(`Open in browser: ${browserUrl}`);
  if (useHttps) {
    console.info("HTTPS mode: self-signed cert in use. You may need to accept a browser security warning once.");
    console.info(`Spotify redirect URI: ${browserUrl}/office`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
