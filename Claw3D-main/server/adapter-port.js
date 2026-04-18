"use strict";

const ADAPTER_DEFAULT_PORTS = {
  hermes: 18789,
  demo: 18890,
};

const normalizePort = (value, fallback) => {
  const raw = String(value ?? "").trim();
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return parsed;
};

const resolveManagedAdapterPort = (adapterType, env = process.env) => {
  switch (adapterType) {
    case "hermes":
      return normalizePort(env.HERMES_ADAPTER_PORT, ADAPTER_DEFAULT_PORTS.hermes);
    case "demo":
      return normalizePort(env.DEMO_ADAPTER_PORT, ADAPTER_DEFAULT_PORTS.demo);
    default:
      return ADAPTER_DEFAULT_PORTS[adapterType] || ADAPTER_DEFAULT_PORTS.hermes;
  }
};

module.exports = {
  ADAPTER_DEFAULT_PORTS,
  resolveManagedAdapterPort,
};