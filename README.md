# Claw3D + OrbStudio Runtime Repository

This repository contains a clean runtime baseline for launching Claw3D with OrbStudio support.

Included:
- `LAUNCH_CLAW3D.py` — dedicated Claw3D launcher with Hermes/demo/backend selection and adapter reset logic
- `LAUNCH_ORBSTUDIO.py` — shared OrbStudio launcher helpers for browser launch, port handling, and dependency setup
- `Claw3D-main/` — Claw3D Next.js application and server runtime
- `scripts/` — diagnostics and full-circuit connectivity testers
- `tests/` — targeted launcher regression coverage
- `update_game_ini.py` — OrbStudio-related runtime helper

Excluded:
- local config files such as `.env` / `.env.local`
- generated artifacts and temporary build files
- runtime logs and machine-specific state

Use `Claw3D-main/.env.example` to configure local gateway settings before launching.
