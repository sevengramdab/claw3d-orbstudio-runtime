# Gateway Connection Troubleshooting

## Quick Diagnostic

Open in browser: **http://localhost:3000/api/gateway/diagnose**

This shows live server-side health: env vars, port status, and adapter HTTP probes.

## Current Status (verified 2026-04-17)

| Component | Port | Status |
|-----------|------|--------|
| Claw3D Studio | 3000 | ✅ Running |
| Hermes Adapter | 18789 | ✅ Running |
| LM Studio | 1234 | ✅ Running |
| Demo Adapter | 18890 | ⬜ Not started |

Server-side chain verified: WS proxy → hermes handshake → `hello-ok` → `agents.list` all pass.

## If the browser is stuck loading

1. **Hard-refresh**: `Ctrl+Shift+R` (bypasses browser cache)
2. **Clear gateway state**: Open DevTools console → `localStorage.clear()` → reload
3. **Check browser console**: Look for `[gateway-client]` or `[gateway-browser]` log lines
4. **Restart dev server**:
   ```powershell
   cd "d:\claw source code\claw-code-parity\Claw3D-main"
   # Kill existing dev server
   Get-Process node | Where-Object { $_.StartTime -lt (Get-Date).AddMinutes(-5) } | Stop-Process -Force
   # Restart
   npm run dev
   ```

## Config files

- **`.env.local`**: `CLAW3D_GATEWAY_ADAPTER_TYPE=hermes`, `CLAW3D_GATEWAY_URL=ws://localhost:18789`
- **Settings**: `~/.openclaw/claw3d/settings.json` → gateway section has `adapterType: "hermes"`
- **Priority**: ENV vars override persisted settings; persisted settings override defaults

## Architecture

```
Browser ──WS──▶ :3000/api/gateway/ws (Next.js proxy)
                    │
                    ▼ findReachableUpstream() cascade
              :18789 hermes-gateway-adapter.js
                    │
                    ▼ model routing
              :1234 LM Studio (lmstudio/* models)
              Anthropic API (anthropic/* models)
              Ollama (ollama/* models)
```

## Known fixes applied

- **`.env.local`**: Changed from `custom`/`http://localhost:1234` to `hermes`/`ws://localhost:18789`
- **AgentsPageScreen token gate**: Fixed empty-token check that blocked hermes/demo adapters from showing the "Booting Studio" loading state (hermes doesn't use tokens)
- **Diagnostic endpoint**: Added `/api/gateway/diagnose` for server-side health checks
- **Connectivity script**: `scripts/check_hermes_connectivity.py` validates the full 5-stage chain
