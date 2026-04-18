import { NextResponse } from "next/server";
import net from "node:net";

const probePort = (port: number, host = "127.0.0.1", timeoutMs = 1500): Promise<boolean> =>
  new Promise((resolve) => {
    const socket = new net.Socket();
    const cleanup = () => { try { socket.destroy(); } catch { /* noop */ } };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => { cleanup(); resolve(true); });
    socket.once("timeout", () => { cleanup(); resolve(false); });
    socket.once("error", () => { cleanup(); resolve(false); });
    socket.connect(port, host);
  });

const httpProbe = async (url: string, timeoutMs = 3000): Promise<{ ok: boolean; body?: string; error?: string }> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal });
    const text = await res.text();
    return { ok: res.ok, body: text.slice(0, 200) };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    clearTimeout(timer);
  }
};

export async function GET() {
  const envAdapterType = process.env.CLAW3D_GATEWAY_ADAPTER_TYPE ?? "(unset)";
  const envGatewayUrl = process.env.CLAW3D_GATEWAY_URL ?? "(unset)";

  const [port3000, port18789, port18890, port1234] = await Promise.all([
    probePort(3000),
    probePort(18789),
    probePort(18890),
    probePort(1234),
  ]);

  const hermesHttp = port18789 ? await httpProbe("http://127.0.0.1:18789/") : null;
  const demoHttp = port18890 ? await httpProbe("http://127.0.0.1:18890/") : null;

  return NextResponse.json({
    timestamp: new Date().toISOString(),
    env: {
      CLAW3D_GATEWAY_ADAPTER_TYPE: envAdapterType,
      CLAW3D_GATEWAY_URL: envGatewayUrl,
      NODE_ENV: process.env.NODE_ENV ?? "(unset)",
    },
    ports: {
      "3000_studio": port3000,
      "18789_hermes": port18789,
      "18890_demo": port18890,
      "1234_lmstudio": port1234,
    },
    probes: {
      hermes: hermesHttp,
      demo: demoHttp,
    },
    hint: port18789 && hermesHttp?.ok
      ? "Hermes adapter is reachable. If the browser still can't connect, try: (1) hard-refresh the page (Ctrl+Shift+R), (2) clear localStorage, (3) restart the dev server."
      : "Hermes adapter is NOT reachable. Start it or check port 18789.",
  });
}
