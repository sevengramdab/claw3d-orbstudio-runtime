export const normalizeCustomBaseUrl = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol === "ws:") {
      parsed.protocol = "http:";
    } else if (parsed.protocol === "wss:") {
      parsed.protocol = "https:";
    }
    const normalizedPath = parsed.pathname.replace(/\/+$/, "");
    if (
      normalizedPath === "/v1" ||
      normalizedPath === "/api" ||
      normalizedPath === "/api/v1"
    ) {
      parsed.pathname = "";
    }
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return trimmed
      .replace(/\/(?:api\/v1|api|v1)\/?$/, "")
      .replace(/\/$/, "");
  }
};

type CustomRuntimeProxyInput = {
  runtimeUrl: string;
  pathname: string;
  method?: "GET" | "POST";
  body?: unknown;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === "object" && !Array.isArray(value));

const normalizeCustomRuntimePathnameCandidates = (pathname: string): string[] => {
  const normalized = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const candidates = new Set<string>([normalized]);

  if (normalized.startsWith("/v1/")) {
    candidates.add(normalized.replace(/^\/v1/, "/api/v1"));
  }
  if (normalized.startsWith("/api/v1/")) {
    candidates.add(normalized.replace(/^\/api\/v1/, "/v1"));
  }
  if (normalized === "/v1/chat/completions") {
    candidates.add("/api/v1/chat");
  }
  if (normalized === "/api/v1/chat") {
    candidates.add("/v1/chat/completions");
  }
  if (normalized === "/v1/chat") {
    candidates.add("/api/v1/chat");
  }
  if (normalized === "/api/v1/chat/completions") {
    candidates.add("/v1/chat");
  }

  return Array.from(candidates);
};

const buildLmStudioInput = (body: unknown): unknown => {
  if (!isRecord(body)) return body;
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const pieces: string[] = [];
  for (const entry of messages) {
    if (!isRecord(entry) || typeof entry.role !== "string" || typeof entry.content !== "string") {
      continue;
    }
    const role = entry.role.trim().toLowerCase();
    const text = entry.content.trim();
    if (!text) continue;
    if (role === "assistant") {
      pieces.push(`Assistant: ${text}`);
    } else if (role === "user") {
      pieces.push(`User: ${text}`);
    } else {
      pieces.push(`${role}: ${text}`);
    }
  }
  if (pieces.length === 0) return body;
  const result: Record<string, unknown> = {
    input: pieces.join("\n"),
  };
  if (typeof body.model === "string" && body.model.trim()) {
    result.model = body.model.trim();
  }
  if (typeof body.stream === "boolean") {
    result.stream = body.stream;
  }
  return result;
};

const tryRequestCustomRuntime = async <T = unknown>(
  runtimeUrl: string,
  pathname: string,
  method: "GET" | "POST",
  body?: unknown
): Promise<T> => {
  const normalizedRuntimeUrl = normalizeCustomBaseUrl(runtimeUrl);
  if (!normalizedRuntimeUrl) {
    throw new Error("Custom runtime URL is not configured.");
  }

  const pathnames = normalizeCustomRuntimePathnameCandidates(pathname);
  let lastError: Error | null = null;

  for (const candidate of pathnames) {
    try {
      const requestBody = candidate === "/api/v1/chat" ? buildLmStudioInput(body) : body;
      const response = await fetch("/api/runtime/custom", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        cache: "no-store",
        body: JSON.stringify({
          runtimeUrl: normalizedRuntimeUrl,
          pathname: candidate,
          method,
          body: requestBody,
        }),
      });

      if (!response.ok) {
        const text = await response.text();
        lastError = new Error(
          text.trim() || `Custom runtime request failed (${response.status}) for ${candidate}.`
        );
        continue;
      }

      return (await response.json()) as T;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }

  throw lastError ?? new Error(`Custom runtime request failed for ${pathname}.`);
};

export async function requestCustomRuntime<T = unknown>({
  runtimeUrl,
  pathname,
  method = "GET",
  body,
}: CustomRuntimeProxyInput): Promise<T> {
  return tryRequestCustomRuntime(runtimeUrl, pathname, method, body);
}

export async function fetchCustomRuntimeJson<T = unknown>(
  runtimeUrl: string,
  pathname: string
): Promise<T> {
  return requestCustomRuntime<T>({ runtimeUrl, pathname, method: "GET" });
}

export async function probeCustomRuntime(runtimeUrl: string): Promise<void> {
  try {
    await fetchCustomRuntimeJson(runtimeUrl, "/health");
    return;
  } catch (healthError) {
    try {
      const payload = await fetchCustomRuntimeJson<{ data?: Array<{ id?: unknown }> }>(
        runtimeUrl,
        "/v1/models"
      );
      if (Array.isArray(payload?.data)) {
        return;
      }
    } catch {
      // Fall through and rethrow the original health probe error.
    }
    throw healthError;
  }
}
