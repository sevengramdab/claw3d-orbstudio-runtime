const { Buffer } = require("node:buffer");
const net = require("node:net");
const { WebSocket, WebSocketServer } = require("ws");

const DEFAULT_UPSTREAM_HANDSHAKE_TIMEOUT_MS = 10_000;

/** Maximum frame payload size (256 KB). */
const MAX_FRAME_SIZE = 256 * 1024;

/** Sustained frame rate per connection. */
const MAX_FRAMES_PER_SECOND = 60;

/** Allow short startup bursts before rate limiting. */
const MAX_FRAME_BURST = 120;

const buildErrorResponse = (id, code, message) => {
  return {
    type: "res",
    id,
    ok: false,
    error: { code, message },
  };
};

const isObject = (value) => Boolean(value && typeof value === "object");

const safeJsonParse = (raw) => {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
};

const sanitizeHeaders = (headers) => {
  const entries = Object.entries(headers || {});
  const sanitized = {};
  for (const [key, value] of entries) {
    const lower = key.toLowerCase();
    if (
      lower === "authorization" ||
      lower === "proxy-authorization" ||
      lower === "sec-websocket-key"
    ) {
      sanitized[key] = "<redacted>";
      continue;
    }
    sanitized[key] = Array.isArray(value) ? value.join(", ") : value;
  }
  return sanitized;
};

/** Per-connection token bucket rate limiter. */
const createFrameRateLimiter = (
  maxPerSecond = MAX_FRAMES_PER_SECOND,
  maxBurst = MAX_FRAME_BURST
) => {
  let tokens = maxBurst;
  let lastRefillAt = Date.now();

  const refill = () => {
    const now = Date.now();
    const elapsedMs = Math.max(0, now - lastRefillAt);
    if (elapsedMs <= 0) return;
    const replenished = (elapsedMs / 1000) * maxPerSecond;
    tokens = Math.min(maxBurst, tokens + replenished);
    lastRefillAt = now;
  };

  return {
    check() {
      refill();
      if (tokens < 1) {
        return false;
      }
      tokens -= 1;
      return true;
    },
    destroy() {
      // No-op: token bucket has no timers to clean up.
    },
  };
};

/**
 * Validate upstream URL against an allowlist.
 * If UPSTREAM_ALLOWLIST env var is set, only those hosts are permitted.
 * Format: comma-separated hostnames, e.g. "gateway.percival-labs.ai,localhost"
 */
const isUpstreamAllowed = (url) => {
  const allowlist = (process.env.UPSTREAM_ALLOWLIST || "").trim();
  if (!allowlist) {
    return process.env.NODE_ENV !== "production";
  }
  try {
    const parsed = new URL(url);
    const allowed = allowlist
      .split(",")
      .map((h) => h.trim().toLowerCase())
      .filter(Boolean);
    return allowed.includes(parsed.hostname.toLowerCase());
  } catch {
    return false;
  }
};

const resolvePathname = (url) => {
  const raw = typeof url === "string" ? url : "";
  const idx = raw.indexOf("?");
  return (idx === -1 ? raw : raw.slice(0, idx)) || "/";
};

const injectAuthToken = (params, token) => {
  const next = isObject(params) ? { ...params } : {};
  const auth = isObject(next.auth) ? { ...next.auth } : {};
  auth.token = token;
  next.auth = auth;
  return next;
};

/** Probe a TCP port to check if something is listening. */
const probePortQuick = (port, host = "127.0.0.1", timeoutMs = 800) =>
  new Promise((resolve) => {
    const socket = new net.Socket();
    const cleanup = () => { try { socket.destroy(); } catch {} };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => { cleanup(); resolve(true); });
    socket.once("timeout", () => { cleanup(); resolve(false); });
    socket.once("error", () => { cleanup(); resolve(false); });
    socket.connect(port, host);
  });

/**
 * HTTP health check — verify the adapter responds at the HTTP level, not
 * just that the TCP port is open.  The hermes and demo adapters both
 * respond with 200 on GET /.  Returns true if the server answers with a
 * 2xx status within *timeoutMs*.
 */
