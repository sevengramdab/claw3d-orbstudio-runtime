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

## Run

1. Configure your environment:
   - copy `Claw3D-main/.env.example` to `Claw3D-main/.env`
   - update gateway and local settings as needed

2. Install dependencies:
   - Python: ensure Python 3.11+ is available
   - Node: install dependencies in `Claw3D-main/` if you plan to run the Next.js app

3. Launch the runtime:
   ```bash
   python LAUNCH_CLAW3D.py
   ```

This starts the Claw3D launch flow and OrbStudio support.

## GitHub Actions
A lightweight CI workflow is included at `.github/workflows/python-package.yml`.
It installs Python tooling and verifies syntax for all Python files in the repository.