const probeHttpHealth = (port, host = "127.0.0.1", timeoutMs = 800) =>
  new Promise((resolve) => {
    const req = require("node:http").get(
      { hostname: host, port, path: "/", timeout: timeoutMs },
      (res) => {
        // Consume the body so the socket can be freed
        res.resume();
        resolve(res.statusCode >= 200 && res.statusCode < 300);
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });

/** Build fallback URL cascade: configured URL, then 18789, then 18890. */
const buildFallbackUrls = (primaryUrl) => {
  const urls = [primaryUrl];
  const seen = new Set([primaryUrl]);
  for (const port of [18789, 18890]) {
    const candidate = `ws://localhost:${port}`;
    if (!seen.has(candidate)) { urls.push(candidate); seen.add(candidate); }
  }
  return urls.filter(Boolean);
};

/** Try each fallback URL in order, return the first reachable one. */
const findReachableUpstream = async (primaryUrl, log) => {
  const candidates = buildFallbackUrls(primaryUrl);
  for (const url of candidates) {
    try {
      const parsed = new URL(url);
      const port = parseInt(parsed.port || "18789", 10);
      const host = parsed.hostname === "localhost" ? "127.0.0.1" : parsed.hostname;
      if (await probePortQuick(port, host)) {
        // TCP port is open — verify the adapter is actually healthy at HTTP level
        if (await probeHttpHealth(port, host)) {
          if (url !== primaryUrl) log(`[gateway-proxy] Primary ${primaryUrl} unreachable, falling back to ${url}`);
          return url;
        }
        log(`[gateway-proxy] Port ${port} is TCP-open but HTTP health check failed, skipping ${url}`);
      }
    } catch {}
  }
  return primaryUrl; // Return primary even if unreachable — let WS error propagate naturally
};

const resolveOriginForUpstream = (upstreamUrl) => {
  const url = new URL(upstreamUrl);
  const proto = url.protocol === "wss:" ? "https:" : "http:";
  const hostname =
    url.hostname === "127.0.0.1" || url.hostname === "::1" || url.hostname === "0.0.0.0"
      ? "localhost"
      : url.hostname;
  const host = url.port ? `${hostname}:${url.port}` : hostname;
  return `${proto}//${host}`;
};

const hasNonEmptyToken = (params) => {
  const raw = params && isObject(params) && isObject(params.auth) ? params.auth.token : "";
  return typeof raw === "string" && raw.trim().length > 0;
};

const hasNonEmptyPassword = (params) => {
  const raw = params && isObject(params) && isObject(params.auth) ? params.auth.password : "";
  return typeof raw === "string" && raw.trim().length > 0;
};

const hasNonEmptyDeviceToken = (params) => {
  const raw = params && isObject(params) && isObject(params.auth) ? params.auth.deviceToken : "";
  return typeof raw === "string" && raw.trim().length > 0;
};

const hasCompleteDeviceAuth = (params) => {
  const device = params && isObject(params) && isObject(params.device) ? params.device : null;
  if (!device) {
    return false;
  }
  const id = typeof device.id === "string" ? device.id.trim() : "";
  const publicKey = typeof device.publicKey === "string" ? device.publicKey.trim() : "";
  const signature = typeof device.signature === "string" ? device.signature.trim() : "";
  const nonce = typeof device.nonce === "string" ? device.nonce.trim() : "";
  const signedAt = device.signedAt;
  return (
    id.length > 0 &&
    publicKey.length > 0 &&
    signature.length > 0 &&
    nonce.length > 0 &&
    Number.isFinite(signedAt) &&
    signedAt >= 0
  );
};

function createGatewayProxy(options) {
  const {
    loadUpstreamSettings,
    allowWs = (req) => resolvePathname(req.url) === "/api/gateway/ws",
    log = () => {},
    logError = (msg, err) => console.error(msg, err),
    logEvent = () => {},
    upstreamHandshakeTimeoutMs = DEFAULT_UPSTREAM_HANDSHAKE_TIMEOUT_MS,
  } = options || {};

  const { verifyClient } = options || {};

  if (typeof loadUpstreamSettings !== "function") {
    throw new Error("createGatewayProxy requires loadUpstreamSettings().");
  }

  const wss = new WebSocketServer({ noServer: true, verifyClient });

  wss.on("connection", (browserWs, browserReq) => {
    let upstreamWs = null;
    let upstreamReady = false;
    let upstreamUrl = "";
    let upstreamToken = "";
    let upstreamAdapterType = "openclaw";
    let connectRequestId = null;
    let connectResponseSent = false;
    let pendingConnectFrame = null;
    let pendingUpstreamSetupError = null;
    let closed = false;
    const frameRateLimiter = createFrameRateLimiter();
    let upstreamHandshakeTimeoutId = null;
    const browserOrigin = String(browserReq?.headers?.origin || "").trim();
    const browserHost = String(browserReq?.headers?.host || "").trim();
    const browserPath = resolvePathname(browserReq?.url);

    logEvent("browser_ws_connected", {
      browserOrigin,
      browserHost,
      browserPath,
      browserHeaders: sanitizeHeaders(browserReq?.headers),
    });

    const closeBoth = (code, reason) => {
      if (closed) return;
      closed = true;
      frameRateLimiter.destroy();
      if (upstreamHandshakeTimeoutId !== null) {
        clearTimeout(upstreamHandshakeTimeoutId);
        upstreamHandshakeTimeoutId = null;
      }
      try {
        browserWs.close(code, reason);
      } catch {}
      try {
        upstreamWs?.close(code, reason);
      } catch {}
    };

    const sendToBrowser = (frame) => {
      if (browserWs.readyState !== WebSocket.OPEN) return;
      browserWs.send(JSON.stringify(frame));
    };

    const sendConnectError = (code, message) => {
      logEvent("connect_error", { code, message, connectRequestId });
      if (connectRequestId && !connectResponseSent) {
        connectResponseSent = true;
        sendToBrowser(buildErrorResponse(connectRequestId, code, message));
      }
      closeBoth(1011, "connect failed");
    };

    const forwardConnectFrame = (frame) => {
      const browserHasAuth =
        hasNonEmptyToken(frame.params) ||
        hasNonEmptyPassword(frame.params) ||
        hasNonEmptyDeviceToken(frame.params) ||
        hasCompleteDeviceAuth(frame.params);

      const requiresToken = upstreamAdapterType === "openclaw";
      if (requiresToken && !upstreamToken && !browserHasAuth) {
        sendConnectError(
          "studio.gateway_token_missing",
          "Upstream gateway token is not configured on the Studio host."
        );
        return;
      }

      const connectFrame = browserHasAuth
        ? frame
        : {
            ...frame,
            params: injectAuthToken(frame.params, upstreamToken),
          };
      logEvent("connect_frame_forwarded", {
        connectRequestId,
        upstreamUrl,
        upstreamAdapterType,
        browserOrigin,
        browserHost,
        hasToken: hasNonEmptyToken(connectFrame.params),
        hasDevice: hasCompleteDeviceAuth(connectFrame.params),
      });
      upstreamWs.send(JSON.stringify(connectFrame));
    };

    const maybeForwardPendingConnect = () => {
      if (!pendingConnectFrame || !upstreamReady || upstreamWs?.readyState !== WebSocket.OPEN) {
        return;
      }
      const frame = pendingConnectFrame;
      pendingConnectFrame = null;
      forwardConnectFrame(frame);
    };

    const startUpstream = async () => {
      try {
        const settings = await loadUpstreamSettings();
        upstreamUrl = typeof settings?.url === "string" ? settings.url.trim() : "";
        upstreamToken = typeof settings?.token === "string" ? settings.token.trim() : "";
        upstreamAdapterType =
          typeof settings?.adapterType === "string" && settings.adapterType.trim()
            ? settings.adapterType.trim().toLowerCase()
            : "openclaw";
        logEvent("upstream_settings_loaded", {
          upstreamUrl,
          upstreamAdapterType,
          hasToken: Boolean(upstreamToken),
        });
      } catch (err) {
        logError("Failed to load upstream gateway settings.", err);
        pendingUpstreamSetupError = {
          code: "studio.settings_load_failed",
          message: "Failed to load Studio gateway settings.",
        };
        return;
      }

      if (!upstreamUrl) {
        pendingUpstreamSetupError = {
          code: "studio.gateway_url_missing",
          message: "Upstream gateway URL is not configured on the Studio host.",
        };
        return;
      }

      // --- Fallback cascade: try configured URL, then 18789, then 18890 ---
      upstreamUrl = await findReachableUpstream(upstreamUrl, log);

      if (!isUpstreamAllowed(upstreamUrl)) {
        pendingUpstreamSetupError = {
          code: "studio.gateway_url_blocked",
          message: "Upstream gateway URL is not in the allowed hosts list.",
        };
        return;
      }

      let upstreamOrigin = "";
      try {
        upstreamOrigin = browserOrigin || resolveOriginForUpstream(upstreamUrl);
      } catch {
        pendingUpstreamSetupError = {
          code: "studio.gateway_url_invalid",
          message: "Upstream gateway URL is invalid on the Studio host.",
        };
        return;
      }

      const upstreamHeaders = {
        "x-claw3d-proxy": "1",
        "x-forwarded-host": browserHost,
        "x-forwarded-origin": browserOrigin,
        "x-forwarded-path": browserPath,
      };

      upstreamWs = new WebSocket(upstreamUrl, {
        origin: upstreamOrigin,
        headers: upstreamHeaders,
        handshakeTimeout: upstreamHandshakeTimeoutMs,
      });
      logEvent("upstream_connecting", {
        upstreamUrl,
        upstreamOrigin,
        upstreamAdapterType,
        browserOrigin,
        browserHost,
        browserPath,
        upstreamHeaders: sanitizeHeaders(upstreamHeaders),
      });

      log(
        `[gateway-proxy] upstream target=${upstreamUrl} origin=${upstreamOrigin || "(none)"} browserOrigin=${browserOrigin || "(none)"} browserHost=${browserHost || "(none)"} browserPath=${browserPath}`
      );

      upstreamHandshakeTimeoutId = setTimeout(() => {
        const timeoutError = {
          code: "studio.upstream_timeout",
          message: "Timed out connecting Studio to the upstream gateway WebSocket.",
        };
        logEvent("upstream_timeout", {
          upstreamUrl,
          upstreamAdapterType,
          timeoutMs: upstreamHandshakeTimeoutMs,
        });
        pendingUpstreamSetupError = timeoutError;
        try {
          upstreamWs?.terminate();
        } catch {}
        if (connectRequestId) {
          sendConnectError(timeoutError.code, timeoutError.message);
        }
      }, upstreamHandshakeTimeoutMs);

      upstreamWs.on("open", () => {
        if (upstreamHandshakeTimeoutId !== null) {
          clearTimeout(upstreamHandshakeTimeoutId);
          upstreamHandshakeTimeoutId = null;
        }
        upstreamReady = true;
        logEvent("upstream_open", { upstreamUrl, upstreamAdapterType });
        maybeForwardPendingConnect();
      });

      upstreamWs.on("unexpected-response", (_request, response) => {
        const statusCode = response?.statusCode || 0;
        const statusMessage = response?.statusMessage || "";
        const responseHeaders = sanitizeHeaders(response?.headers || {});
        log(
          `[gateway-proxy] upstream unexpected response status=${statusCode} message=${statusMessage || "(none)"}`
        );
        logEvent("upstream_unexpected_response", {
          upstreamUrl,
          upstreamAdapterType,
          statusCode,
          statusMessage,
          responseHeaders,
        });
      });

      upstreamWs.on("message", (upRaw) => {
        const upParsed = safeJsonParse(String(upRaw ?? ""));
        if (upParsed && isObject(upParsed) && upParsed.type === "res") {
          const resId = typeof upParsed.id === "string" ? upParsed.id : "";
          if (resId && connectRequestId && resId === connectRequestId) {
            connectResponseSent = true;
          }
        }
        if (browserWs.readyState === WebSocket.OPEN) {
          browserWs.send(String(upRaw ?? ""));
        }
      });

      upstreamWs.on("close", (code, reasonBuffer) => {
        if (upstreamHandshakeTimeoutId !== null) {
          clearTimeout(upstreamHandshakeTimeoutId);
          upstreamHandshakeTimeoutId = null;
        }
        const reason =
          typeof reasonBuffer === "string"
            ? reasonBuffer
            : Buffer.isBuffer(reasonBuffer)
              ? reasonBuffer.toString()
              : "";
        log(
          `[gateway-proxy] upstream closed code=${code} reason=${reason || "(none)"} hadConnect=${Boolean(connectRequestId)} responseSent=${connectResponseSent}`
        );
        logEvent("upstream_closed", {
          upstreamUrl,
          upstreamAdapterType,
          code,
          reason,
          hadConnect: Boolean(connectRequestId),
          responseSent: connectResponseSent,
        });
        if (!connectRequestId) {
          pendingUpstreamSetupError ||= {
            code: "studio.upstream_closed",
            message: `Upstream gateway closed (${code}): ${reason}`,
          };
          return;
        }
        if (!connectResponseSent && connectRequestId) {
          connectResponseSent = true;
          sendToBrowser(
            buildErrorResponse(
              connectRequestId,
              code === 1008 ? "studio.upstream_rejected" : "studio.upstream_closed",
              code === 1008
                ? `Upstream gateway rejected connect (${code}): ${reason || "no reason provided"}`
                : `Upstream gateway closed (${code}): ${reason}`
            )
          );
          return;
        }
        closeBoth(1012, "upstream closed");
      });

      upstreamWs.on("error", (err) => {
        if (upstreamHandshakeTimeoutId !== null) {
          clearTimeout(upstreamHandshakeTimeoutId);
          upstreamHandshakeTimeoutId = null;
        }
        logError("Upstream gateway WebSocket error.", err);
        logEvent("upstream_error", {
          upstreamUrl,
          upstreamAdapterType,
          error: err instanceof Error ? err.message : String(err),
        });
        if (!connectRequestId) {
          pendingUpstreamSetupError ||= {
            code: "studio.upstream_error",
            message: "Failed to connect to upstream gateway WebSocket.",
          };
          return;
        }
        if (
          pendingUpstreamSetupError?.code === "studio.upstream_timeout" &&
          pendingUpstreamSetupError?.message
        ) {
          sendConnectError(pendingUpstreamSetupError.code, pendingUpstreamSetupError.message);
          return;
        }
        sendConnectError(
          "studio.upstream_error",
          "Failed to connect to upstream gateway WebSocket."
        );
      });

      log("proxy connected");
      logEvent("proxy_connected", { upstreamUrl, upstreamAdapterType });
    };

    void startUpstream();

    browserWs.on("message", async (raw) => {
      const rawStr = String(raw ?? "");
      const rawByteLength = Buffer.byteLength(rawStr, "utf8");

      // Frame size limit
      if (rawByteLength > MAX_FRAME_SIZE) {
        closeBoth(1009, "frame too large");
        return;
      }

      // Rate limiting
      if (!frameRateLimiter.check()) {
        log(
          "[gateway-proxy] proxy rate limit hit (>" +
            MAX_FRAMES_PER_SECOND +
            " frames/s sustained, burst " +
            MAX_FRAME_BURST +
            ")"
        );
        closeBoth(1008, "rate limit exceeded");
        return;
      }

      const parsed = safeJsonParse(rawStr);
      if (!parsed || !isObject(parsed)) {
        closeBoth(1003, "invalid json");
        return;
      }

      if (!connectRequestId) {
        if (parsed.type !== "req" || parsed.method !== "connect") {
          closeBoth(1008, "connect required");
          return;
        }
        const id = typeof parsed.id === "string" ? parsed.id : "";
        if (!id) {
          closeBoth(1008, "connect id required");
          return;
        }
        connectRequestId = id;
        const params = isObject(parsed.params) ? parsed.params : null;
        const client = params && isObject(params.client) ? params.client : null;
        log(
          `[gateway-proxy] connect frame client.id=${
            typeof client?.id === "string" ? client.id : "n/a"
          } client.mode=${
            typeof client?.mode === "string" ? client.mode : "n/a"
          } hasToken=${hasNonEmptyToken(params)} hasDevice=${hasCompleteDeviceAuth(params)}`
        );
        logEvent("connect_frame", {
          clientId: typeof client?.id === "string" ? client.id : "n/a",
          clientMode: typeof client?.mode === "string" ? client.mode : "n/a",
          hasToken: hasNonEmptyToken(params),
          hasDevice: hasCompleteDeviceAuth(params),
          upstreamAdapterType,
        });
        if (pendingUpstreamSetupError) {
          sendConnectError(pendingUpstreamSetupError.code, pendingUpstreamSetupError.message);
          return;
        }
        pendingConnectFrame = parsed;
        maybeForwardPendingConnect();
        return;
      }

      if (!upstreamReady || upstreamWs.readyState !== WebSocket.OPEN) {
        closeBoth(1013, "upstream not ready");
        return;
      }

      if (parsed.type === "req" && parsed.method === "connect" && !connectResponseSent) {
        pendingConnectFrame = null;
        forwardConnectFrame(parsed);
        return;
      }

      upstreamWs.send(JSON.stringify(parsed));
    });

    browserWs.on("close", () => {
      log("[gateway-proxy] browser disconnected");
      logEvent("browser_disconnected", { connectRequestId, upstreamAdapterType });
      closeBoth(1000, "client closed");
    });

    browserWs.on("error", (err) => {
      logError("Browser WebSocket error.", err);
      logEvent("browser_error", {
        upstreamAdapterType,
        error: err instanceof Error ? err.message : String(err),
      });
      closeBoth(1011, "client error");
    });
  });

  const handleUpgrade = (req, socket, head) => {
    if (!allowWs(req)) {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit("connection", ws, req);
    });
  };

  return { wss, handleUpgrade };
}

module.exports = { createGatewayProxy };
