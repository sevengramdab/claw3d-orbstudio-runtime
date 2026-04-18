from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import shutil as shutil_module
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple

import numpy as np

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
    import uvicorn

    FASTAPI_AVAILABLE = True
except Exception:
    FastAPI = Any  # type: ignore[assignment]
    WebSocket = Any  # type: ignore[assignment]
    WebSocketDisconnect = Exception  # type: ignore[assignment]
    FileResponse = None  # type: ignore[assignment]
    HTMLResponse = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
    uvicorn = None  # type: ignore[assignment]
    FASTAPI_AVAILABLE = False

try:
    from src.auto_dj import ComfyUIClient
except Exception:
    ComfyUIClient = None  # type: ignore[assignment]

try:
    from src.comfyui_launcher import launch_comfyui
except Exception:
    launch_comfyui = None  # type: ignore[assignment]

try:
    from src.comfyui_launcher import ComfyUiLaunchConfig, is_comfyui_ready
except Exception:
    ComfyUiLaunchConfig = None  # type: ignore[assignment]
    is_comfyui_ready = None  # type: ignore[assignment]

# ==============================================================================
# ORBSTUDIO PHASE 1: THE SUBTERRANEAN IGNITION
# ARCHITECTURE: LEAD SYSTEM ENGINEER / STUDIO WILDCARD STANDARD
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [ORBSTUDIO_SYS] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ORBSTUDIO_PIXEL_ENGINE_ROOT = Path(__file__).resolve().parent / "orbstudio_pixel_engine"
ORBSTUDIO_PIXEL_ENGINE_DIST = ORBSTUDIO_PIXEL_ENGINE_ROOT / "dist"
ORBSTUDIO_PIXEL_ENGINE_WEB = ORBSTUDIO_PIXEL_ENGINE_ROOT / "web"
ROOM_GRID_WIDTH = 4
ROOM_GRID_START_ROWS = 4
ORBSTUDIO_CHATLOG_NAME = "ORBSTUDIO_CHATLOG.jsonl"

ROOM_STYLE_SPECS: Dict[str, Dict[str, str]] = {
    "reactor": {
        "title": "Reactor Bay",
        "style": "biolum reactor noir",
        "prompt": "cinematic fallout shelter reactor room concept art, teal fusion glow, brass catwalks, layered machinery walls, moody industrial vault interior",
    },
    "foundry": {
        "title": "Forge Deck",
        "style": "smelt-industrial bronze",
        "prompt": "cinematic underground foundry room concept art, bronze furnaces, hot riveted steel, orange forge glow, fallout shelter style industrial vault bay",
    },
    "hydro": {
        "title": "Hydro Garden",
        "style": "verdant synth-botanical",
        "prompt": "lush hydroponics vault room concept art, suspended planters, green grow lights, retro-futurist shelter agriculture bay, cinematic layered interior",
    },
    "archive": {
        "title": "Signal Archive",
        "style": "neon archive lounge",
        "prompt": "retro-futurist archive room concept art, violet data stacks, holographic consoles, library vault interior, cinematic shelter management game style",
    },
    "command": {
        "title": "Command Nest",
        "style": "navy command panoramic",
        "prompt": "vault command center concept art, blue tactical monitors, panoramic overseer deck, metallic control room, cinematic shelter strategy game interior",
    },
    "transit": {
        "title": "Transit Tube",
        "style": "stainless transit spine",
        "prompt": "retro-futurist transit tunnel concept art, stainless corridor, pressure doors, ladder shaft junction, clean metallic fallout shelter passageway",
    },
}

ORBSTUDIO_ROOM_BLUEPRINTS: List[Dict[str, Any]] = [
    {
        "title": "Reactor Core",
        "theme": "reactor",
        "style": "fusion manifold",
        "detail": "Thermal pressure, coolant bleed, and burn-stack pacing.",
        "lanes": ["steam", "load", "coolant"],
        "terminals": ["Core HUD", "Valve Tree"],
        "intake": "token heat",
        "output": "steam bus",
    },
    {
        "title": "Queue Switchyard",
        "theme": "transit",
        "style": "priority rail",
        "detail": "Jobs enter here, split by urgency, and leave on timed dispatch lanes.",
        "lanes": ["inbox", "priority", "dispatch"],
        "terminals": ["Queue Scope", "Latch Bank"],
        "intake": "queued work",
        "output": "crew paths",
    },
    {
        "title": "Prompt Relay",
        "theme": "command",
        "style": "syntax command",
        "detail": "Intent parsing, route rules, and operator overrides share the same switchboard.",
        "lanes": ["intent", "parse", "route"],
        "terminals": ["Syntax CRT", "Policy Wheel"],
        "intake": "prompt lines",
        "output": "task routes",
    },
    {
        "title": "Signal Archive",
        "theme": "archive",
        "style": "neon trace vault",
        "detail": "Logs, telemetry replays, and tape-index lookups stay browsable from one room.",
        "lanes": ["logs", "replay", "lookup"],
        "terminals": ["Tape Stack", "Trace Index"],
        "intake": "telemetry",
        "output": "audit trace",
    },
    {
        "title": "Patch Foundry",
        "theme": "foundry",
        "style": "rivet forge",
        "detail": "Diffs are heated, hammered, and sealed before the line moves forward.",
        "lanes": ["diff", "patch", "seal"],
        "terminals": ["Forge Bench", "Rivet Press"],
        "intake": "source deltas",
        "output": "patched state",
    },
    {
        "title": "Boiler Watch",
        "theme": "reactor",
        "style": "watchtower thermal",
        "detail": "Warning bands, trip causes, and flashover risk stay visible at a glance.",
        "lanes": ["pressure", "risk", "trip"],
        "terminals": ["Gauge Rail", "Watch Bell"],
        "intake": "heat alerts",
        "output": "reroute orders",
    },
    {
        "title": "Agent Barracks",
        "theme": "hydro",
        "style": "crew greenhouse",
        "detail": "Crew stamina, carry lanes, and return paths are staged in green-lit berths.",
        "lanes": ["crew", "carry", "return"],
        "terminals": ["Roster Board", "Locker Mesh"],
        "intake": "crew state",
        "output": "active patrols",
    },
    {
        "title": "Tool Relay",
        "theme": "command",
        "style": "operator bus",
        "detail": "File tools, shell calls, and API routes fan through a guarded relay spine.",
        "lanes": ["file", "shell", "api"],
        "terminals": ["Toolbus CRT", "Permit Gate"],
        "intake": "tool calls",
        "output": "side effects",
    },
    {
        "title": "Memory Loom",
        "theme": "archive",
        "style": "context jacquard",
        "detail": "Persistent notes, replay threads, and recent commands weave into operator recall.",
        "lanes": ["context", "recall", "thread"],
        "terminals": ["Recall Shelf", "Session Loom"],
        "intake": "memory frames",
        "output": "restored state",
    },
    {
        "title": "Wireworks",
        "theme": "foundry",
        "style": "copper dagworks",
        "detail": "Signal edges, mux lanes, and path reservations are soldered into one graph room.",
        "lanes": ["dag", "edges", "mux"],
        "terminals": ["Copper Rack", "Mux Plate"],
        "intake": "signal paths",
        "output": "wired lanes",
    },
    {
        "title": "Cooling Garden",
        "theme": "hydro",
        "style": "bleed nursery",
        "detail": "Cooldown loops and reset drains soften the boiler before it can spike again.",
        "lanes": ["drain", "bleed", "reset"],
        "terminals": ["Bleed Map", "Reset Mesh"],
        "intake": "spent heat",
        "output": "stable load",
    },
    {
        "title": "Transit Spine",
        "theme": "transit",
        "style": "junction spine",
        "detail": "Room-to-room hallways, ladder shafts, and token buses meet at this junction.",
        "lanes": ["north", "east", "south"],
        "terminals": ["Junction Board", "Lift Timer"],
        "intake": "cross-room flow",
        "output": "handoff lanes",
    },
    {
        "title": "Fault Chapel",
        "theme": "archive",
        "style": "warning reliquary",
        "detail": "Incidents are acknowledged, muted, or escalated beneath warning glass and tape light.",
        "lanes": ["ack", "mute", "escalate"],
        "terminals": ["Fault Ledger", "Alarm Prism"],
        "intake": "fault rack",
        "output": "operator focus",
    },
    {
        "title": "Ops Deck",
        "theme": "command",
        "style": "camera bridge",
        "detail": "Agent follow cams, zoom locks, and overseer framing all route through this deck.",
        "lanes": ["observe", "track", "focus"],
        "terminals": ["Camera Bridge", "Focus Dial"],
        "intake": "agent motion",
        "output": "camera state",
    },
    {
        "title": "Output Vault",
        "theme": "foundry",
        "style": "delivery kiln",
        "detail": "Rendered payloads, reports, and finished work are stamped before release.",
        "lanes": ["render", "persist", "ship"],
        "terminals": ["Stamp Press", "Release Gate"],
        "intake": "finished jobs",
        "output": "deliverables",
    },
    {
        "title": "Backup Catacomb",
        "theme": "transit",
        "style": "shadow vault",
        "detail": "Cold storage, mirrored state, and fallback launcher paths live below the line.",
        "lanes": ["shadow", "mirror", "cold"],
        "terminals": ["Vault Key", "Mirror Shelf"],
        "intake": "saved state",
        "output": "recovery path",
    },
]


def pixel_engine_theme_presets() -> List[Dict[str, str]]:
    return [
        {
            "id": "fallout_shelter",
            "title": "Fallout Shelter",
            "vibe": "vault-management cutaway with brass machinery and reactive telemetry",
        },
        {
            "id": "morrowind_cavern",
            "title": "Morrowind Cavern",
            "vibe": "wandering excavation paths, carved chambers, and lamp-lit underworks",
        },
        {
            "id": "seattle_underground",
            "title": "Seattle Underground",
            "vibe": "brick service tunnels, relays, and signal wires under the street grid",
        },
    ]


def _pixel_engine_asset(asset_path: str) -> Optional[Path]:
    normalized = PurePosixPath(asset_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        return None

    for root in (ORBSTUDIO_PIXEL_ENGINE_DIST, ORBSTUDIO_PIXEL_ENGINE_WEB):
        candidate = (root / normalized).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def build_pixel_engine_preview_html() -> str:
    theme_cards = "".join(
        f"<li><strong>{theme['title']}</strong><span>{theme['vibe']}</span></li>"
        for theme in pixel_engine_theme_presets()
    )
    return f"""
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>ORBSTUDIO Pixel Engine</title>
  <style>
    body{{margin:0;padding:32px;background:linear-gradient(180deg,#07131b,#03070a);color:#dffcff;font-family:'Trebuchet MS','Segoe UI',sans-serif}}
    main{{max-width:960px;margin:0 auto;padding:24px;border:1px solid rgba(109,245,255,.24);border-radius:18px;background:linear-gradient(180deg,rgba(12,32,42,.94),rgba(6,14,18,.98))}}
    h1{{margin:0 0 12px;color:#6df5ff;letter-spacing:.08em;text-transform:uppercase}}
    p{{color:rgba(223,252,255,.8);line-height:1.55}}
    code{{color:#f5c96b}}
    ul{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;padding:0;list-style:none;margin:24px 0 0}}
    li{{padding:16px;border-radius:14px;border:1px solid rgba(109,245,255,.16);background:rgba(8,21,28,.84)}}
    strong{{display:block;margin-bottom:8px;color:#f4fdff;text-transform:uppercase;letter-spacing:.08em}}
    span{{display:block;color:rgba(223,252,255,.74)}}
  </style>
</head>
<body>
  <main>
    <h1>ORBSTUDIO Pixel Engine</h1>
    <p>Live runtime remains rooted in <code>update_game_ini.py</code>. This preview route keeps the themed direction visible while the active vault renderer evolves.</p>
    <p>Workspace surface: <code>{ORBSTUDIO_PIXEL_ENGINE_ROOT.name}/</code></p>
    <ul>{theme_cards}</ul>
  </main>
</body>
</html>
"""


# ELI5: This is our electrical plug standard. Every model adapter has to fit this
# socket so the foreman can swap between cloud power and the local generator.
class AgentModel(Protocol):
    async def execute_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...


# ELI5: This is the brass pressure gauge on the boiler face. When token traffic
# rises too high, the needle pegs red and the firebox is treated like a trip event.
@dataclass
class ThermalPressureGauge:
    current_load: int = 0
    burst_limit: int = 10000
    is_tripped: bool = False
    token_velocity: float = 0.2
    last_trip_reason: str = "nominal"

    # ELI5: Adding load here is like putting more amperage on a shop circuit.
    # Too much demand causes voltage sag first, then the breaker snaps open.
    def add_pressure(self, amount: int, task_id: str = "UNKNOWN") -> None:
        self.current_load += amount
        self.token_velocity = max(0.25, min(6.0, amount / 900.0))
        if self.current_load >= self.burst_limit:
            self.is_tripped = True
            self.last_trip_reason = f"THERMAL FLASHOVER DURING {task_id}"
            logger.warning("CRITICAL: MAIN BREAKER TRIPPED! THERMAL RUNAWAY IMMINENT.")

    # ELI5: This is the cooldown radiator. It bleeds heat and pressure off the line
    # so the boiler can settle back into a safe operating band.
    def bleed_off(self, amount: int) -> None:
        self.current_load = max(0, self.current_load - amount)
        self.token_velocity = max(0.15, self.token_velocity * 0.86)
        if self.current_load <= int(self.burst_limit * 0.45):
            self.is_tripped = False
            self.last_trip_reason = "pressure normalized"


# ELI5: This function handles the mandatory "Save Point" before we alter any
# physical architecture. Think of it as copying your original vellum blueprint
# to a safe before you start drawing new HVAC lines on it.
def execute_ark_backup_protocol() -> None:
    """Mandatory backup sequence for Game.ini and GameUserSettings.ini."""
    logger.info("INITIATING: Ark File Backup Protocol...")

    # ELI5: We set our clock to Pacific Time. This is the master timecode
    # for our engineering site logs.
    pst = timezone(timedelta(hours=-8))
    timestamp = datetime.now(pst).strftime("%Y-%m-%d_%H%M_PST")

    # ELI5: Establishing the physical filing cabinet for the backups.
    backup_dir = os.path.join("E:\\", "ark_backups")
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        logger.info(f"Constructed new backup archive vault at: {backup_dir}")

    files_to_backup = ["Game.ini", "GameUserSettings.ini"]
    target_dir = os.path.join(os.getcwd(), "ShooterGame", "Saved", "Config", "WindowsServer")

    for file in files_to_backup:
        src = os.path.join(target_dir, file)
        if os.path.exists(src):
            dst = os.path.join(backup_dir, f"{timestamp}_{file}")
            # ELI5: This is the physical act of running the vellum through the copier.
            shutil.copy2(src, dst)
            logger.info(f"SUCCESS: Hard-copied {file} to Vault -> {dst}")
        else:
            logger.info(f"BYPASS: {file} not found in active directory. Skipping.")


# ELI5: If the building does not have a real E: filing cabinet, the SITK rolls in a
# temporary labeled one so the locked copier routine can still file to the expected bay.
def ensure_backup_vault_available() -> None:
    if os.name != "nt" or os.path.exists("E:\\"):
        return

    shadow_vault = Path.cwd() / "outputs" / "orbstudio" / "E_drive_shadow"
    shadow_vault.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            ["subst", "E:", str(shadow_vault)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and os.path.exists("E:\\"):
            logger.info("Provisioned virtual E: backup vault at %s", shadow_vault)
        else:
            logger.warning(
                "Unable to provision virtual E: drive automatically. Backup may require a real E: volume. %s",
                (result.stderr or "").strip(),
            )
    except FileNotFoundError:
        logger.warning("SUBST command unavailable. A real E: backup volume is required for the locked backup routine.")


# ELI5: This is the config drafting table. It patches Game.ini like a careful revision cloud
# on an engineering drawing: one clean change set, no duplicate notes, and a rollback copy nearby.
class GameIniOperator:
    PHASE2_SECTION = "[/Script/ShooterGame.ShooterGameMode]"
    PHASE2_LINES = [
        "Phase2SITKEnabled=True",
        "BoilerWatchdog=True",
        "TeleprinterSidecarPort=8765",
        "LocalBypassGovernorPort=1234",
        "AGDDispatchMode=Balanced",
    ]

    def __init__(self, config_root: Optional[Path | str] = None):
        if config_root is None:
            self.config_root = Path.cwd() / "ShooterGame" / "Saved" / "Config" / "WindowsServer"
        else:
            self.config_root = Path(config_root)
        self.game_ini_path = self.config_root / "Game.ini"
        self.rollback_path = self.config_root / "Game.ini.phase2.rollback.bak"
        self.manifest_path = self.config_root / "phase2_manifest.json"

    # ELI5: This ensures the drafting folder and sheet exist before we try to stamp the revision block.
    def _ensure_paths(self) -> None:
        self.config_root.mkdir(parents=True, exist_ok=True)
        if not self.game_ini_path.exists():
            self.game_ini_path.write_text(self.PHASE2_SECTION + "\n", encoding="utf-8")

    # ELI5: This applies the Phase 2 notes once and only once, like an idempotent CAD layer update.
    def apply_phase2_patch(self) -> Dict[str, Any]:
        self._ensure_paths()
        original = self.game_ini_path.read_text(encoding="utf-8")
        updated_text = original
        updated = False

        if self.PHASE2_SECTION not in updated_text:
            updated_text = updated_text.rstrip() + "\n\n" + self.PHASE2_SECTION + "\n"
            updated = True

        if not self.rollback_path.exists():
            self.rollback_path.write_text(original, encoding="utf-8")

        section_index = updated_text.find(self.PHASE2_SECTION)
        section_body = updated_text[section_index:]
        missing_lines = [line for line in self.PHASE2_LINES if line not in section_body]
        if missing_lines:
            insertion = "\n".join(missing_lines) + "\n"
            updated_text = updated_text.rstrip() + "\n" + insertion
            updated = True

        if updated:
            self.game_ini_path.write_text(updated_text, encoding="utf-8")

        manifest = {
            "updated": updated,
            "game_ini_path": str(self.game_ini_path),
            "rollback_path": str(self.rollback_path),
            "manifest_path": str(self.manifest_path),
            "phase2_lines": list(self.PHASE2_LINES),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    # ELI5: This rolls the config sheet back to the last safe revision if the foreman wants to undo the patch.
    def rollback_phase2_patch(self) -> Dict[str, Any]:
        if not self.rollback_path.exists():
            return {"rolled_back": False, "reason": "no rollback file present"}
        self._ensure_paths()
        shutil.copy2(self.rollback_path, self.game_ini_path)
        return {
            "rolled_back": True,
            "game_ini_path": str(self.game_ini_path),
            "rollback_path": str(self.rollback_path),
        }


# ELI5: This is the commissioning clipboard for the whole toolkit. It checks whether
# the workshop has the right breakers, tools, and launch buttons before the crew clocks in.
class BootstrapDiagnostics:
    def __init__(self, workspace_root: Optional[Path | str] = None):
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        self.output_dir = self.workspace_root / "outputs" / "orbstudio"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_path = self.output_dir / "bootstrap_report.json"
        self.launcher_path = self.output_dir / "launch_orbstudio_phase6.bat"

    # ELI5: This is the preflight inspector walking the shop floor to confirm power,
    # parts, and hand tools are ready before a machine startup.
    def collect(self) -> Dict[str, Any]:
        dependencies = {
            "python": {
                "available": True,
                "version": sys.version.split()[0],
                "executable": sys.executable,
            },
            "fastapi": {"available": FASTAPI_AVAILABLE},
            "uvicorn": {"available": uvicorn is not None},
            "numpy": {"available": np is not None},
            "subst": {"available": shutil_module.which("subst") is not None},
        }
        paths = {
            "workspace_root": str(self.workspace_root),
            "outputs_dir": str(self.output_dir),
            "game_ini_dir": str(self.workspace_root / "ShooterGame" / "Saved" / "Config" / "WindowsServer"),
        }
        launcher_preview = f'@echo off\r\ncd /d "{self.workspace_root}"\r\n"{sys.executable}" update_game_ini.py --serve --apply-phase2-config --bootstrap-report\r\n'
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dependencies": dependencies,
            "paths": paths,
            "launcher_preview": launcher_preview,
        }

    # ELI5: This writes the commissioning paperwork and a one-click starter button,
    # like hanging a laminated startup sheet beside the main breaker.
    def generate_report(self) -> Dict[str, Any]:
        payload = self.collect()
        self.report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.launcher_path.write_text(payload["launcher_preview"], encoding="utf-8")
        payload["report_path"] = str(self.report_path)
        payload["launcher_path"] = str(self.launcher_path)
        return payload


# ELI5: This is our AutoCAD-style model space. The rock grid is split into layers:
# solid rock is 0, tunnel is 1, and wider chamber nodes are 2 for branching pockets.
class CaveSpatialHash:
    def __init__(self, width: int = 1024, height: int = 1024, cell_size: int = 32):
        self.cell_size = cell_size
        self.grid_width = max(4, width // cell_size)
        self.grid_height = max(4, height // cell_size)
        self.cave_matrix = np.zeros((self.grid_height, self.grid_width), dtype=np.int8)
        self.agent_cells: Dict[str, Tuple[int, int]] = {}
        self.agent_layer = np.full((self.grid_height, self.grid_width), "", dtype=object)
        self.reserved_paths: Dict[str, List[Tuple[int, int]]] = {}
        self.reservation_expiry: Dict[str, float] = {}
        self.reservation_started_at: Dict[str, float] = {}
        logger.info("Initialized 2.5D Spatial Hash Matrix for Cave Generation.")

    # ELI5: This is the safety fence around the dig site so the tunnel machine never
    # drills past the blueprint sheet or into invalid coordinates.
    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.grid_width and 0 <= y < self.grid_height

    # ELI5: Carving a cell is like erasing one square of bedrock off the drafting plan.
    def carve_cell(self, x: int, y: int, value: int = 1) -> None:
        if self._in_bounds(x, y):
            self.cave_matrix[y, x] = value

    # ELI5: This makes a small service bay. In shop drawings, it is the bulb-out room
    # where a crew can turn around with tools and cable reels.
    def carve_room(self, center_x: int, center_y: int, radius: int = 1) -> None:
        for y in range(center_y - radius, center_y + radius + 1):
            for x in range(center_x - radius, center_x + radius + 1):
                self.carve_cell(x, y, value=2)

    # ELI5: This legacy straight cut stays available as a simple linear trench tool.
    def carve_tunnel(self, start_x: int, start_y: int, length: int) -> None:
        end_x = min(start_x + length, self.grid_width)
        self.cave_matrix[start_y, start_x:end_x] = 1
        logger.info(f"Excavated tunnel segment at Sector [{start_x}:{start_y}]")

    # ELI5: This is the Morrowind-style tunnel generator. It walks like a wandering
    # survey crew, making non-linear organic turns instead of one stiff hallway.
    def Generate_Morrowind_Layout(self, seed: Optional[int] = None, steps: int = 240) -> None:
        rng = random.Random(seed)
        x = self.grid_width // 2
        y = self.grid_height // 2
        self.carve_room(x, y, radius=1)

        for _ in range(max(8, steps)):
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
            stride = rng.randint(1, 3)
            for _ in range(stride):
                x = min(max(1, x + dx), self.grid_width - 2)
                y = min(max(1, y + dy), self.grid_height - 2)
                self.carve_cell(x, y, value=1)
            if rng.random() < 0.16:
                self.carve_room(x, y, radius=rng.randint(1, 2))

        logger.info("Morrowind layout generated with random-walk tunnel carving.")

    # ELI5: Open cells are the lit work lanes where AGDs are allowed to walk.
    def is_open_cell(self, x: int, y: int) -> bool:
        return self._in_bounds(x, y) and int(self.cave_matrix[y, x]) > 0

    # ELI5: This is the crew dispatcher finding the nearest open bay on the floorplan.
    def nearest_open_cell(self, x: int, y: int) -> Tuple[int, int]:
        if self.is_open_cell(x, y):
            return x, y
        for radius in range(1, max(self.grid_width, self.grid_height)):
            for ny in range(max(0, y - radius), min(self.grid_height, y + radius + 1)):
                for nx in range(max(0, x - radius), min(self.grid_width, x + radius + 1)):
                    if self.is_open_cell(nx, ny):
                        return nx, ny
        return self.grid_width // 2, self.grid_height // 2

    # ELI5: This is the occupancy chart on the dispatch wall. It tells us which bays are already
    # full so we do not try to park two rail crews in the same maintenance pocket.
    def occupied_cells(self, exclude_agent_id: Optional[str] = None) -> Set[Tuple[int, int]]:
        return {
            cell
            for agent_id, cell in self.agent_cells.items()
            if agent_id != exclude_agent_id
        }

    # ELI5: These are the chalk marks for future train movements. Reserved cells are treated
    # like temporarily blocked track so another crew does not plan through the same corridor.
    def reserved_cells(self, exclude_agent_id: Optional[str] = None) -> Set[Tuple[int, int]]:
        self.cleanup_expired_reservations()
        cells: Set[Tuple[int, int]] = set()
        for agent_id, path in self.reserved_paths.items():
            if agent_id == exclude_agent_id:
                continue
            cells.update(path)
        return cells

    # ELI5: This finds the nearest legal parking spot when the preferred bay is already occupied.
    def nearest_available_cell(self, x: int, y: int, exclude_agent_id: Optional[str] = None) -> Tuple[int, int]:
        blocked = self.occupied_cells(exclude_agent_id=exclude_agent_id)
        blocked.update(self.reserved_cells(exclude_agent_id=exclude_agent_id))
        if self.is_open_cell(x, y) and (x, y) not in blocked:
            return x, y
        for radius in range(1, max(self.grid_width, self.grid_height)):
            for ny in range(max(0, y - radius), min(self.grid_height, y + radius + 1)):
                for nx in range(max(0, x - radius), min(self.grid_width, x + radius + 1)):
                    if self.is_open_cell(nx, ny) and (nx, ny) not in blocked:
                        return nx, ny
        return self.nearest_open_cell(self.grid_width // 2, self.grid_height // 2)

    # ELI5: This is a simple track-routing planner. It lays out a short path through open,
    # unoccupied cells so one AGD can move without colliding into another parked crew.
    def plan_safe_steps(self, agent_id: str, target_x: int, target_y: int, step_limit: int = 24) -> List[Tuple[int, int]]:
        start = self.agent_cells.get(agent_id)
        if start is None:
            start = self.place_agent(agent_id)
        goal = self.nearest_available_cell(target_x, target_y, exclude_agent_id=agent_id)
        if start == goal:
            return []

        blocked = self.occupied_cells(exclude_agent_id=agent_id)
        blocked.update(self.reserved_cells(exclude_agent_id=agent_id))
        queue: List[Tuple[int, int]] = [start]
        came_from: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {start: None}
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        while queue:
            current = queue.pop(0)
            if current == goal:
                break
            for dx, dy in directions:
                nxt = (current[0] + dx, current[1] + dy)
                if nxt in came_from or nxt in blocked:
                    continue
                if not self.is_open_cell(nxt[0], nxt[1]):
                    continue
                came_from[nxt] = current
                queue.append(nxt)

        if goal not in came_from:
            return []

        cells: List[Tuple[int, int]] = []
        cursor: Optional[Tuple[int, int]] = goal
        while cursor and cursor != start:
            cells.append(cursor)
            cursor = came_from[cursor]
        cells.reverse()

        steps: List[Tuple[int, int]] = []
        prev = start
        for cell in cells[:step_limit]:
            steps.append((cell[0] - prev[0], cell[1] - prev[1]))
            prev = cell
        return steps

    # ELI5: This paints a temporary route on the dispatch map so later crews can see the lane is spoken for.
    def reserve_path(self, agent_id: str, steps: List[Tuple[int, int]], ttl_s: float = 30.0) -> List[Tuple[int, int]]:
        cursor = self.agent_cells.get(agent_id)
        if cursor is None:
            cursor = next(iter(self.agent_cells.values()), None)
        if cursor is None:
            cursor = self.place_agent(agent_id)
        reserved: List[Tuple[int, int]] = []
        for dx, dy in steps:
            cursor = (cursor[0] + dx, cursor[1] + dy)
            reserved.append(cursor)
        self.reserved_paths[agent_id] = reserved
        self.reservation_expiry[agent_id] = max(0.01, ttl_s)
        self.reservation_started_at[agent_id] = time.monotonic()
        return reserved

    # ELI5: These reservations are like temporary traffic cones. If a crew never shows up,
    # the cones have to be picked up so the corridor can be used again.
    def cleanup_expired_reservations(self, now: Optional[float] = None) -> None:
        expired: List[str] = []
        for agent_id, ttl_s in self.reservation_expiry.items():
            elapsed = now if now is not None else time.monotonic() - self.reservation_started_at.get(agent_id, 0.0)
            if elapsed >= ttl_s:
                expired.append(agent_id)
        for agent_id in expired:
            self.reserved_paths.pop(agent_id, None)
            self.reservation_expiry.pop(agent_id, None)
            self.reservation_started_at.pop(agent_id, None)

    # ELI5: This is the foreman's clipboard copy of all active corridor reservations.
    # It records the remaining cone time so a restart can rebuild the same blocked lanes.
    def serialize_reservations(self) -> Dict[str, Dict[str, Any]]:
        self.cleanup_expired_reservations()
        snapshot: Dict[str, Dict[str, Any]] = {}
        for agent_id, path in self.reserved_paths.items():
            ttl_s = float(self.reservation_expiry.get(agent_id, 0.0))
            started_at = float(self.reservation_started_at.get(agent_id, time.monotonic()))
            remaining_ttl = max(0.01, ttl_s - max(0.0, time.monotonic() - started_at))
            snapshot[agent_id] = {
                "path": [list(cell) for cell in path],
                "remaining_ttl": remaining_ttl,
            }
        return snapshot

    # ELI5: This redraws the active traffic cones after a restart so the same corridors stay reserved.
    def restore_reservations(self, payload: Dict[str, Dict[str, Any]]) -> None:
        self.reserved_paths.clear()
        self.reservation_expiry.clear()
        self.reservation_started_at.clear()
        now = time.monotonic()
        for agent_id, item in payload.items():
            path = [tuple(int(coord) for coord in cell) for cell in item.get("path", [])]
            if not path:
                continue
            remaining_ttl = max(0.01, float(item.get("remaining_ttl", 30.0)))
            self.reserved_paths[agent_id] = path
            self.reservation_expiry[agent_id] = remaining_ttl
            self.reservation_started_at[agent_id] = now

    # ELI5: This erases the chalk marks once the crew has moved through that segment.
    def consume_reserved_step(self, agent_id: str, cell: Tuple[int, int]) -> None:
        path = self.reserved_paths.get(agent_id)
        if not path:
            return
        if path and path[0] == cell:
            path.pop(0)
        else:
            self.reserved_paths[agent_id] = [item for item in path if item != cell]
        if not self.reserved_paths.get(agent_id):
            self.reserved_paths.pop(agent_id, None)
            self.reservation_expiry.pop(agent_id, None)
            self.reservation_started_at.pop(agent_id, None)

    # ELI5: This writes the worker badge number onto the floor grid so the foreman
    # always knows which AGD occupies which cell.
    def place_agent(self, agent_id: str, x: Optional[int] = None, y: Optional[int] = None) -> Tuple[int, int]:
        target_x = x if x is not None else self.grid_width // 2
        target_y = y if y is not None else self.grid_height // 2
        open_x, open_y = self.nearest_available_cell(target_x, target_y, exclude_agent_id=agent_id)

        old = self.agent_cells.get(agent_id)
        if old:
            self.agent_layer[old[1], old[0]] = ""

        self.agent_cells[agent_id] = (open_x, open_y)
        self.agent_layer[open_y, open_x] = agent_id
        return open_x, open_y

    # ELI5: This slides an AGD from one grid square to the next like moving a block
    # on an electrical ladder diagram.
    def move_agent(self, agent_id: str, dx: int, dy: int) -> Tuple[int, int]:
        cur_x, cur_y = self.agent_cells.get(agent_id, self.place_agent(agent_id))
        next_x, next_y = self.nearest_available_cell(cur_x + dx, cur_y + dy, exclude_agent_id=agent_id)
        self.agent_layer[cur_y, cur_x] = ""
        self.agent_cells[agent_id] = (next_x, next_y)
        self.agent_layer[next_y, next_x] = agent_id
        self.consume_reserved_step(agent_id, (next_x, next_y))
        return next_x, next_y

    # ELI5: This gives the dispatcher a quick radius check to see which crew is nearby.
    def query_nearby_agents(self, x: int, y: int, radius: int = 2) -> Dict[str, Tuple[int, int]]:
        return {
            agent_id: cell
            for agent_id, cell in self.agent_cells.items()
            if abs(cell[0] - x) <= radius and abs(cell[1] - y) <= radius
        }

    def _theme_palette(self) -> Dict[str, Dict[str, str]]:
        return {
            "reactor": {"base": "#4b4f2f", "accent": "#b6d05a", "shadow": "#1d2413"},
            "foundry": {"base": "#6f3a25", "accent": "#d99248", "shadow": "#2b140d"},
            "hydro": {"base": "#35543a", "accent": "#7ca66c", "shadow": "#162316"},
            "archive": {"base": "#53443a", "accent": "#d8c49b", "shadow": "#231c17"},
            "command": {"base": "#314551", "accent": "#89a9b5", "shadow": "#11181c"},
            "transit": {"base": "#58534c", "accent": "#b7a88d", "shadow": "#1f1a16"},
        }

    def _serialize_tiles(self) -> Tuple[List[Dict[str, Any]], List[Tuple[int, int]]]:
        theme_cycle = ["reactor", "foundry", "hydro", "archive", "command", "transit"]
        tiles: List[Dict[str, Any]] = []
        chamber_cells: List[Tuple[int, int]] = []
        for y in range(self.grid_height):
            for x in range(self.grid_width):
                tile = int(self.cave_matrix[y, x])
                if tile <= 0:
                    continue
                neighbor_count = sum(
                    1
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if self.is_open_cell(x + dx, y + dy)
                )
                theme = theme_cycle[(x * 3 + y * 5 + tile) % len(theme_cycle)]
                clutter = "pipe" if (x + y) % 5 == 0 else ("moss" if tile == 2 and (x + y) % 3 == 0 else "crate")
                occluder = tile == 2 or neighbor_count >= 3
                if tile == 2:
                    chamber_cells.append((x, y))
                tiles.append(
                    {
                        "x": x,
                        "y": y,
                        "kind": "chamber" if tile == 2 else "tunnel",
                        "theme": theme,
                        "walkable": True,
                        "z": 2 if tile == 2 else 1,
                        "neighbors": neighbor_count,
                        "clutter": clutter,
                        "foreground": occluder,
                    }
                )
        return tiles, chamber_cells

    def _bucket_index(self, value: int, start: int, end: int, buckets: int) -> int:
        span = max(1, end - start + 1)
        return min(buckets - 1, max(0, int(((value - start) * buckets) / span)))

    def _bucket_bounds(self, index: int, start: int, end: int, buckets: int) -> Tuple[int, int]:
        span = max(1, end - start + 1)
        bucket_start = start + int((index * span) / buckets)
        bucket_end = start + int(((index + 1) * span) / buckets) - 1
        if index == buckets - 1:
            bucket_end = end
        return bucket_start, max(bucket_start, bucket_end)

    def _default_boiler_anchor(self, chamber_cells: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        if not chamber_cells:
            return None
        center_x = self.grid_width / 2.0
        center_y = self.grid_height / 2.0
        return min(
            chamber_cells,
            key=lambda cell: abs(cell[0] - center_x) + abs(cell[1] - center_y),
        )

    def _build_room_connectors(self, rows: int) -> List[Dict[str, Any]]:
        connectors: List[Dict[str, Any]] = []
        for row in range(rows):
            for col in range(ROOM_GRID_WIDTH):
                room_index = row * ROOM_GRID_WIDTH + col
                room_id = f"room-{room_index + 1:02d}"
                if col < ROOM_GRID_WIDTH - 1:
                    connectors.append(
                        {
                            "from": room_id,
                            "to": f"room-{room_index + 2:02d}",
                            "kind": "hallway",
                            "label": "service lane",
                        }
                    )
                if row < rows - 1:
                    connectors.append(
                        {
                            "from": room_id,
                            "to": f"room-{room_index + ROOM_GRID_WIDTH + 1:02d}",
                            "kind": "ladder",
                            "label": "stack riser",
                        }
                    )
        return connectors

    def _build_signal_links(self, rows: int) -> List[Dict[str, Any]]:
        links: List[Dict[str, Any]] = []
        horizontal_kinds = ["token", "control", "trace", "deliverable"]
        vertical_kinds = ["coolant", "telemetry", "reserve", "watchdog"]
        for row in range(rows):
            for col in range(ROOM_GRID_WIDTH - 1):
                source = row * ROOM_GRID_WIDTH + col
                links.append(
                    {
                        "from": f"room-{source + 1:02d}",
                        "to": f"room-{source + 2:02d}",
                        "kind": horizontal_kinds[(source + col) % len(horizontal_kinds)],
                        "label": f"lane {row + 1}.{col + 1}",
                        "load_pct": min(96, 44 + source * 3),
                    }
                )
        for row in range(rows - 1):
            for col in range(ROOM_GRID_WIDTH):
                source = row * ROOM_GRID_WIDTH + col
                links.append(
                    {
                        "from": f"room-{source + 1:02d}",
                        "to": f"room-{source + ROOM_GRID_WIDTH + 1:02d}",
                        "kind": vertical_kinds[(source + row) % len(vertical_kinds)],
                        "label": f"stack {col + 1}",
                        "load_pct": min(92, 38 + source * 2),
                    }
                )
        diagonal_pairs = [(1, 6, "prompt"), (4, 10, "tool"), (7, 12, "fault"), (10, 15, "mirror")]
        for source, target, kind in diagonal_pairs:
            if target <= rows * ROOM_GRID_WIDTH:
                links.append(
                    {
                        "from": f"room-{source:02d}",
                        "to": f"room-{target:02d}",
                        "kind": kind,
                        "label": "cross-link",
                        "load_pct": min(90, 52 + source * 2),
                    }
                )
        return links

    def _build_vault_rooms(
        self,
        tiles: List[Dict[str, Any]],
        boiler_anchor: Optional[Tuple[int, int]],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        rows = max(ROOM_GRID_START_ROWS, (len(ORBSTUDIO_ROOM_BLUEPRINTS) + ROOM_GRID_WIDTH - 1) // ROOM_GRID_WIDTH)
        min_x = min((int(tile["x"]) for tile in tiles), default=0)
        max_x = max((int(tile["x"]) for tile in tiles), default=max(0, self.grid_width - 1))
        min_y = min((int(tile["y"]) for tile in tiles), default=0)
        max_y = max((int(tile["y"]) for tile in tiles), default=max(0, self.grid_height - 1))
        room_tiles: Dict[int, List[Dict[str, Any]]] = {index: [] for index in range(rows * ROOM_GRID_WIDTH)}
        room_agents: Dict[int, List[str]] = {index: [] for index in range(rows * ROOM_GRID_WIDTH)}
        room_reserved: Dict[int, int] = {index: 0 for index in range(rows * ROOM_GRID_WIDTH)}
        reserved_cells = self.reserved_cells()

        for tile in tiles:
            col = self._bucket_index(int(tile["x"]), min_x, max_x, ROOM_GRID_WIDTH)
            row = self._bucket_index(int(tile["y"]), min_y, max_y, rows)
            room_tiles[row * ROOM_GRID_WIDTH + col].append(tile)

        for agent_id, cell in self.agent_cells.items():
            col = self._bucket_index(int(cell[0]), min_x, max_x, ROOM_GRID_WIDTH)
            row = self._bucket_index(int(cell[1]), min_y, max_y, rows)
            room_agents[row * ROOM_GRID_WIDTH + col].append(agent_id)

        for cell_x, cell_y in reserved_cells:
            col = self._bucket_index(int(cell_x), min_x, max_x, ROOM_GRID_WIDTH)
            row = self._bucket_index(int(cell_y), min_y, max_y, rows)
            room_reserved[row * ROOM_GRID_WIDTH + col] += 1

        boiler_room_index: Optional[int] = None
        if boiler_anchor:
            boiler_room_index = (
                self._bucket_index(int(boiler_anchor[1]), min_y, max_y, rows) * ROOM_GRID_WIDTH
                + self._bucket_index(int(boiler_anchor[0]), min_x, max_x, ROOM_GRID_WIDTH)
            )

        rooms: List[Dict[str, Any]] = []
        for index in range(rows * ROOM_GRID_WIDTH):
            blueprint = dict(ORBSTUDIO_ROOM_BLUEPRINTS[index % len(ORBSTUDIO_ROOM_BLUEPRINTS)])
            row = index // ROOM_GRID_WIDTH
            col = index % ROOM_GRID_WIDTH
            bucket_min_x, bucket_max_x = self._bucket_bounds(col, min_x, max_x, ROOM_GRID_WIDTH)
            bucket_min_y, bucket_max_y = self._bucket_bounds(row, min_y, max_y, rows)
            assigned_tiles = room_tiles[index]
            assigned_agents = sorted(room_agents[index])
            reserved_count = room_reserved[index]
            tile_bounds = [bucket_min_x, bucket_min_y, bucket_max_x, bucket_max_y]
            if assigned_tiles:
                tile_bounds = [
                    min(int(tile["x"]) for tile in assigned_tiles),
                    min(int(tile["y"]) for tile in assigned_tiles),
                    max(int(tile["x"]) for tile in assigned_tiles),
                    max(int(tile["y"]) for tile in assigned_tiles),
                ]
            anchor_cell = [
                (tile_bounds[0] + tile_bounds[2]) // 2,
                (tile_bounds[1] + tile_bounds[3]) // 2,
            ]
            chamber_count = sum(1 for tile in assigned_tiles if tile.get("kind") == "chamber")
            token_usage = min(100, 16 + len(assigned_tiles) * 3 + len(assigned_agents) * 15 + reserved_count * 8 + (18 if index == boiler_room_index else 0))
            signal_load = min(100, 22 + chamber_count * 12 + len(assigned_agents) * 14 + reserved_count * 6 + row * 7 + col * 5)
            rooms.append(
                {
                    "id": f"room-{index + 1:02d}",
                    "grid": [col, row],
                    "title": blueprint["title"],
                    "theme": blueprint["theme"],
                    "style": blueprint["style"],
                    "detail": blueprint["detail"],
                    "lanes": list(blueprint["lanes"]),
                    "terminals": list(blueprint["terminals"]),
                    "intake": blueprint["intake"],
                    "output": blueprint["output"],
                    "tile_bounds": tile_bounds,
                    "anchor_cell": anchor_cell,
                    "tile_count": len(assigned_tiles),
                    "chamber_count": chamber_count,
                    "occupancy": len(assigned_agents),
                    "agents": assigned_agents,
                    "reserved_count": reserved_count,
                    "locked": reserved_count > 0,
                    "boiler_room": index == boiler_room_index,
                    "token_usage_pct": token_usage,
                    "signal_load_pct": signal_load,
                    "status": "boiler hub" if index == boiler_room_index else ("reserved" if reserved_count else "nominal"),
                }
            )

        room_grid = {
            "columns": ROOM_GRID_WIDTH,
            "rows": rows,
            "max_columns": ROOM_GRID_WIDTH,
        }
        return room_grid, rooms, self._build_room_connectors(rows), self._build_signal_links(rows)

    # ELI5: This turns the cave floor into a compact tile list so the browser can paint
    # an isometric map instead of guessing from raw matrix numbers.
    def serialize_world(self) -> Dict[str, Any]:
        tiles, chamber_cells = self._serialize_tiles()
        boiler_anchor = self._default_boiler_anchor(chamber_cells)
        room_grid, rooms, room_connectors, signal_links = self._build_vault_rooms(tiles, boiler_anchor)
        return {
            "grid_width": self.grid_width,
            "grid_height": self.grid_height,
            "cell_size": self.cell_size,
            "projection": {
                "kind": "isometric",
                "tile_width": 64,
                "tile_height": 32,
                "wall_height": 28,
                "agent_lift": 20,
            },
            "palette": self._theme_palette(),
            "boiler_tile": list(boiler_anchor) if boiler_anchor else [],
            "room_grid": room_grid,
            "rooms": rooms,
            "room_connectors": room_connectors,
            "signal_links": signal_links,
            "tiles": tiles,
        }


# ELI5: This class is the emergency transfer switch. When the boiler trips, all
# requests get rerouted to the local generator on LM Studio port 1234.
class LocalBypassGovernor:
    def __init__(self, local_port: int = 1234):
        self.local_port = local_port
        self.is_active = False
        self.local_endpoint = f"http://127.0.0.1:{self.local_port}/v1/completions"
        logger.info("Local Bypass Governor installed and waiting on standby.")

    # ELI5: Throwing this switch is like moving a factory from city power onto a diesel generator.
    def engage_local_generator(self) -> None:
        self.is_active = True
        logger.warning(f"EMERGENCY BYPASS ENGAGED: Routing all inference to {self.local_endpoint}")

    # ELI5: This lets the generator rest after enough successful local work cools the plant.
    def cool_down_cycle(self, successful_local_tasks: int) -> bool:
        if successful_local_tasks >= 5:
            self.is_active = False
            logger.info("Boiler pressure normalized. Re-engaging Cloud Exchange.")
            return True
        return False

    # ELI5: This is the actual local dispatch. If LM Studio is reachable, we knock on
    # the endpoint; if not, we still return a safe local-accept result for the foreman.
    async def execute_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request_payload = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.local_endpoint,
            data=request_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        def _send() -> Dict[str, Any]:
            try:
                with urllib.request.urlopen(request, timeout=2.0) as response:
                    raw = response.read().decode("utf-8")
                    return {"route": "local-bypass", "ok": True, "payload": raw}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                exc.close()
                return {
                    "route": "local-bypass",
                    "ok": True,
                    "fallback": True,
                    "endpoint": self.local_endpoint,
                    "detail": detail or str(exc),
                    "task_id": payload.get("task_id", "UNKNOWN"),
                }
            except Exception as exc:
                return {
                    "route": "local-bypass",
                    "ok": True,
                    "fallback": True,
                    "endpoint": self.local_endpoint,
                    "detail": str(exc),
                    "task_id": payload.get("task_id", "UNKNOWN"),
                }

        return await asyncio.to_thread(_send)


# ELI5: This is the default cloud line. It behaves like the normal utility feed when
# the boiler is healthy and there is no need to switch to the basement generator.
class CloudDispatchModel:
    async def execute_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.05)
        return {
            "route": "cloud",
            "ok": True,
            "task_id": payload.get("task_id", "UNKNOWN"),
            "detail": "Task processed on primary exchange.",
        }


# ELI5: A Gandy Dancer is a tunnel crew worker. Each one has a simple state chart,
# like an electrical relay ladder, so the foreman can predict what comes next.
class GandyState(str, Enum):
    IDLE = "IDLE"
    WALK = "WALK"
    CARRY = "CARRY"
    USE_TOOL = "USE_TOOL"


# ELI5: This object represents one AGD worker moving around the cave floorplan.
@dataclass
class GandyDancer:
    agent_id: str
    cave_system: CaveSpatialHash
    movement_speed: float = 1.0
    state: GandyState = GandyState.IDLE
    carried_load: int = 0
    tool_registry: Dict[str, Any] = field(default_factory=dict)
    motion_snapshot: Dict[str, Any] = field(default_factory=dict)
    motion_callback: Optional[Callable[[str], Any]] = None

    def __post_init__(self) -> None:
        origin = self.cave_system.place_agent(self.agent_id)
        self.tool_registry = {
            "write_file": self._tool_write_file,
            "append_file": self._tool_append_file,
            "call_api": self._tool_call_api,
        }
        self.motion_snapshot = {
            "from": list(origin),
            "to": list(origin),
            "started_at": time.time(),
            "duration_s": 0.0,
        }

    # ELI5: This changes the relay position for the AGD so every downstream action
    # knows whether the worker is resting, walking, hauling, or using a tool.
    def set_state(self, new_state: GandyState) -> None:
        self.state = new_state
        self._emit_motion_event()

    @property
    def effective_speed(self) -> float:
        if self.state == GandyState.CARRY:
            return self.movement_speed * 0.5
        return self.movement_speed

    # ELI5: This computes the delay between steps. A loaded cart makes the worker move
    # slower, just like a heavy cable reel slows the crew on a rail line.
    def _step_delay(self) -> float:
        return max(0.02, 0.12 / max(0.25, self.effective_speed))

    def _capture_motion(self, origin: Tuple[int, int], destination: Tuple[int, int], duration_s: float) -> None:
        self.motion_snapshot = {
            "from": [int(origin[0]), int(origin[1])],
            "to": [int(destination[0]), int(destination[1])],
            "started_at": time.time(),
            "duration_s": max(0.0, float(duration_s)),
        }
        self._emit_motion_event()

    def _emit_motion_event(self) -> None:
        if self.motion_callback is None:
            return
        result = self.motion_callback(self.agent_id)
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)

    # ELI5: This marches the AGD through the cave like moving a drafting cursor from
    # snap point to snap point on an AutoCAD grid.
    async def walk(self, path: List[Tuple[int, int]]) -> Tuple[int, int]:
        self.set_state(GandyState.WALK)
        final = self.cave_system.agent_cells.get(self.agent_id, (0, 0))
        for dx, dy in path:
            origin = final
            duration_s = self._step_delay()
            final = self.cave_system.move_agent(self.agent_id, dx, dy)
            self._capture_motion(origin, final, duration_s)
            await asyncio.sleep(duration_s)
        self.set_state(GandyState.IDLE)
        self._capture_motion(final, final, 0.0)
        return final

    # ELI5: Carry mode halves the pace because the AGD is hauling material or tools.
    async def carry(self, path: List[Tuple[int, int]], load_weight: int) -> Tuple[int, int]:
        self.carried_load = load_weight
        self.set_state(GandyState.CARRY)
        final = self.cave_system.agent_cells.get(self.agent_id, (0, 0))
        for dx, dy in path:
            origin = final
            duration_s = self._step_delay()
            final = self.cave_system.move_agent(self.agent_id, dx, dy)
            self._capture_motion(origin, final, duration_s)
            await asyncio.sleep(duration_s)
        self.carried_load = 0
        self.set_state(GandyState.IDLE)
        self._capture_motion(final, final, 0.0)
        return final

    # ELI5: This dispatches a real tool action. Think of it like plugging a drill,
    # radio, or clipboard into the same standardized service port.
    async def use_tool(self, tool_name: str, **kwargs: Any) -> Any:
        if tool_name not in self.tool_registry:
            raise KeyError(f"Unknown tool action: {tool_name}")
        self.set_state(GandyState.USE_TOOL)
        try:
            handler = self.tool_registry[tool_name]
            return await handler(**kwargs)
        finally:
            self.set_state(GandyState.IDLE)

    # ELI5: This writes a fresh service note to disk, like pinning a new work order
    # onto the maintenance board in the tunnel office.
    async def _tool_write_file(self, path: str, text: str) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> str:
            target.write_text(text, encoding="utf-8")
            return str(target)

        return await asyncio.to_thread(_write)

    # ELI5: This appends a line to the day log, like adding another pencil mark to the foreman's ledger.
    async def _tool_append_file(self, path: str, text: str) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _append() -> str:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(text)
            return str(target)

        return await asyncio.to_thread(_append)

    # ELI5: This is the AGD using a field telephone to call another station through the API wire.
    async def _tool_call_api(self, url: str, timeout: float = 2.0) -> Dict[str, Any]:
        request = urllib.request.Request(url, method="GET")

        def _fetch() -> Dict[str, Any]:
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return {
                        "ok": True,
                        "status": response.status,
                        "url": url,
                    }
            except urllib.error.URLError as exc:
                return {
                    "ok": False,
                    "url": url,
                    "detail": str(exc),
                }

        return await asyncio.to_thread(_fetch)


# ELI5: This switchboard tracks every teleprinter line connected from VS Code or a browser.
class TeleprinterConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Set[Any] = set()

    # ELI5: Plugging the teleprinter cable into the wall jack opens a live status circuit.
    async def connect(self, websocket: Any) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"New Teleprinter wired into the grid. Total active lines: {len(self.active_connections)}")

    # ELI5: Pulling the cable out removes the dead line so we do not page an empty desk.
    def disconnect(self, websocket: Any) -> None:
        self.active_connections.discard(websocket)
        logger.info("Teleprinter line severed.")

    # ELI5: Broadcasting is our plant-wide PA speaker. Every connected operator hears the same bulletin.
    async def broadcast_telemetry(self, message: Dict[str, Any]) -> None:
        if not self.active_connections:
            return
        payload = json.dumps(message)
        stale: List[Any] = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                stale.append(connection)
        for dead in stale:
            self.disconnect(dead)


# ELI5: This is the whole factory control cabinet. It owns the gauge, cave map,
# worker roster, config patching, persistence, and emergency routing behavior in one clean assembly.
class SITKMasterControl:
    def __init__(
        self,
        seed: int = 13,
        layout_steps: int = 260,
        state_path: Optional[Path | str] = None,
        config_root: Optional[Path | str] = None,
        recovery_policy: str = "auto-reset",
    ):
        self.gauge = ThermalPressureGauge()
        self.cave_system = CaveSpatialHash()
        self.cave_system.Generate_Morrowind_Layout(seed=seed, steps=layout_steps)
        self.switchboard = TeleprinterConnectionManager()
        self.governor = LocalBypassGovernor(local_port=1234)
        self.primary_model: AgentModel = CloudDispatchModel()
        self.agents: Dict[str, GandyDancer] = {}
        self.active_circuits: List[asyncio.Task[Any]] = []
        self.flashover_announced = False
        self.successful_local_tasks = 0
        self.output_dir = Path("outputs") / "orbstudio"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = Path(state_path) if state_path else self.output_dir / "sitk_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.chatlog_path = self.output_dir / ORBSTUDIO_CHATLOG_NAME
        self.config_operator = GameIniOperator(config_root=config_root)
        self.bootstrap = BootstrapDiagnostics(workspace_root=Path.cwd())
        self.warning_band = int(self.gauge.burst_limit * 0.75)
        self.high_risk_band = int(self.gauge.burst_limit * 0.90)
        self.recovery_policy = recovery_policy
        self.job_queue: List[Dict[str, Any]] = []
        self.completed_jobs: List[Dict[str, Any]] = []
        self.command_log: List[Dict[str, Any]] = []
        self.chat_history: List[Dict[str, Any]] = self._load_chat_history()
        self.startup_recovery: Dict[str, Any] = {"performed": False, "actions": []}
        self.fault_log: List[Dict[str, Any]] = []
        self.acked_fault_ids: Set[str] = set()
        self.autonomous_mode = "enabled"
        self.autonomous_tick_count = 0
        self.autonomous_task_serial = 0
        self.autonomous_last_task = "idle"
        self.autonomous_last_agent = ""
        self.generated_assets: Dict[str, Dict[str, Any]] = {
            "texture": {"path": "", "prompt": "", "status": "idle", "url": ""},
            "character": {"path": "", "prompt": "", "status": "idle", "url": ""},
            **{
                self._room_style_asset_key(theme): {"path": "", "prompt": spec["prompt"], "status": "idle", "url": ""}
                for theme, spec in ROOM_STYLE_SPECS.items()
            },
        }
        self.asset_output_dir = self.output_dir / "generated_assets"
        self.asset_output_dir.mkdir(parents=True, exist_ok=True)
        self.load_state()
        self._apply_cold_boot_hygiene()

    # ELI5: This is the event ledger. It stores the recent work orders and operator commands
    # the same way a substation keeps a rolling log of breaker events.
    def _record_event(self, event: str, **details: Any) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **details,
        }
        self.command_log.append(entry)
        self.command_log = self.command_log[-60:]

    def _load_chat_history(self) -> List[Dict[str, Any]]:
        if not self.chatlog_path.exists():
            return []
        entries: List[Dict[str, Any]] = []
        try:
            for raw_line in self.chatlog_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    entries.append(payload)
        except OSError as exc:
            logger.warning("Unable to read ORBSTUDIO chatlog: %s", exc)
            return []
        return entries[-120:]

    def _append_chatlog_entry(self, entry: Dict[str, Any]) -> None:
        try:
            self.chatlog_path.parent.mkdir(parents=True, exist_ok=True)
            with self.chatlog_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except OSError as exc:
            logger.warning("Unable to append ORBSTUDIO chatlog entry: %s", exc)

    @staticmethod
    def _chat_text(value: Any, fallback: str = "") -> str:
        text = str(value or fallback).strip()
        if len(text) <= 280:
            return text
        return text[:277].rstrip() + "..."

    def _record_chat_exchange(self, role: str, message: str, channel: str = "teleprinter", **details: Any) -> Dict[str, Any]:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "channel": channel,
            "message": self._chat_text(message, fallback="(empty)"),
            **details,
        }
        self.chat_history.append(entry)
        self.chat_history = self.chat_history[-120:]
        self._append_chatlog_entry(entry)
        return entry

    def _command_chat_message(self, action: str, payload: Dict[str, Any]) -> str:
        for key in ("message", "prompt", "policy", "agent_id"):
            if payload.get(key):
                return f"{action}: {self._chat_text(payload.get(key))}"
        if action == "process-queue":
            return f"{action}: lookahead={int(payload.get('lookahead', 1))}"
        return action

    def _result_chat_message(self, action: str, result: Dict[str, Any]) -> str:
        if result.get("ok") is False:
            return self._chat_text(result.get("error") or result.get("reason") or f"{action} failed")
        if action == "save-state":
            return f"State saved to {result.get('state_path', self.state_path)}"
        if action == "bootstrap-report":
            return f"Bootstrap report ready at {result.get('report_path', '')}"
        if action == "health-check":
            return f"Health check complete. queue={result.get('queue_depth', 0)} pressure={result.get('boiler', {}).get('pressure', 0)}"
        if action == "enqueue-demo":
            return f"Demo ticket queued: {result.get('ticket', {}).get('task_id', 'unknown')}"
        if action in {"dispatch-next", "process-queue"}:
            return self._chat_text(f"{action} complete. processed={result.get('processed', int(bool(result.get('ok'))))} remaining={result.get('remaining', len(self.job_queue))}")
        if action == "trip-boiler":
            return "Boiler tripped. Local bypass governor engaged if needed."
        if action == "reset-boiler":
            return "Boiler reset and flashover latch cleared."
        if action == "set-recovery-policy":
            return f"Recovery policy set to {result.get('recovery_policy', self.recovery_policy)}"
        if action == "generate-texture":
            return self._chat_text(f"Texture forge status: {result.get('asset', {}).get('status', 'idle')}")
        if action == "generate-character":
            return self._chat_text(f"Dweller forge status: {result.get('asset', {}).get('status', 'idle')}")
        if action == "generate-room-styles":
            return self._chat_text(f"Room style pack generated: {len(result.get('assets', {}))} themes")
        if action == "autonomous-tick":
            return self._chat_text(f"Autonomous tick completed: {result.get('task_id', 'idle')}")
        return self._chat_text(result.get("status") or result.get("detail") or f"{action} complete")

    def _finalize_command(self, action: str, payload: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        self._record_chat_exchange("user", self._command_chat_message(action, payload), channel="command", action=action)
        self._record_chat_exchange("assistant", self._result_chat_message(action, result), channel="command", action=action)
        return result

    # ELI5: This is the annunciator panel. Every serious plant problem gets a tagged lamp
    # entry so operators can acknowledge it without losing the audit trail.
    def _record_fault(self, kind: str, detail: str, severity: str = "warning") -> Dict[str, Any]:
        fault_id = f"{kind}:{len(self.fault_log)+1}:{int(time.time())}"
        fault = {
            "id": fault_id,
            "kind": kind,
            "detail": detail,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.fault_log.append(fault)
        self.fault_log = self.fault_log[-50:]
        return fault

    def _fault_snapshot(self) -> Dict[str, Any]:
        recent = [
            {
                **fault,
                "acknowledged": fault["id"] in self.acked_fault_ids,
            }
            for fault in self.fault_log[-8:]
        ]
        unacked = [fault for fault in recent if not fault["acknowledged"]]
        return {
            "count": len(self.fault_log),
            "unacked": unacked,
            "recent": recent,
        }

    def _asset_url(self, kind: str, path: str) -> str:
        if not path:
            return ""
        return f"/generated-assets/{kind}?ts={int(time.time())}"

    @staticmethod
    def _room_style_asset_key(theme: str) -> str:
        return f"room-style-{theme}"

    def _room_style_assets(self) -> Dict[str, Dict[str, Any]]:
        snapshot: Dict[str, Dict[str, Any]] = {}
        for theme, spec in ROOM_STYLE_SPECS.items():
            asset_key = self._room_style_asset_key(theme)
            meta = dict(self.generated_assets.get(asset_key, {}))
            snapshot[theme] = {
                "title": spec["title"],
                "style": spec["style"],
                "prompt": str(meta.get("prompt") or spec["prompt"]),
                "status": str(meta.get("status") or "idle"),
                "path": str(meta.get("path") or ""),
                "url": str(meta.get("url") or ""),
            }
        return snapshot

    def _refresh_generated_asset_urls(self) -> None:
        for kind, meta in self.generated_assets.items():
            meta["url"] = self._asset_url(kind, str(meta.get("path", "")))

    def _generate_svg_fallback(self, kind: str, prompt: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "texture":
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
<rect width="512" height="512" fill="#2b2118"/>
<g stroke="#6f5435" stroke-width="10" opacity="0.75">
<path d="M0 64 L512 64"/><path d="M0 192 L512 192"/><path d="M0 320 L512 320"/><path d="M0 448 L512 448"/>
<path d="M64 0 L64 512"/><path d="M192 0 L192 512"/><path d="M320 0 L320 512"/><path d="M448 0 L448 512"/>
</g>
<g fill="#a88452" opacity="0.22">
<circle cx="120" cy="120" r="26"/><circle cx="380" cy="150" r="18"/><circle cx="280" cy="380" r="30"/><circle cx="90" cy="420" r="16"/>
</g>
<text x="24" y="486" fill="#ffd089" font-family="Courier New" font-size="20">{prompt[:42]}</text>
</svg>'''
        elif kind.startswith("room-style-"):
            theme = kind.replace("room-style-", "", 1)
            spec = ROOM_STYLE_SPECS.get(theme, {"title": theme.title(), "style": theme, "prompt": prompt})
            palette = {
                "reactor": ("#11333b", "#74ffd1", "#183a31"),
                "foundry": ("#4d261b", "#ffb86d", "#27140f"),
                "hydro": ("#133626", "#9dffba", "#0b2016"),
                "archive": ("#2f2149", "#c69aff", "#160f26"),
                "command": ("#173753", "#8fe0ff", "#0c1826"),
                "transit": ("#383e46", "#f2f6fa", "#171a1e"),
            }
            base, accent, shadow = palette.get(theme, ("#203040", "#dfefff", "#10151b"))
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="768" height="512" viewBox="0 0 768 512">
<defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="{base}"/>
        <stop offset="100%" stop-color="{shadow}"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="{accent}" stop-opacity="0.95"/>
        <stop offset="100%" stop-color="#ffffff" stop-opacity="0.2"/>
    </linearGradient>
</defs>
<rect width="768" height="512" rx="24" fill="url(#bg)"/>
<rect x="32" y="42" width="704" height="428" rx="28" fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.14)"/>
<rect x="70" y="92" width="628" height="248" rx="22" fill="url(#accent)" opacity="0.38"/>
<rect x="96" y="348" width="250" height="72" rx="18" fill="rgba(0,0,0,0.22)"/>
<rect x="386" y="334" width="84" height="96" rx="18" fill="rgba(255,255,255,0.14)"/>
<rect x="496" y="308" width="132" height="122" rx="22" fill="rgba(0,0,0,0.18)"/>
<rect x="528" y="94" width="126" height="12" rx="6" fill="{accent}" opacity="0.85"/>
<rect x="112" y="114" width="180" height="10" rx="5" fill="{accent}" opacity="0.72"/>
<text x="80" y="74" fill="#f7ffff" font-family="Trebuchet MS" font-size="34" font-weight="700">{spec['title']}</text>
<text x="82" y="110" fill="rgba(247,255,255,0.72)" font-family="Trebuchet MS" font-size="18">{spec['style']}</text>
<text x="80" y="462" fill="#f7ffff" font-family="Courier New" font-size="18">{prompt[:72]}</text>
</svg>'''
        else:
            svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="768" viewBox="0 0 512 768">
<rect width="512" height="768" fill="#14100c"/>
<ellipse cx="256" cy="716" rx="110" ry="24" fill="#000" opacity="0.32"/>
<rect x="196" y="280" width="120" height="240" rx="24" fill="#8a6737"/>
<circle cx="256" cy="200" r="74" fill="#e3c296"/>
<rect x="166" y="300" width="38" height="180" rx="18" fill="#8a6737"/>
<rect x="308" y="300" width="38" height="180" rx="18" fill="#8a6737"/>
<rect x="206" y="520" width="34" height="150" rx="16" fill="#5c4630"/>
<rect x="272" y="520" width="34" height="150" rx="16" fill="#5c4630"/>
<rect x="184" y="132" width="144" height="34" rx="10" fill="#3b2d1b"/>
<text x="32" y="734" fill="#ffd089" font-family="Courier New" font-size="20">{prompt[:38]}</text>
</svg>'''
        output_path.write_text(svg, encoding="utf-8")

    def _generate_asset_sync(self, kind: str, prompt: str) -> Dict[str, Any]:
        suffix = ".png" if ComfyUIClient is not None else ".svg"
        output_path = self.asset_output_dir / f"{kind}{suffix}"
        ok = False

        if ComfyUIClient is not None:
            try:
                comfy_ready = False
                if is_comfyui_ready is not None and ComfyUiLaunchConfig is not None:
                    comfy_ready = bool(is_comfyui_ready(ComfyUiLaunchConfig()))
                if comfy_ready:
                    comfy = ComfyUIClient()
                    ok = bool(comfy.generate_image(prompt=prompt, output_path=output_path, steps=10))
            except Exception:
                ok = False

        if not ok:
            self._generate_svg_fallback(kind, prompt, output_path.with_suffix(".svg"))
            output_path = output_path.with_suffix(".svg")
            ok = True

        self.generated_assets[kind] = {
            "path": str(output_path),
            "prompt": prompt,
            "status": "ready" if ok else "failed",
            "url": self._asset_url(kind, str(output_path)),
        }
        return self.generated_assets[kind]

    async def generate_asset(self, kind: str, prompt: str) -> Dict[str, Any]:
        self.generated_assets[kind] = {
            "path": str(self.generated_assets.get(kind, {}).get("path", "")),
            "prompt": prompt,
            "status": "running",
            "url": str(self.generated_assets.get(kind, {}).get("url", "")),
        }
        result = await asyncio.to_thread(self._generate_asset_sync, kind, prompt)
        self._record_event("asset-generated", kind=kind, status=result.get("status"))
        await self.broadcast_status(event=f"asset-{kind}")
        return {"ok": result.get("status") == "ready", "asset": result}

    async def generate_room_styles(self) -> Dict[str, Any]:
        assets: Dict[str, Dict[str, Any]] = {}
        all_ready = True
        for theme, spec in ROOM_STYLE_SPECS.items():
            result = await self.generate_asset(self._room_style_asset_key(theme), spec["prompt"])
            assets[theme] = dict(result.get("asset", {}))
            all_ready = all_ready and bool(result.get("ok"))
        self._record_event("room-styles-generated", count=len(assets))
        await self.broadcast_status(event="asset-room-styles")
        return {"ok": all_ready, "assets": assets}

    # ELI5: This is the cold-start electrician checking whether yesterday's emergency latch
    # is still hanging open before the morning shift begins. If it is stale, we reset it.
    def _apply_cold_boot_hygiene(self) -> None:
        actions: List[str] = []
        if self.recovery_policy == "strict":
            self.startup_recovery = {"performed": False, "actions": actions, "mode": self.recovery_policy}
            return
        recovery_load_cap = int(self.gauge.burst_limit * 0.4)
        if self.gauge.current_load >= self.gauge.burst_limit:
            self.gauge.current_load = recovery_load_cap
            self.gauge.token_velocity = min(self.gauge.token_velocity, 0.45)
            actions.append("normalized-overpressure")
        if self.gauge.is_tripped:
            self.gauge.is_tripped = False
            if self.recovery_policy == "auto-reset":
                self.gauge.current_load = min(self.gauge.current_load, recovery_load_cap)
                self.gauge.token_velocity = min(self.gauge.token_velocity, 0.35)
            self.gauge.last_trip_reason = "cold boot reset"
            actions.append("cleared-stale-trip")
        if self.governor.is_active:
            self.governor.is_active = False
            actions.append("released-local-bypass")
        self.flashover_announced = False
        self.startup_recovery = {"performed": bool(actions), "actions": actions, "mode": self.recovery_policy}
        if actions:
            self._record_event("startup-recovery", actions=actions)

    # ELI5: This estimates how awkward a job is before dispatch, like checking both the job sheet
    # and the rail map before sending a crew into a congested tunnel.
    def _job_score(self, ticket: Dict[str, Any], agent_id: str) -> Tuple[int, int, int, str]:
        priority = int(ticket.get("priority", 5))
        payload = dict(ticket.get("payload", {}))
        destination = payload.get("destination")
        if destination:
            target_x = int(destination[0])
            target_y = int(destination[1])
            steps = self.cave_system.plan_safe_steps(agent_id, target_x, target_y)
            resolved_goal = self.cave_system.nearest_available_cell(target_x, target_y, exclude_agent_id=agent_id)
            destination_penalty = 0 if resolved_goal == (target_x, target_y) else 500 + abs(resolved_goal[0] - target_x) + abs(resolved_goal[1] - target_y)
            path_cost = len(steps) if steps else 999
        else:
            destination_penalty = 0
            path_cost = len(payload.get("path", [(1, 0)]))
        return (priority, destination_penalty, path_cost, str(ticket.get("queued_at", "")))

    def _random_open_destination(self, exclude_agent_id: Optional[str] = None) -> Tuple[int, int]:
        blocked = self.cave_system.occupied_cells(exclude_agent_id=exclude_agent_id)
        blocked.update(self.cave_system.reserved_cells(exclude_agent_id=exclude_agent_id))
        candidates: List[Tuple[int, int]] = []
        for y in range(self.cave_system.grid_height):
            for x in range(self.cave_system.grid_width):
                if not self.cave_system.is_open_cell(x, y):
                    continue
                if (x, y) in blocked:
                    continue
                candidates.append((x, y))
        if not candidates:
            return self.cave_system.nearest_available_cell(
                self.cave_system.grid_width // 2,
                self.cave_system.grid_height // 2,
                exclude_agent_id=exclude_agent_id,
            )
        return random.choice(candidates)

    def _create_autonomous_job(self, agent_id: str) -> Dict[str, Any]:
        destination = self._random_open_destination(exclude_agent_id=agent_id)
        self.autonomous_task_serial += 1
        task_id = f"AUTO_PATROL_{self.autonomous_task_serial:03d}"
        ticket = self.submit_job(
            task_id,
            {
                "load_weight": random.randint(60, 180),
                "high_risk": False,
                "destination": [destination[0], destination[1]],
                "tool_action": {
                    "name": "append_file",
                    "kwargs": {
                        "path": str(self.output_dir / "autonomous_patrol.log"),
                        "text": f"{task_id} -> {destination[0]},{destination[1]}\n",
                    },
                },
            },
            priority=3,
        )
        self.autonomous_last_task = task_id
        self.autonomous_last_agent = agent_id
        self._record_event("autonomous-job-created", task_id=task_id, agent_id=agent_id, destination=list(destination))
        return ticket

    def _choose_job_index(self, agent_id: str, lookahead: int = 1) -> int:
        if not self.job_queue:
            return 0
        window = self.job_queue[: max(1, lookahead)]
        best_local_index = min(range(len(window)), key=lambda idx: self._job_score(window[idx], agent_id))
        return best_local_index

    # ELI5: This prepares a worker and pins its badge onto the cave map.
    async def register_agent(self, agent_id: str, movement_speed: float = 1.0) -> GandyDancer:
        agent = self.agents.get(agent_id)
        if agent is None:
            agent = GandyDancer(agent_id=agent_id, cave_system=self.cave_system, movement_speed=movement_speed)
            self.agents[agent_id] = agent
        else:
            agent.cave_system = self.cave_system
            agent.movement_speed = movement_speed
            if agent_id not in self.cave_system.agent_cells:
                self.cave_system.place_agent(agent_id)
        agent.motion_callback = lambda moved_agent_id: self.broadcast_status(event="agent-motion", agent_id=moved_agent_id)
        self._record_event("agent-registered", agent_id=agent_id)
        await self.broadcast_status(event="agent-registered", agent_id=agent_id)
        return agent

    async def _ensure_autonomous_agents(self, count: int = 3) -> None:
        while len(self.agents) < count:
            next_index = len(self.agents) + 1
            await self.register_agent(f"AGD-{next_index:02d}", movement_speed=1.05 + (next_index * 0.08))

    async def _dispatch_ticket(self, ticket: Dict[str, Any], selected_agent_id: str) -> Dict[str, Any]:
        agent = self.agents[selected_agent_id]
        payload = dict(ticket["payload"])
        path = payload.pop("path", [(1, 0)])
        destination = payload.pop("destination", None)
        carry_weight = int(payload.pop("carry_weight", 0))
        tool_action = payload.pop("tool_action", None)

        if destination:
            path = self.cave_system.plan_safe_steps(
                selected_agent_id,
                int(destination[0]),
                int(destination[1]),
            ) or path

        self.cave_system.reserve_path(selected_agent_id, path)

        if carry_weight > 0:
            await agent.carry(path, load_weight=carry_weight)
        else:
            await agent.walk(path)

        tool_result = None
        if tool_action:
            tool_name = str(tool_action.get("name"))
            tool_kwargs = dict(tool_action.get("kwargs", {}))
            tool_result = await agent.use_tool(tool_name, **tool_kwargs)

        route_result = await self.route_agent_request({"task_id": ticket["task_id"], **payload})
        result = {
            "ok": True,
            "task_id": ticket["task_id"],
            "agent_id": selected_agent_id,
            "tool_result": tool_result,
            "route_result": route_result,
        }
        self.completed_jobs.append({
            "task_id": ticket["task_id"],
            "agent_id": selected_agent_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        self.completed_jobs = self.completed_jobs[-40:]
        self._record_event("job-dispatched", task_id=ticket["task_id"], agent_id=selected_agent_id)
        return result

    async def run_autonomous_tick(self) -> Dict[str, Any]:
        self.autonomous_tick_count += 1
        if self.autonomous_mode != "enabled":
            return {"ok": False, "reason": "autonomy-disabled"}

        await self._ensure_autonomous_agents(count=3)

        idle_agents = [agent_id for agent_id, agent in self.agents.items() if agent.state == GandyState.IDLE]
        if not idle_agents:
            return {"ok": False, "reason": "agent-busy", "agent_id": self.autonomous_last_agent}

        while len(self.job_queue) < len(idle_agents):
            self._create_autonomous_job(idle_agents[len(self.job_queue) % len(idle_agents)])

        dispatches: List[asyncio.Task[Dict[str, Any]]] = []
        selected_results: List[Dict[str, Any]] = []
        for agent_id in idle_agents:
            if not self.job_queue:
                break
            ticket = self.job_queue.pop(self._choose_job_index(agent_id, lookahead=min(3, max(1, len(self.job_queue)))))
            dispatches.append(asyncio.create_task(self._dispatch_ticket(ticket, agent_id)))

        if not dispatches:
            return {"ok": False, "reason": "queue-empty"}

        selected_results = await asyncio.gather(*dispatches)
        final_result = selected_results[-1]
        self.autonomous_last_agent = str(final_result.get("agent_id", self.autonomous_last_agent))
        self.autonomous_last_task = str(final_result.get("task_id", self.autonomous_last_task))
        await self.broadcast_status(event="autonomous-tick", agent_id=self.autonomous_last_agent)
        return {
            "ok": True,
            "results": selected_results,
            "task_id": self.autonomous_last_task,
            "agent_id": self.autonomous_last_agent,
        }

    # ELI5: This queue is like a foreman's job board. High-priority slips go to the top,
    # and the next free AGD pulls the most urgent card first.
    def submit_job(self, task_id: str, payload: Dict[str, Any], priority: int = 5) -> Dict[str, Any]:
        ticket = {
            "task_id": task_id,
            "priority": int(priority),
            "payload": dict(payload),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        self.job_queue.append(ticket)
        self.job_queue.sort(key=lambda item: (item["priority"], item["queued_at"]))
        self._record_event("job-queued", task_id=task_id, priority=priority)
        return ticket

    # ELI5: This chooses the next crew like a dispatcher assigning the nearest open service truck,
    # helping spread work across the tunnel instead of always calling the same unit.
    def _select_agent_for_job(self, agent_id: Optional[str] = None) -> Optional[str]:
        if agent_id and agent_id in self.agents:
            return agent_id
        if not self.agents:
            return None
        return min(
            self.agents.keys(),
            key=lambda key: len(self.cave_system.query_nearby_agents(*self.cave_system.agent_cells.get(key, (0, 0)), radius=1)),
        )

    # ELI5: This dispatches one queued task to a crew, like handing the next stamped work order
    # to the nearest available gandy dancer on the tunnel board.
    async def dispatch_next_job(self, agent_id: Optional[str] = None, lookahead: int = 1) -> Dict[str, Any]:
        if not self.job_queue:
            return {"ok": False, "reason": "queue-empty"}

        if not self.agents:
            await self.register_agent(agent_id or "AGD-01", movement_speed=1.25)

        selected_agent_id = self._select_agent_for_job(agent_id) or next(iter(self.agents.keys()))
        ticket = self.job_queue.pop(self._choose_job_index(selected_agent_id, lookahead=lookahead))
        return await self._dispatch_ticket(ticket, selected_agent_id)

    # ELI5: This runs a whole clipboard stack of work orders in sequence, like clearing the backlog
    # at shift change until either the board is empty or the foreman says stop.
    async def process_job_queue(self, max_jobs: Optional[int] = None, lookahead: int = 1) -> Dict[str, Any]:
        processed = 0
        completed: List[Dict[str, Any]] = []
        limit = max_jobs if max_jobs is not None else len(self.job_queue)
        while self.job_queue and processed < limit:
            result = await self.dispatch_next_job(lookahead=lookahead)
            if result.get("ok"):
                completed.append(result)
                processed += 1
            else:
                break
        self._record_event("queue-processed", processed=processed)
        return {
            "ok": True,
            "processed": processed,
            "remaining": len(self.job_queue),
            "completed_jobs": completed,
        }

    # ELI5: This writes the operating state to disk, like saving a panel schedule so the whole room
    # can come back exactly as it was after a shutdown or brownout.
    async def save_state(self) -> Dict[str, Any]:
        snapshot = {
            "gauge": {
                "current_load": self.gauge.current_load,
                "burst_limit": self.gauge.burst_limit,
                "is_tripped": self.gauge.is_tripped,
                "token_velocity": self.gauge.token_velocity,
                "last_trip_reason": self.gauge.last_trip_reason,
            },
            "governor": {"is_active": self.governor.is_active},
            "agents": {
                agent_id: {
                    "cell": list(self.cave_system.agent_cells.get(agent_id, (0, 0))),
                    "movement_speed": agent.movement_speed,
                    "state": agent.state.value,
                }
                for agent_id, agent in self.agents.items()
            },
            "job_queue": self.job_queue,
            "completed_jobs": self.completed_jobs[-20:],
            "command_log": self.command_log[-30:],
            "chat_history": self.chat_history[-40:],
            "fault_log": self.fault_log[-50:],
            "acked_fault_ids": sorted(self.acked_fault_ids),
            "reservations": self.cave_system.serialize_reservations(),
            "generated_assets": self.generated_assets,
            "autonomous": {
                "mode": self.autonomous_mode,
                "tick_count": self.autonomous_tick_count,
                "task_serial": self.autonomous_task_serial,
                "last_task": self.autonomous_last_task,
                "last_agent": self.autonomous_last_agent,
            },
        }

        def _write() -> None:
            self.state_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        await asyncio.to_thread(_write)
        self._record_event("state-saved", path=str(self.state_path))
        return {"ok": True, "state_path": str(self.state_path)}

    # ELI5: This restores the saved panel schedule and worker map so the plant can resume after restart.
    def load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"loaded": False, "reason": "state-file-missing"}

        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Unable to load Phase 2 state file: %s", exc)
            return {"loaded": False, "reason": str(exc)}

        gauge_state = payload.get("gauge", {})
        self.gauge.current_load = int(gauge_state.get("current_load", self.gauge.current_load))
        self.gauge.burst_limit = int(gauge_state.get("burst_limit", self.gauge.burst_limit))
        self.gauge.is_tripped = bool(gauge_state.get("is_tripped", self.gauge.is_tripped))
        self.gauge.token_velocity = float(gauge_state.get("token_velocity", self.gauge.token_velocity))
        self.gauge.last_trip_reason = str(gauge_state.get("last_trip_reason", self.gauge.last_trip_reason))
        self.governor.is_active = bool(payload.get("governor", {}).get("is_active", False))
        self.job_queue = list(payload.get("job_queue", []))
        self.completed_jobs = list(payload.get("completed_jobs", []))[-40:]
        self.command_log = list(payload.get("command_log", []))[-60:]
        if not self.chat_history:
            self.chat_history = [
                item
                for item in list(payload.get("chat_history", []))[-120:]
                if isinstance(item, dict)
            ]
        self.fault_log = list(payload.get("fault_log", []))[-50:]
        self.acked_fault_ids = set(str(item) for item in payload.get("acked_fault_ids", []))
        autonomous = dict(payload.get("autonomous", {}))
        self.autonomous_mode = str(autonomous.get("mode", self.autonomous_mode))
        self.autonomous_tick_count = int(autonomous.get("tick_count", self.autonomous_tick_count))
        self.autonomous_task_serial = int(autonomous.get("task_serial", self.autonomous_task_serial))
        self.autonomous_last_task = str(autonomous.get("last_task", self.autonomous_last_task))
        self.autonomous_last_agent = str(autonomous.get("last_agent", self.autonomous_last_agent))
        raw_assets = dict(payload.get("generated_assets", {}))
        for kind in ("texture", "character"):
            if kind in raw_assets:
                self.generated_assets[kind] = dict(raw_assets[kind])
        self._refresh_generated_asset_urls()

        for agent_id, agent_state in payload.get("agents", {}).items():
            speed = float(agent_state.get("movement_speed", 1.0))
            agent = GandyDancer(agent_id=agent_id, cave_system=self.cave_system, movement_speed=speed)
            agent.set_state(GandyState(str(agent_state.get("state", GandyState.IDLE.value))))
            agent.motion_callback = lambda moved_agent_id: self.broadcast_status(event="agent-motion", agent_id=moved_agent_id)
            cell = agent_state.get("cell", [self.cave_system.grid_width // 2, self.cave_system.grid_height // 2])
            self.cave_system.place_agent(agent_id, int(cell[0]), int(cell[1]))
            self.agents[agent_id] = agent

        self.cave_system.restore_reservations(dict(payload.get("reservations", {})))

        return {"loaded": True, "state_path": str(self.state_path)}

    # ELI5: This applies the real Game.ini revision set and logs the result for the sidecar operators.
    def apply_phase2_config(self) -> Dict[str, Any]:
        result = self.config_operator.apply_phase2_patch()
        self._record_event("config-applied", updated=result.get("updated", False))
        return result

    # ELI5: This restores the previous marked-up drawing set when the operator needs to back out
    # the latest field revision without manually editing the sheet.
    def rollback_config(self) -> Dict[str, Any]:
        result = self.config_operator.rollback_phase2_patch()
        self._record_event("config-rolled-back", rolled_back=result.get("rolled_back", False))
        return result

    # ELI5: This is the plant health board. It summarizes the boiler, queue, and startup paperwork
    # the way a control room wall panel gives operators one glance status.
    def health_snapshot(self) -> Dict[str, Any]:
        bootstrap_report = self.bootstrap.generate_report()
        return {
            "bootstrap": {
                "report_path": bootstrap_report["report_path"],
                "launcher_path": bootstrap_report["launcher_path"],
                "dependencies": bootstrap_report["dependencies"],
            },
            "chatlog": {
                "path": str(self.chatlog_path),
                "turn_count": len(self.chat_history),
                "recent": self.chat_history[-6:],
            },
            "startup_recovery": self.startup_recovery,
            "recovery_policy": self.recovery_policy,
            "queue_depth": len(self.job_queue),
            "completed_jobs": self.completed_jobs[-5:],
            "faults": self._fault_snapshot(),
            "boiler": {
                "pressure": self.gauge.current_load,
                "warning_band": self.warning_band,
                "is_tripped": self.gauge.is_tripped,
                "local_bypass": self.governor.is_active,
            },
        }

    # ELI5: This is a little front-desk command interpreter for the browser sidecar.
    async def execute_command(self, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        self._record_event("command", action=action)

        if action == "save-state":
            return self._finalize_command(action, payload, await self.save_state())
        if action == "bootstrap-report":
            return self._finalize_command(action, payload, self.bootstrap.generate_report())
        if action == "patch-config":
            return self._finalize_command(action, payload, self.apply_phase2_config())
        if action == "rollback-config":
            return self._finalize_command(action, payload, self.rollback_config())
        if action == "enqueue-demo":
            ticket = self.submit_job(
                task_id="PHASE2_DEMO_JOB",
                priority=2,
                payload={
                    "load_weight": 900,
                    "high_risk": False,
                    "path": [(1, 0), (0, 1)],
                    "tool_action": {
                        "name": "append_file",
                        "kwargs": {
                            "path": str(self.output_dir / "teleprinter_queue.log"),
                            "text": "Phase 2 queue dispatch completed.\n",
                        },
                    },
                },
            )
            return self._finalize_command(action, payload, {"ok": True, "ticket": ticket})
        if action == "dispatch-next":
            return self._finalize_command(action, payload, await self.dispatch_next_job(payload.get("agent_id"), lookahead=int(payload.get("lookahead", 1))))
        if action == "process-queue":
            return self._finalize_command(action, payload, await self.process_job_queue(int(payload.get("max_jobs", 1)), lookahead=int(payload.get("lookahead", 1))))
        if action == "health-check":
            return self._finalize_command(action, payload, self.health_snapshot())
        if action == "trip-boiler":
            self.gauge.add_pressure(self.gauge.burst_limit, task_id="REMOTE_COMMAND")
            await self._handle_flashover_if_needed()
            return self._finalize_command(action, payload, {"ok": True, "tripped": self.gauge.is_tripped})
        if action == "reset-boiler":
            self.gauge.bleed_off(self.gauge.burst_limit)
            self.governor.is_active = False
            self.flashover_announced = False
            return self._finalize_command(action, payload, {"ok": True, "tripped": self.gauge.is_tripped})
        if action == "clear-stale-trip":
            self._apply_cold_boot_hygiene()
            return self._finalize_command(action, payload, {"ok": True, "startup_recovery": self.startup_recovery})
        if action == "set-recovery-policy":
            policy = str(payload.get("policy", "auto-reset"))
            if policy not in {"auto-reset", "cautious", "strict"}:
                return self._finalize_command(action, payload, {"ok": False, "error": "invalid recovery policy"})
            self.recovery_policy = policy
            self._apply_cold_boot_hygiene()
            return self._finalize_command(action, payload, {"ok": True, "recovery_policy": self.recovery_policy, "startup_recovery": self.startup_recovery})
        if action == "acknowledge-faults":
            for fault in self.fault_log:
                self.acked_fault_ids.add(fault["id"])
            return self._finalize_command(action, payload, {"ok": True, "faults": self._fault_snapshot()})
        if action == "generate-texture":
            prompt = str(payload.get("prompt") or "seamless subterranean stone-and-brass floor texture, grime, industrial wear, tileable game material")
            return self._finalize_command(action, payload, await self.generate_asset("texture", prompt))
        if action == "generate-character":
            prompt = str(payload.get("prompt") or "full-body underground dieselpunk rail worker, realistic human character, workwear, lantern belt, game concept art")
            return self._finalize_command(action, payload, await self.generate_asset("character", prompt))
        if action == "generate-room-styles":
            return self._finalize_command(action, payload, await self.generate_room_styles())
        if action == "autonomous-tick":
            return self._finalize_command(action, payload, await self.run_autonomous_tick())
        return self._finalize_command(action, payload, {"ok": True, "status": self.serialize_status(event="command-status")})

    # ELI5: This turns the current boiler and crew readings into a simple dashboard packet.
    def serialize_status(self, event: str = "heartbeat", agent_id: Optional[str] = None) -> Dict[str, Any]:
        world = self.cave_system.serialize_world()
        pressure_ratio = self.gauge.current_load / max(1, self.gauge.burst_limit)
        boiler_state = "flashover" if self.gauge.is_tripped else ("warning" if pressure_ratio >= 0.75 else "stable")
        return {
            "event": event,
            "agent_id": agent_id,
            "boiler_pressure": self.gauge.current_load,
            "burst_limit": self.gauge.burst_limit,
            "warning_band": self.warning_band,
            "is_tripped": self.gauge.is_tripped,
            "token_velocity": round(self.gauge.token_velocity, 2),
            "trip_reason": self.gauge.last_trip_reason,
            "local_bypass": self.governor.is_active,
            "job_queue_depth": len(self.job_queue),
            "completed_jobs": self.completed_jobs[-5:],
            "startup_recovery": self.startup_recovery,
            "recovery_policy": self.recovery_policy,
            "faults": self._fault_snapshot(),
            "state_path": str(self.state_path),
            "chatlog_path": str(self.chatlog_path),
            "config_path": str(self.config_operator.game_ini_path),
            "launcher_path": str(self.bootstrap.launcher_path),
            "world": world,
            "boiler": {
                "pressure": self.gauge.current_load,
                "limit": self.gauge.burst_limit,
                "ratio": round(pressure_ratio, 3),
                "state": boiler_state,
                "steam_level": round(min(1.0, 0.18 + pressure_ratio * 1.2), 3),
                "valve_phase": round(time.monotonic() * max(0.2, self.gauge.token_velocity), 3),
                "tile": list(world.get("boiler_tile") or []),
            },
            "teleprinter": {
                "mode": "mechanical",
                "stagger_ms": 16 if event in {"connected", "heartbeat", "watchdog"} else 12,
                "backlog_burst": 3 if event == "watchdog" else 6,
            },
            "generated_assets": self.generated_assets,
            "room_styles": self._room_style_assets(),
            "autonomous": {
                "mode": self.autonomous_mode,
                "tick_count": self.autonomous_tick_count,
                "last_task": self.autonomous_last_task,
                "last_agent": self.autonomous_last_agent,
            },
            "reserved_paths": {key: [list(cell) for cell in value] for key, value in self.cave_system.reserved_paths.items()},
            "recent_commands": self.command_log[-5:],
            "recent_chat": self.chat_history[-8:],
            "active_agents": {
                key: {
                    "cell": list(value),
                    "state": self.agents[key].state.value,
                    "motion": dict(self.agents[key].motion_snapshot),
                }
                for key, value in self.cave_system.agent_cells.items()
                if key in self.agents
            },
        }

    # ELI5: This pushes one clean dashboard update to every teleprinter on the floor.
    async def broadcast_status(self, event: str = "heartbeat", agent_id: Optional[str] = None) -> None:
        await self.switchboard.broadcast_telemetry(self.serialize_status(event=event, agent_id=agent_id))

    # ELI5: This is the fire watch. It keeps checking the boiler so the foreman gets a flashover warning instantly.
    async def boiler_watchdog(self, poll_interval: float = 0.35) -> None:
        while True:
            await self._handle_flashover_if_needed()
            await self.broadcast_status(event="watchdog")
            await asyncio.sleep(poll_interval)

    async def autonomous_director(self, poll_interval: float = 2.5) -> None:
        while True:
            try:
                await self.run_autonomous_tick()
            except Exception as exc:
                self._record_fault("autonomous-director", str(exc), severity="warning")
            await asyncio.sleep(poll_interval)

    # ELI5: This is the emergency script the moment the breaker trips. It lights the red border,
    # throws the reroute lever, and tells every connected sidecar that the plant is in flashover mode.
    async def _handle_flashover_if_needed(self) -> None:
        if self.gauge.is_tripped and not self.flashover_announced:
            self.flashover_announced = True
            self.governor.engage_local_generator()
            self._record_fault("thermal-flashover", self.gauge.last_trip_reason, severity="critical")
            await self.broadcast_status(event="thermal-flashover")
            logger.warning("THERMAL FLASHOVER EVENT TRIGGERED. REDIRECTING TO LOCAL BYPASS GOVERNOR.")

    # ELI5: This starts the background house systems, similar to energizing the main panel and alarm loop.
    async def start_background_tasks(self) -> None:
        if not self.active_circuits:
            self.active_circuits.append(asyncio.create_task(self.boiler_watchdog()))
            self.active_circuits.append(asyncio.create_task(self.autonomous_director()))

    # ELI5: This shuts off the auxiliary circuits in an orderly way so we do not leave sparking wires behind.
    async def stop_background_tasks(self) -> None:
        for task in self.active_circuits:
            task.cancel()
        if self.active_circuits:
            await asyncio.gather(*self.active_circuits, return_exceptions=True)
        self.active_circuits.clear()

    # ELI5: This is the traffic cop for model requests. Healthy tasks use the main exchange;
    # heavy or risky tasks get pre-emptive local bypass when the plant is in the warning band.
    async def route_agent_request(self, payload: Dict[str, Any], model: Optional[AgentModel] = None) -> Dict[str, Any]:
        task_id = str(payload.get("task_id", "UNKNOWN"))
        load_weight = int(payload.get("load_weight", 1000))
        high_risk = bool(payload.get("high_risk", False))
        self.gauge.add_pressure(load_weight, task_id=task_id)
        await self._handle_flashover_if_needed()

        soft_reroute = (
            not self.gauge.is_tripped
            and not self.governor.is_active
            and self.gauge.current_load >= self.warning_band
            and (high_risk or load_weight >= int(self.gauge.burst_limit * 0.18))
        )

        if self.governor.is_active or self.gauge.is_tripped or soft_reroute:
            result = await self.governor.execute_task(payload)
            result["preemptive"] = soft_reroute and not self.gauge.is_tripped
            if self.governor.is_active or self.gauge.is_tripped:
                self.successful_local_tasks += 1
                self.governor.cool_down_cycle(self.successful_local_tasks)
        else:
            route_model = model or self.primary_model
            result = await route_model.execute_task(payload)
            result["preemptive"] = False

        self._record_event("task-routed", task_id=task_id, route=result.get("route"), preemptive=result.get("preemptive"))
        self.gauge.bleed_off(max(250, load_weight // 4))
        await self.broadcast_status(event="task-complete")
        return result

    # ELI5: This is the shift demo. It walks a crew, slows them under load, uses real Python tools,
    # applies the config patch, saves state, and can hammer the boiler so the reroute can be observed.
    async def run_smoke_test(self, simulate_trip: bool = True) -> Dict[str, Any]:
        await self.start_background_tasks()
        try:
            agent = await self.register_agent("AGD-01", movement_speed=2.0)
            await agent.walk([(1, 0), (0, 1), (1, 0)])
            await agent.carry([(0, 1), (-1, 0)], load_weight=120)
            tool_path = self.output_dir / "foreman_log.txt"
            await agent.use_tool(
                "append_file",
                path=str(tool_path),
                text="AGD-01 completed ballast delivery.\n",
            )

            config_result = self.apply_phase2_config()
            self.submit_job(
                task_id="QUEUE_SYNC_JOB",
                priority=1,
                payload={
                    "load_weight": 600,
                    "high_risk": False,
                    "path": [(1, 0), (0, 1)],
                },
            )
            queued_result = await self.dispatch_next_job(agent.agent_id)

            normal_result = await self.route_agent_request(
                {"task_id": "CAVE_STATUS_SYNC", "load_weight": 1200, "agent": agent.agent_id}
            )

            trip_result: Dict[str, Any] = {"route": "skipped"}
            if simulate_trip:
                trip_result = await self.route_agent_request(
                    {
                        "task_id": "THERMAL_LOAD_TEST",
                        "load_weight": self.gauge.burst_limit,
                        "agent": agent.agent_id,
                        "high_risk": True,
                    }
                )

            await self.save_state()
            status = self.serialize_status(event="smoke-test")
            return {
                "normal_result": normal_result,
                "queued_result": queued_result,
                "trip_result": trip_result,
                "config_result": config_result,
                "status": status,
                "log_path": str(tool_path),
            }
        finally:
            await self.stop_background_tasks()


# ELI5: This HTML is the sidecar front panel. It now presents the plant like a
# vault-management game board instead of a plain terminal while still using the same live data.
def build_teleprinter_template() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ORBSTUDIO // Vault Ops</title>
  <style>
    :root{
            --vault-cyan:#6df5ff;
            --vault-cyan-soft:#bffffa;
            --vault-gold:#f5c96b;
            --vault-ink:#07131b;
            --vault-panel:#0c202a;
            --vault-panel-2:#133240;
            --vault-line:rgba(109,245,255,.34);
            --trip:#ff6961;
            --pulse-speed:1.4s;
            --shadow:0 18px 48px rgba(0,0,0,.42);
    }
    *{box-sizing:border-box}
    body{
      margin:0;
            background:
                radial-gradient(circle at top, rgba(92,197,207,.16), transparent 30%),
                linear-gradient(180deg, #08131a 0%, #05090d 100%);
            color:var(--vault-cyan-soft);
            font-family:"Trebuchet MS", "Segoe UI", sans-serif;
      min-height:100vh;
            padding:24px;
            letter-spacing:.02em;
    }
    .panel{
            max-width:1280px;
      margin:0 auto;
            border:1px solid var(--vault-line);
            background:
                linear-gradient(180deg, rgba(16,40,51,.96), rgba(6,14,18,.98)),
                linear-gradient(90deg, rgba(255,255,255,.03), transparent 35%);
            box-shadow:var(--shadow), inset 0 0 0 1px rgba(255,255,255,.04);
            padding:20px;
            border-radius:18px;
      position:relative;
      overflow:hidden;
    }
    .panel::before{
      content:"";
      position:absolute;
      inset:0;
            background:
                linear-gradient(90deg, rgba(255,255,255,.04), transparent 18%),
                repeating-linear-gradient(to bottom, rgba(255,255,255,.02), rgba(255,255,255,.02) 1px, transparent 1px, transparent 5px);
      pointer-events:none;
    }
    .panel.tripped{
            border-color:rgba(255,105,97,.95);
            box-shadow:0 0 28px rgba(255,105,97,.34), inset 0 0 24px rgba(255,105,97,.16);
    }
    .row{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
        .title{font-size:1.45rem;font-weight:800;letter-spacing:.08em;color:var(--vault-cyan);text-transform:uppercase}
    .tube{
            width:16px;height:16px;border-radius:50%;background:var(--vault-gold);
            box-shadow:0 0 12px var(--vault-gold), 0 0 28px rgba(245,201,107,.66);
      animation:tubePulse var(--pulse-speed) infinite ease-in-out;
    }
        .badge{
            border:1px solid var(--vault-line);
            padding:8px 12px;
            border-radius:999px;
            background:rgba(109,245,255,.08);
            font-size:.85rem;
            text-transform:uppercase;
            letter-spacing:.08em;
        }
        .trip{color:#ff9f96}
    .console{
      margin-top:16px;
            min-height:240px;
            border:1px solid var(--vault-line);
      padding:12px;
      white-space:pre-wrap;
            background:linear-gradient(180deg, rgba(3,10,14,.88), rgba(7,18,23,.96));
      overflow:auto;
            border-radius:14px;
            font-family:"Lucida Console", "Courier New", monospace;
            color:#d6fcff;
    }
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:14px}
        .card{
            border:1px solid var(--vault-line);
            padding:12px;
            background:linear-gradient(180deg, rgba(19,50,64,.74), rgba(11,28,36,.88));
            border-radius:14px;
            box-shadow:inset 0 1px 0 rgba(255,255,255,.04);
        }
    .controls{margin-top:14px;gap:10px}
        .topline{display:flex;gap:16px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;margin-bottom:8px}
        .subtitle{font-size:.92rem;color:rgba(191,255,250,.76);text-transform:uppercase;letter-spacing:.12em}
                .game-shell{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;margin-top:18px;align-items:start}
                .viewport{padding:14px;background:linear-gradient(180deg, rgba(13,34,43,.98), rgba(8,16,21,.98))}
                .viewport-title{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px}
                .viewport-note{font-size:.84rem;color:rgba(191,255,250,.74)}
                .dossier-panel{
                    width:74px;
                    padding:10px;
                    overflow:hidden;
                    transition:width .2s ease, padding .2s ease, background .2s ease;
                }
                .dossier-panel[open]{
                    width:min(360px, 30vw);
                    padding:12px;
                }
                .dossier-summary{
                    display:flex;
                    align-items:center;
                    justify-content:center;
                    min-height:520px;
                    cursor:pointer;
                    user-select:none;
                    color:#ecffff;
                    font-weight:800;
                    letter-spacing:.12em;
                    text-transform:uppercase;
                    writing-mode:vertical-rl;
                    text-orientation:mixed;
                }
                .dossier-panel[open] .dossier-summary{
                    min-height:auto;
                    justify-content:space-between;
                    writing-mode:horizontal-tb;
                    text-orientation:initial;
                    margin-bottom:10px;
                }
                .dossier-summary::-webkit-details-marker{display:none}
                .dossier-summary::marker{content:""}
                .dossier-summary::after{
                    content:"OPEN";
                    margin-top:10px;
                    font-size:.72rem;
                    color:rgba(191,255,250,.72);
                    letter-spacing:.14em;
                }
                .dossier-panel[open] .dossier-summary::after{
                    content:"CLOSE";
                    margin-top:0;
                    margin-left:12px;
                }
                .dossier-body{display:grid;gap:0}
                .vault-stage{
                    position:relative;
                    min-height:520px;
                    overflow:hidden;
                    border:1px solid var(--vault-line);
                    border-radius:16px;
                    background:
                        radial-gradient(circle at 18% 8%, rgba(109,245,255,.1), transparent 18%),
                        repeating-linear-gradient(180deg, rgba(77,57,37,.12), rgba(77,57,37,.12) 42px, rgba(34,24,17,.18) 42px, rgba(34,24,17,.18) 88px),
                        linear-gradient(180deg, #2a1d14 0%, #1c140f 24%, #120e0b 100%);
                    box-shadow:inset 0 1px 0 rgba(255,255,255,.06), inset 0 -28px 46px rgba(0,0,0,.32);
                    perspective:900px;
                }
                .vault-stage::before{
                    content:"";
                    position:absolute;
                    inset:0;
                    background:
                        linear-gradient(90deg, rgba(0,0,0,.34) 0, rgba(0,0,0,.18) 6%, transparent 16%),
                        linear-gradient(180deg, rgba(255,255,255,.05), transparent 18%),
                        repeating-linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.02) 2px, transparent 2px, transparent 92px);
                    pointer-events:none;
                }
                .vault-stage::after{
                    content:"";
                    position:absolute;
                    left:0;
                    right:0;
                    bottom:14px;
                    height:10px;
                    background:linear-gradient(90deg, rgba(255,255,255,.14), rgba(255,255,255,.03));
                    pointer-events:none;
                }
                .vault-header-ribbon{
                    position:absolute;
                    left:24px;
                    right:24px;
                    top:20px;
                    display:flex;
                    justify-content:space-between;
                    gap:12px;
                    align-items:center;
                    padding:12px 16px;
                    border:1px solid rgba(109,245,255,.18);
                    border-radius:14px;
                    background:linear-gradient(90deg, rgba(8,23,29,.88), rgba(14,41,52,.72));
                    backdrop-filter:blur(6px);
                    z-index:4;
                }
                .vault-header-ribbon strong{font-size:1rem;letter-spacing:.08em;text-transform:uppercase;color:#f5fdff}
                .vault-header-ribbon span{font-size:.82rem;color:rgba(191,255,250,.74)}
                .vault-ribbon-copy{display:grid;gap:8px;min-width:0}
                .agent-camera-bar{
                    display:flex;
                    flex-wrap:wrap;
                    gap:8px;
                    align-items:center;
                }
                .agent-camera-select{
                    min-width:140px;
                    max-width:220px;
                    padding:6px 28px 6px 10px;
                    border-radius:999px;
                    border:1px solid var(--vault-line);
                    background:linear-gradient(180deg, rgba(20,56,72,.96), rgba(10,28,38,.98));
                    color:#efffff;
                    font:inherit;
                    font-size:.68rem;
                    letter-spacing:.08em;
                    text-transform:uppercase;
                }
                .agent-camera-bar button{
                    padding:6px 10px;
                    font-size:.66rem;
                    letter-spacing:.09em;
                    background:linear-gradient(180deg, rgba(34,86,108,.94), rgba(12,37,49,.96));
                }
                .agent-camera-bar button.active{
                    background:linear-gradient(180deg, rgba(120,206,145,.92), rgba(36,103,58,.96));
                    color:#06110b;
                    border-color:rgba(214,255,223,.44);
                    box-shadow:0 0 16px rgba(125,255,174,.16);
                }
                .agent-camera-status{
                    font-size:.7rem;
                    letter-spacing:.08em;
                    text-transform:uppercase;
                    color:rgba(228,255,248,.84);
                    white-space:nowrap;
                }
                    .vault-follow-dock{
                        position:absolute;
                        top:86px;
                        right:28px;
                        z-index:6;
                        display:flex;
                        flex-wrap:wrap;
                        align-items:center;
                        gap:10px;
                        max-width:min(560px, calc(100% - 56px));
                        padding:10px 12px;
                        border-radius:14px;
                        border:1px solid rgba(109,245,255,.22);
                        background:linear-gradient(180deg, rgba(6,21,27,.94), rgba(9,32,42,.90));
                        box-shadow:0 10px 28px rgba(0,0,0,.26), 0 0 20px rgba(109,245,255,.12);
                        backdrop-filter:blur(8px);
                    }
                    .vault-follow-dock.collapsed .vault-follow-body{
                        display:none;
                    }
                    .vault-follow-header{
                        width:100%;
                        display:flex;
                        align-items:center;
                        justify-content:space-between;
                        gap:10px;
                    }
                    .vault-follow-title{
                        font-size:.72rem;
                        letter-spacing:.1em;
                        text-transform:uppercase;
                        color:rgba(239,255,255,.84);
                    }
                    .vault-follow-body{
                        width:100%;
                        display:grid;
                        gap:10px;
                    }
                    .vault-follow-controls{
                        display:flex;
                        flex-wrap:wrap;
                        align-items:center;
                        gap:10px;
                    }
                    .vault-follow-zoom{
                        display:flex;
                        flex-wrap:wrap;
                        align-items:center;
                        gap:8px;
                    }
                    .vault-follow-dock button{
                        padding:9px 14px;
                        font-size:.72rem;
                        letter-spacing:.1em;
                        background:linear-gradient(180deg, rgba(123,217,146,.96), rgba(47,120,69,.98));
                        color:#04110a;
                        border-color:rgba(223,255,230,.42);
                        box-shadow:0 0 18px rgba(125,255,174,.18);
                    }
                    .vault-follow-dock button.active{
                        background:linear-gradient(180deg, rgba(255,212,128,.96), rgba(174,117,38,.98));
                        color:#1b1204;
                        border-color:rgba(255,233,186,.46);
                        box-shadow:0 0 18px rgba(255,214,117,.18);
                    }
                    .vault-follow-copy{
                        font-size:.7rem;
                        letter-spacing:.08em;
                        text-transform:uppercase;
                        color:rgba(232,255,249,.76);
                    }
                    .vault-follow-dock .follow-collapse-button{
                        min-width:40px;
                        padding:8px 12px;
                        background:linear-gradient(180deg, rgba(32,76,96,.96), rgba(14,35,46,.98));
                        color:#efffff;
                        border-color:rgba(109,245,255,.26);
                        box-shadow:none;
                    }
                    .vault-follow-dock .follow-zoom-button,
                    .vault-follow-dock .follow-zoom-reset{
                        min-width:42px;
                        padding:8px 12px;
                        background:linear-gradient(180deg, rgba(32,76,96,.96), rgba(14,35,46,.98));
                        color:#efffff;
                        border-color:rgba(109,245,255,.26);
                        box-shadow:none;
                    }
                    .vault-follow-label{
                        font-size:.68rem;
                        letter-spacing:.08em;
                        text-transform:uppercase;
                        color:rgba(232,255,249,.72);
                    }
                    .vault-follow-zoom-value{
                        min-width:64px;
                        font-size:.72rem;
                        letter-spacing:.08em;
                        text-transform:uppercase;
                        color:rgba(239,255,255,.88);
                    }
                    .vault-follow-dock .agent-camera-select{
                        min-width:180px;
                        max-width:260px;
                    }
                .vault-camera-hint{
                    position:absolute;
                    left:32px;
                    bottom:32px;
                    z-index:5;
                    max-width:min(420px, calc(100% - 64px));
                    padding:9px 12px;
                    border-radius:12px;
                    border:1px solid rgba(109,245,255,.16);
                    background:linear-gradient(90deg, rgba(8,23,29,.9), rgba(14,41,52,.76));
                    font-size:.72rem;
                    letter-spacing:.06em;
                    color:rgba(228,255,248,.82);
                    box-shadow:0 12px 24px rgba(0,0,0,.18);
                    backdrop-filter:blur(6px);
                }
                .vault-grid{
                    position:absolute;
                    left:24px;
                    right:24px;
                    top:92px;
                    bottom:24px;
                    overflow:hidden;
                    cursor:grab;
                    touch-action:none;
                    user-select:none;
                }
                .vault-grid.panning{cursor:grabbing}
                .vault-content{
                    position:absolute;
                    left:0;
                    top:0;
                    transform-origin:0 0;
                    will-change:transform;
                }
                .vault-agents{position:absolute;inset:0;pointer-events:none;z-index:6}
                .vault-room{
                    position:absolute;
                    border-radius:18px 18px 8px 8px;
                    transform-style:preserve-3d;
                    transform:translateZ(0);
                    box-shadow:0 18px 28px rgba(0,0,0,.24);
                    overflow:hidden;
                    --room-art-image:none;
                }
                .vault-room::before{
                    content:"";
                    position:absolute;
                    inset:0;
                    border-radius:inherit;
                    border:1px solid rgba(255,255,255,.16);
                    pointer-events:none;
                    z-index:3;
                }
                .room-shell{
                    position:absolute;
                    inset:0;
                    background:
                        linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.01)),
                        linear-gradient(90deg, rgba(0,0,0,.24), transparent 12%, transparent 88%, rgba(0,0,0,.18));
                }
                .room-ceiling{
                    position:absolute;
                    left:0;
                    right:0;
                    top:0;
                    height:14px;
                    border-radius:14px 14px 0 0;
                    background:linear-gradient(180deg, rgba(255,255,255,.24), rgba(255,255,255,.05));
                    opacity:.9;
                    transform:none;
                }
                .room-backdrop{
                    position:absolute;
                    left:14px;
                    right:26px;
                    top:18px;
                    bottom:26px;
                    border-radius:12px 8px 4px 4px;
                    overflow:hidden;
                    box-shadow:inset 0 1px 0 rgba(255,255,255,.12), inset 0 -18px 18px rgba(0,0,0,.24);
                    z-index:1;
                }
                .room-art{
                    position:absolute;
                    inset:0;
                    background-image:
                        linear-gradient(180deg, rgba(255,255,255,.1), rgba(0,0,0,.18)),
                        var(--room-art-image);
                    background-size:cover;
                    background-position:center;
                    opacity:.78;
                    mix-blend-mode:normal;
                    filter:saturate(1.18) contrast(1.08);
                }
                .room-pattern{
                    position:absolute;
                    inset:0;
                    background:
                        radial-gradient(circle at 25% 25%, rgba(255,255,255,.12), transparent 22%),
                        repeating-linear-gradient(135deg, rgba(255,255,255,.04), rgba(255,255,255,.04) 8px, transparent 8px, transparent 20px);
                    opacity:.18;
                }
                .room-wall-left,
                .room-wall-right{
                    position:absolute;
                    top:18px;
                    bottom:26px;
                    width:14px;
                    z-index:2;
                    overflow:hidden;
                    box-shadow:inset 0 0 0 1px rgba(255,255,255,.08);
                }
                .room-wall-left{
                    left:0;
                    transform:none;
                    border-radius:12px 0 0 4px;
                }
                .room-wall-right{
                    right:12px;
                    width:16px;
                    transform:none;
                    border-radius:0 8px 4px 0;
                }
                .room-wall-left::before,
                .room-wall-right::before{
                    content:"";
                    position:absolute;
                    inset:0;
                    background-image:
                        linear-gradient(180deg, rgba(255,255,255,.08), rgba(0,0,0,.3)),
                        var(--room-art-image);
                    background-size:cover;
                    background-position:center;
                    opacity:.72;
                    filter:saturate(1.1) contrast(1.04);
                }
                .room-wall-left::after,
                .room-wall-right::after{
                    content:"";
                    position:absolute;
                    inset:0;
                    background:linear-gradient(90deg, rgba(0,0,0,.28), rgba(255,255,255,.06));
                    mix-blend-mode:overlay;
                }
                .room-floor{
                    position:absolute;
                    left:14px;
                    right:24px;
                    bottom:10px;
                    height:16px;
                    border-radius:2px 2px 8px 8px;
                    transform:none;
                    opacity:.96;
                    overflow:hidden;
                    z-index:2;
                }
                .room-floor::before{
                    content:"";
                    position:absolute;
                    inset:0;
                    background-image:
                        linear-gradient(180deg, rgba(255,255,255,.06), rgba(0,0,0,.28)),
                        var(--room-art-image);
                    background-size:cover;
                    background-position:center;
                    filter:saturate(1.08) contrast(1.02);
                }
                .room-floor::after{
                    content:"";
                    position:absolute;
                    inset:0;
                    background:repeating-linear-gradient(90deg, rgba(255,255,255,.08), rgba(255,255,255,.08) 10px, rgba(0,0,0,.06) 10px, rgba(0,0,0,.06) 22px);
                    opacity:.26;
                }
                .room-decal{
                    position:absolute;
                    left:30px;
                    right:30px;
                    bottom:20px;
                    height:6px;
                    border-radius:999px;
                    opacity:.8;
                    filter:blur(.2px);
                    z-index:3;
                }
                .room-labels{
                    position:absolute;
                    left:14px;
                    right:14px;
                    top:16px;
                    display:flex;
                    justify-content:space-between;
                    gap:8px;
                    z-index:2;
                }
                .room-name{font-size:.76rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#f7ffff}
                .room-style{font-size:.64rem;letter-spacing:.08em;text-transform:uppercase;color:rgba(247,255,255,.7)}
                .room-occupancy{
                    position:absolute;
                    left:14px;
                    right:14px;
                    bottom:12px;
                    display:flex;
                    justify-content:space-between;
                    align-items:flex-end;
                    z-index:2;
                    font-size:.68rem;
                    text-transform:uppercase;
                    letter-spacing:.08em;
                    color:rgba(247,255,255,.76);
                }
                .room-code{font-family:"Lucida Console", "Courier New", monospace;color:rgba(247,255,255,.9)}
                .room-pop{display:flex;gap:8px;align-items:center}
                .room-pop span{width:6px;height:6px;border-radius:50%;background:#f5c96b;box-shadow:0 0 10px rgba(245,201,107,.6)}
                .room-pop span.off{background:rgba(255,255,255,.24);box-shadow:none}
                .room-light-strip{
                    position:absolute;
                    left:16px;
                    right:16px;
                    top:44px;
                    height:3px;
                    border-radius:999px;
                    opacity:.9;
                    z-index:2;
                }
                .room-machine{
                    position:absolute;
                    width:28%;
                    height:34%;
                    right:34px;
                    bottom:28px;
                    border-radius:14px;
                    background:linear-gradient(180deg, rgba(255,255,255,.2), rgba(0,0,0,.2));
                    box-shadow:0 10px 16px rgba(0,0,0,.18);
                    opacity:.78;
                    z-index:3;
                }
                .room-machine::after{
                    content:"";
                    position:absolute;
                    inset:18% 16%;
                    border-radius:10px;
                    border:1px solid rgba(255,255,255,.22);
                }
                .room-door{
                    position:absolute;
                    width:18px;
                    height:28px;
                    border-radius:10px 10px 4px 4px;
                    background:linear-gradient(180deg, rgba(255,255,255,.28), rgba(0,0,0,.32));
                    border:1px solid rgba(255,255,255,.18);
                    box-shadow:0 5px 10px rgba(0,0,0,.2);
                    z-index:4;
                }
                .room-door.left{left:-8px;top:50%;transform:translateY(-50%)}
                .room-door.right{right:2px;top:50%;transform:translateY(-50%)}
                .room-door.top{left:50%;top:-2px;transform:translateX(-50%) rotate(90deg)}
                .room-door.bottom{left:50%;bottom:-2px;transform:translateX(-50%) rotate(90deg)}
                .vault-connector{
                    position:absolute;
                    z-index:1;
                    pointer-events:none;
                    --connector-art-image:none;
                }
                .vault-connector.hallway{
                    height:20px;
                    border-radius:10px;
                    background-image:
                        linear-gradient(180deg, rgba(255,255,255,.12), rgba(0,0,0,.24)),
                        var(--connector-art-image),
                        linear-gradient(180deg, rgba(95,97,104,.95), rgba(53,55,60,.98));
                    background-size:cover;
                    background-position:center;
                    box-shadow:inset 0 1px 0 rgba(255,255,255,.28), 0 8px 14px rgba(0,0,0,.16);
                }
                .vault-connector.hallway::before{
                    content:"";
                    position:absolute;
                    left:8px;
                    right:8px;
                    top:8px;
                    height:6px;
                    border-radius:999px;
                    background:repeating-linear-gradient(90deg, rgba(34,48,61,.46), rgba(34,48,61,.46) 8px, rgba(255,255,255,.08) 8px, rgba(255,255,255,.08) 20px);
                }
                .vault-connector.ladder{
                    width:24px;
                    border-radius:4px;
                    background-image:
                        linear-gradient(180deg, rgba(255,255,255,.08), rgba(0,0,0,.18)),
                        var(--connector-art-image),
                        linear-gradient(90deg, rgba(145,109,66,.95), rgba(97,65,32,.98));
                    background-size:cover;
                    background-position:center;
                    box-shadow:inset 0 1px 0 rgba(255,255,255,.22), 0 10px 14px rgba(0,0,0,.16);
                }
                .vault-connector.ladder::before{
                    content:"";
                    position:absolute;
                    left:6px;
                    right:6px;
                    top:8px;
                    bottom:8px;
                    background:repeating-linear-gradient(180deg, rgba(255,244,222,.8), rgba(255,244,222,.8) 3px, transparent 3px, transparent 18px);
                }
                .connector-door{
                    position:absolute;
                    width:14px;
                    height:26px;
                    border-radius:8px;
                    background:linear-gradient(180deg, rgba(255,255,255,.22), rgba(0,0,0,.28));
                    border:1px solid rgba(255,255,255,.16);
                }
                .hallway .connector-door.a{left:-4px;top:-2px}
                .hallway .connector-door.b{right:-4px;top:-2px}
                .ladder .connector-door.a{top:-4px;left:5px;transform:rotate(90deg)}
                .ladder .connector-door.b{bottom:-4px;left:5px;transform:rotate(90deg)}
                .vault-room.theme-reactor .room-backdrop{background:radial-gradient(circle at 50% 35%, rgba(123,255,210,.34), transparent 26%), linear-gradient(180deg, #234f46 0%, #14363d 100%)}
                .vault-room.theme-reactor .room-floor{background:linear-gradient(180deg, #26463f, #142823)}
                .vault-room.theme-reactor .room-decal,.vault-room.theme-reactor .room-light-strip{background:linear-gradient(90deg, #7dffca, #d2fff1)}
                .vault-room.theme-reactor .room-machine{background:linear-gradient(180deg, rgba(54,128,116,.82), rgba(20,61,55,.86))}
                .vault-room.theme-foundry .room-backdrop{background:radial-gradient(circle at 65% 28%, rgba(255,164,88,.24), transparent 22%), linear-gradient(180deg, #5c3024 0%, #2b1714 100%)}
                .vault-room.theme-foundry .room-floor{background:linear-gradient(180deg, #543127, #2b1814)}
                .vault-room.theme-foundry .room-decal,.vault-room.theme-foundry .room-light-strip{background:linear-gradient(90deg, #ffb75c, #ffd990)}
                .vault-room.theme-foundry .room-machine{background:linear-gradient(180deg, rgba(149,81,46,.84), rgba(71,34,21,.88))}
                .vault-room.theme-hydro .room-backdrop{background:radial-gradient(circle at 25% 25%, rgba(148,255,196,.2), transparent 24%), linear-gradient(180deg, #1d4d39 0%, #102922 100%)}
                .vault-room.theme-hydro .room-floor{background:linear-gradient(180deg, #214c39, #10251e)}
                .vault-room.theme-hydro .room-decal,.vault-room.theme-hydro .room-light-strip{background:linear-gradient(90deg, #8bf1a7, #dfffd0)}
                .vault-room.theme-hydro .room-machine{background:linear-gradient(180deg, rgba(71,138,97,.82), rgba(23,67,42,.88))}
                .vault-room.theme-archive .room-backdrop{background:linear-gradient(180deg, #3b2c55 0%, #1e1534 100%)}
                .vault-room.theme-archive .room-floor{background:linear-gradient(180deg, #34294d, #171127)}
                .vault-room.theme-archive .room-decal,.vault-room.theme-archive .room-light-strip{background:linear-gradient(90deg, #b894ff, #efe2ff)}
                .vault-room.theme-archive .room-machine{background:linear-gradient(180deg, rgba(97,71,150,.82), rgba(36,24,69,.88))}
                .vault-room.theme-command .room-backdrop{background:radial-gradient(circle at 50% 20%, rgba(130,210,255,.28), transparent 20%), linear-gradient(180deg, #204967 0%, #112537 100%)}
                .vault-room.theme-command .room-floor{background:linear-gradient(180deg, #23435a, #101e2d)}
                .vault-room.theme-command .room-decal,.vault-room.theme-command .room-light-strip{background:linear-gradient(90deg, #77d2ff, #d8f7ff)}
                .vault-room.theme-command .room-machine{background:linear-gradient(180deg, rgba(52,112,163,.82), rgba(20,49,76,.88))}
                .vault-room.theme-transit .room-backdrop{background:linear-gradient(180deg, #4a4d56 0%, #242730 100%)}
                .vault-room.theme-transit .room-floor{background:linear-gradient(180deg, #484b53, #20232a)}
                .vault-room.theme-transit .room-decal,.vault-room.theme-transit .room-light-strip{background:linear-gradient(90deg, #d0d7dd, #f4f8fb)}
                .vault-room.theme-transit .room-machine{background:linear-gradient(180deg, rgba(103,111,122,.82), rgba(37,42,49,.88))}
                .vault-room.locked{filter:saturate(.7)}
                .vault-room.locked .room-backdrop{box-shadow:inset 0 0 0 2px rgba(255,159,150,.55), inset 0 -18px 18px rgba(0,0,0,.24)}
                .vault-room.locked .room-light-strip,.vault-room.locked .room-decal{background:linear-gradient(90deg, #ff9f96, #ffd0ca)}
                .vault-room-layer{position:absolute;inset:0;z-index:2;pointer-events:none}
                .vault-signal-layer{position:absolute;inset:0;z-index:3;width:100%;height:100%;pointer-events:none;overflow:visible}
                .vault-room.boiler-room::after{
                    content:"";
                    position:absolute;
                    inset:-8px;
                    border-radius:22px 22px 12px 12px;
                    border:1px solid rgba(245,201,107,.48);
                    box-shadow:0 0 24px rgba(245,201,107,.22);
                    pointer-events:none;
                }
                .room-grid-badge{
                    padding:4px 8px;
                    border-radius:999px;
                    border:1px solid rgba(255,255,255,.16);
                    background:rgba(7,19,27,.62);
                    font-size:.58rem;
                    letter-spacing:.12em;
                    text-transform:uppercase;
                    color:rgba(245,253,255,.84);
                    white-space:nowrap;
                }
                .room-io{
                    position:absolute;
                    left:16px;
                    right:16px;
                    top:58px;
                    display:flex;
                    justify-content:space-between;
                    gap:12px;
                    z-index:3;
                    font-size:.56rem;
                    letter-spacing:.12em;
                    text-transform:uppercase;
                    color:rgba(231,248,255,.72);
                }
                .room-io span{
                    flex:1 1 0;
                    padding:4px 6px;
                    border-radius:999px;
                    border:1px solid rgba(255,255,255,.12);
                    background:rgba(7,19,27,.38);
                    text-align:center;
                }
                .room-lanes{
                    position:absolute;
                    left:18px;
                    right:84px;
                    bottom:42px;
                    display:grid;
                    gap:5px;
                    z-index:3;
                }
                .room-lane{
                    display:grid;
                    grid-template-columns:minmax(0,1fr) auto;
                    gap:8px;
                    align-items:center;
                    font-size:.56rem;
                    letter-spacing:.1em;
                    text-transform:uppercase;
                    color:rgba(241,252,255,.76);
                }
                .room-lane span{
                    display:block;
                    height:6px;
                    border-radius:999px;
                    background:linear-gradient(90deg, rgba(255,255,255,.22), rgba(255,255,255,.04));
                    overflow:hidden;
                    position:relative;
                }
                .room-lane span::after{
                    content:"";
                    position:absolute;
                    inset:0;
                    width:var(--lane-fill, 50%);
                    background:linear-gradient(90deg, rgba(109,245,255,.92), rgba(245,201,107,.82));
                    box-shadow:0 0 14px rgba(109,245,255,.18);
                }
                .room-terminal{
                    position:absolute;
                    width:74px;
                    min-height:34px;
                    padding:6px 7px;
                    border-radius:10px;
                    border:1px solid rgba(255,255,255,.15);
                    background:linear-gradient(180deg, rgba(8,20,28,.92), rgba(6,12,17,.92));
                    box-shadow:0 6px 12px rgba(0,0,0,.22);
                    z-index:4;
                }
                .room-terminal.primary{left:18px;bottom:82px}
                .room-terminal.secondary{right:24px;top:74px}
                .room-terminal-title{font-size:.52rem;letter-spacing:.12em;text-transform:uppercase;color:#f4fdff}
                .room-terminal-copy{margin-top:4px;font-size:.5rem;letter-spacing:.08em;color:rgba(220,246,255,.72)}
                .room-token-meter{
                    position:absolute;
                    left:18px;
                    right:24px;
                    bottom:26px;
                    height:8px;
                    border-radius:999px;
                    border:1px solid rgba(255,255,255,.12);
                    background:rgba(7,19,27,.38);
                    overflow:hidden;
                    z-index:3;
                }
                .room-token-meter span{
                    display:block;
                    height:100%;
                    width:var(--room-token-fill, 50%);
                    background:linear-gradient(90deg, rgba(109,245,255,.96), rgba(245,201,107,.84));
                    box-shadow:0 0 18px rgba(109,245,255,.16);
                }
                .room-signal-caption{
                    position:absolute;
                    left:18px;
                    right:18px;
                    bottom:10px;
                    display:flex;
                    justify-content:space-between;
                    gap:10px;
                    font-size:.52rem;
                    letter-spacing:.1em;
                    text-transform:uppercase;
                    color:rgba(224,248,255,.76);
                    z-index:3;
                }
                .room-signal-caption strong{font-size:.58rem;color:#f5fdff}
                .room-wire-port{
                    position:absolute;
                    width:12px;
                    height:12px;
                    border-radius:50%;
                    border:1px solid rgba(255,255,255,.22);
                    background:linear-gradient(180deg, rgba(109,245,255,.88), rgba(24,67,86,.92));
                    box-shadow:0 0 12px rgba(109,245,255,.22);
                    z-index:5;
                }
                .room-wire-port.left{left:-6px;top:50%;transform:translateY(-50%)}
                .room-wire-port.right{right:-6px;top:50%;transform:translateY(-50%)}
                .room-wire-port.top{left:50%;top:-6px;transform:translateX(-50%)}
                .room-wire-port.bottom{left:50%;bottom:-6px;transform:translateX(-50%)}
                .dweller{
                    position:absolute;
                    width:34px;
                    height:78px;
                    z-index:2;
                    pointer-events:auto;
                    cursor:pointer;
                    will-change:transform;
                }
                .dweller:focus-visible{outline:2px solid rgba(125,247,255,.85);outline-offset:4px;border-radius:12px}
                .dweller-rig{
                    position:absolute;
                    inset:0;
                    transform-origin:50% 72%;
                }
                .dweller.facing-left .dweller-rig{transform:scaleX(-1)}
                .dweller.is-tracked .dweller-tag{
                    background:rgba(122,255,170,.2);
                    border-color:rgba(186,255,210,.55);
                    color:#f6fff7;
                    box-shadow:0 0 12px rgba(125,255,174,.18);
                }
                .dweller.is-tracked .dweller-head,
                .dweller.is-tracked .dweller-body{
                    box-shadow:0 0 0 2px rgba(125,247,255,.2), 0 0 18px rgba(125,247,255,.18);
                }
                .dweller-shadow{
                    position:absolute;
                    left:50%;
                    bottom:8px;
                    width:28px;
                    height:10px;
                    transform:translateX(-50%);
                    border-radius:50%;
                    background:rgba(0,0,0,.3);
                    filter:blur(2px);
                }
                .dweller-limb{
                    position:absolute;
                    left:50%;
                    width:5px;
                    border-radius:999px;
                    transform-origin:50% 0%;
                    background:linear-gradient(180deg, rgba(29,37,52,.96), rgba(11,16,27,.94));
                }
                .dweller-arm{
                    top:28px;
                    height:22px;
                    z-index:1;
                }
                .dweller-arm.arm-a{transform:translateX(-11px) rotate(12deg)}
                .dweller-arm.arm-b{transform:translateX(6px) rotate(-12deg)}
                .dweller-leg{
                    bottom:10px;
                    height:24px;
                    z-index:1;
                }
                .dweller-leg.leg-a{transform:translateX(-8px) rotate(8deg)}
                .dweller-leg.leg-b{transform:translateX(3px) rotate(-8deg)}
                .dweller-body{
                    position:absolute;
                    left:50%;
                    bottom:14px;
                    width:16px;
                    height:30px;
                    transform:translateX(-50%);
                    border-radius:8px 8px 6px 6px;
                }
                .dweller-head{
                    position:absolute;
                    left:50%;
                    bottom:42px;
                    width:18px;
                    height:18px;
                    transform:translateX(-50%);
                    border-radius:50%;
                    background:#ffe7b8;
                    box-shadow:0 0 0 2px rgba(0,0,0,.08);
                }
                .dweller-crate{
                    position:absolute;
                    left:50%;
                    bottom:22px;
                    width:14px;
                    height:14px;
                    transform:translateX(6px);
                    border-radius:4px;
                    background:linear-gradient(180deg, #84f0ff, #2da8bd);
                    box-shadow:0 0 10px rgba(125,247,255,.28);
                }
                .dweller-tag{
                    position:absolute;
                    left:50%;
                    top:-4px;
                    transform:translateX(-50%);
                    padding:2px 6px;
                    border-radius:999px;
                    background:rgba(7,19,27,.8);
                    border:1px solid rgba(255,255,255,.14);
                    font-size:.58rem;
                    color:#ecffff;
                    font-family:"Lucida Console", "Courier New", monospace;
                    letter-spacing:.06em;
                    text-transform:uppercase;
                    white-space:nowrap;
                }
                .dweller.walk .dweller-body,.dweller.walk .dweller-head{animation:dwellerBob .56s ease-in-out infinite}
                .dweller.carry .dweller-body,.dweller.carry .dweller-head{animation:dwellerBob .72s ease-in-out infinite}
                .dweller.idle .dweller-body,.dweller.idle .dweller-head{animation:dwellerBob 2.2s ease-in-out infinite}
                .dweller.walk .arm-a,.dweller.walk .leg-b{animation:dwellerStride .56s ease-in-out infinite}
                .dweller.walk .arm-b,.dweller.walk .leg-a{animation:dwellerStride .56s ease-in-out infinite reverse}
                .dweller.carry .arm-a,.dweller.carry .leg-b{animation:dwellerStride .72s ease-in-out infinite}
                .dweller.carry .arm-b,.dweller.carry .leg-a{animation:dwellerStride .72s ease-in-out infinite reverse}
                .dweller.idle .dweller-arm{animation:dwellerIdleLimb 2.4s ease-in-out infinite}
                .dweller.idle .dweller-leg{animation:none}
                .dweller.walk .dweller-body{background:linear-gradient(180deg, #f5c96b, #b37d21)}
                .dweller.carry .dweller-body{background:linear-gradient(180deg, #8ef2ff, #238ea1)}
                .dweller.idle .dweller-body{background:linear-gradient(180deg, #f5f7ff, #98aac1)}
                .legend-list{display:grid;gap:8px;font-size:.88rem;color:#d8fbff}
                .room-style-rack{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}
                .room-style-chip{border:1px solid var(--vault-line);border-radius:12px;padding:8px;background:rgba(6,16,22,.72)}
                .room-style-thumb{width:100%;aspect-ratio:1.4/1;object-fit:cover;border-radius:8px;border:1px solid rgba(255,255,255,.1);background:#081116}
                .room-style-caption{margin-top:6px;font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:#dffcff}
        .legend-swatch{display:inline-block;width:12px;height:12px;margin-right:8px;vertical-align:middle}
        .asset-stack{display:grid;gap:12px;margin-top:12px}
                .asset-preview{width:100%;aspect-ratio:1/1;object-fit:cover;border:1px solid var(--vault-line);background:#081116;border-radius:12px}
                .asset-prompt{font-size:.8rem;opacity:.82;min-height:2.6em;color:#d8fbff}
        .subgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:14px}
        .tables{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:14px}
        table{width:100%;border-collapse:collapse;font-size:.88rem}
                th,td{border-bottom:1px solid rgba(109,245,255,.12);padding:6px;text-align:left;vertical-align:top}
                th{color:var(--vault-gold);font-size:.78rem;text-transform:uppercase;letter-spacing:.08em}
                .fault-unacked{color:#ff9f96}
                .stat-label{font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:rgba(191,255,250,.58);margin-bottom:8px}
                .stat-value{font-size:1.35rem;font-weight:700;color:#f5fdff}
                .section-chip{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;border:1px solid var(--vault-line);background:rgba(109,245,255,.06);font-size:.76rem;text-transform:uppercase;letter-spacing:.1em}
                .hud-bar{height:8px;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden;border:1px solid rgba(255,255,255,.06)}
                .hud-bar > span{display:block;height:100%;background:linear-gradient(90deg, #7df7ff, #f5c96b)}
    button{
            background:linear-gradient(180deg, rgba(37,89,111,.96), rgba(19,52,66,.96));
            color:#efffff;border:1px solid var(--vault-line);
            padding:9px 12px;cursor:pointer;font:inherit;border-radius:999px;
            text-transform:uppercase;font-size:.8rem;letter-spacing:.08em;
    }
        button:hover{box-shadow:0 0 14px rgba(109,245,255,.18)}
        .small{opacity:.82;font-size:.9rem;color:#d7fdff}
        @media (max-width: 980px){
            body{padding:14px}
            .game-shell{grid-template-columns:1fr}
                        .dossier-panel,.dossier-panel[open]{width:auto}
                        .dossier-summary{min-height:auto;writing-mode:horizontal-tb;text-orientation:initial;margin-bottom:10px}
                        .dossier-summary::after{content:"EXPAND";margin-top:0;margin-left:12px}
                        .dossier-panel[open] .dossier-summary::after{content:"COLLAPSE"}
                        .vault-stage{min-height:420px}
                        .vault-follow-dock{top:auto;left:24px;right:24px;bottom:78px;max-width:none}
                        .vault-follow-copy{display:none}
        }
    @keyframes tubePulse{
      0%,100%{transform:scale(1);opacity:.7}
      50%{transform:scale(1.18);opacity:1}
    }
        @keyframes dwellerBob{
            0%,100%{transform:translateX(-50%) translateY(0)}
            50%{transform:translateX(-50%) translateY(-4px)}
        }
        @keyframes dwellerStride{
            0%,100%{transform:var(--limb-rest) rotate(-18deg)}
            50%{transform:var(--limb-rest) rotate(18deg)}
        }
        @keyframes dwellerIdleLimb{
            0%,100%{transform:var(--limb-rest) rotate(0deg)}
            50%{transform:var(--limb-rest) rotate(4deg)}
        }
                .pixel-grid{
                        background:
                                radial-gradient(circle at 50% 18%, rgba(225,167,72,.18), transparent 26%),
                                linear-gradient(180deg, rgba(43,22,16,.92) 0%, rgba(12,8,6,.96) 100%);
                }
                .viewport-crt{
                        z-index:4;
                        mix-blend-mode:screen;
                        opacity:.62;
                }
                .pixel-grid::before,.pixel-grid::after{content:"";position:absolute;inset:0;pointer-events:none}
                .pixel-grid::before{background:repeating-linear-gradient(to bottom, rgba(255,190,110,.04) 0 2px, rgba(0,0,0,0) 2px 4px);opacity:.72;z-index:1}
                .pixel-grid::after{background:radial-gradient(circle at center, rgba(0,0,0,0) 46%, rgba(0,0,0,.42) 100%);z-index:1}
                .vault-content.pixel-world{transform-origin:0 0;image-rendering:pixelated}
                .pixel-layer,.pixel-agents,.pixel-occluders,.pixel-fx{position:absolute;inset:0}
                .pixel-layer{z-index:1;opacity:.94;filter:saturate(.92) contrast(1.02)}
                .pixel-occluders{z-index:4}
                .pixel-fx{z-index:5}
                .pixel-agents{z-index:6}
                .pixel-tile,.pixel-occluder,.pixel-boiler,.steam-burst{position:absolute;transform-style:preserve-3d}
                .pixel-diamond{position:absolute;left:0;top:0;width:100%;height:100%;clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%);border:1px solid rgba(0,0,0,.55);box-shadow:inset 0 0 0 1px rgba(255,230,170,.08)}
                .pixel-tile-top{background:linear-gradient(135deg, rgba(255,238,190,.16), rgba(0,0,0,0) 58%), repeating-linear-gradient(135deg, rgba(255,220,150,.08) 0 4px, rgba(0,0,0,0) 4px 8px), var(--tile-base, #6c5038)}
                .pixel-tile.locked .pixel-tile-top{background:linear-gradient(135deg, rgba(255,174,164,.18), rgba(0,0,0,0) 58%), repeating-linear-gradient(135deg, rgba(255,120,108,.14) 0 4px, rgba(0,0,0,0) 4px 8px), var(--tile-base, #6c5038)}
                .pixel-tile-riser{top:46%;height:calc(100% + var(--wall-height, 28px));clip-path:polygon(0 0,50% 54%,50% 100%,0 46%);background:linear-gradient(180deg, var(--tile-shadow, #1f1610), rgba(0,0,0,.82));opacity:.95}
                .pixel-tile-riser.right{left:50%;clip-path:polygon(50% 54%,100% 0,100% 46%,50% 100%);background:linear-gradient(180deg, rgba(0,0,0,.2), var(--tile-shadow, #1f1610))}
                .pixel-grit{position:absolute;inset:10% 16%;clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%);background:radial-gradient(circle at 28% 26%, rgba(164,201,109,.35), rgba(0,0,0,0) 38%), repeating-linear-gradient(135deg, rgba(0,0,0,.12) 0 3px, rgba(255,255,255,.03) 3px 6px);opacity:.58;mix-blend-mode:multiply}
                .pixel-clutter,.pixel-occluder .pixel-clutter{position:absolute;image-rendering:pixelated;border:1px solid rgba(0,0,0,.45)}
                .pixel-clutter.pipe{left:52%;top:18%;width:14px;height:44px;background:linear-gradient(180deg, #99774e, #42311e);box-shadow:-18px 12px 0 0 #5c4431}
                .pixel-clutter.moss{left:12%;top:14%;width:26px;height:16px;background:#567545;box-shadow:18px 10px 0 0 #415937, 34px 2px 0 0 #6e8e58}
                .pixel-clutter.crate{left:54%;top:26%;width:20px;height:18px;background:#6f4d2e;box-shadow:inset 0 0 0 2px rgba(255,230,180,.08)}
                .pixel-occluder{width:68px;height:68px}
                .pixel-occluder .pixel-clutter{left:18px;top:8px;width:30px;height:44px;background:linear-gradient(180deg, rgba(126,98,72,.95), rgba(37,25,18,.96));box-shadow:20px 16px 0 0 rgba(72,52,36,.9), -12px 24px 0 0 rgba(69,92,51,.85)}
                .pixel-boiler{width:116px;height:132px;filter:drop-shadow(0 14px 18px rgba(0,0,0,.45))}
                .pixel-boiler-body{position:absolute;inset:18px 24px 18px 24px;background:linear-gradient(180deg, #8b562d 0%, #5e311d 44%, #26130f 100%);border:3px solid #2d180f;box-shadow:inset 0 0 0 3px rgba(255,198,129,.18), inset 0 -10px 0 rgba(0,0,0,.25)}
                .pixel-boiler-gauge,.pixel-boiler-valve,.pixel-boiler-door,.pixel-boiler-pipe{position:absolute;border:2px solid rgba(29,14,10,.92);background:#b9823e}
                .pixel-boiler-gauge{left:38px;top:6px;width:40px;height:40px;border-radius:50%;background:radial-gradient(circle at 50% 48%, #f6d89c 0 44%, #6d471f 45% 100%)}
                .pixel-boiler-needle{position:absolute;left:18px;top:18px;width:16px;height:3px;background:#8f120f;transform-origin:2px 50%}
                .pixel-boiler-door{left:37px;top:56px;width:42px;height:44px;background:linear-gradient(180deg, #5b2e1a, #311711);box-shadow:inset 0 0 0 2px rgba(255,188,96,.12)}
                .pixel-boiler-pipe{left:84px;top:34px;width:20px;height:58px;background:linear-gradient(180deg, #776554, #3a2e24)}
                .pixel-boiler-valve{left:82px;top:20px;width:24px;height:24px;border-radius:50%;background:#b2432f}
                .pixel-boiler-valve::before,.pixel-boiler-valve::after{content:"";position:absolute;inset:10px -6px;background:#d0a368}
                .pixel-boiler-valve::after{inset:-6px 10px}
                .pixel-boiler-fire{position:absolute;left:42px;top:72px;width:32px;height:18px;background:linear-gradient(180deg, rgba(255,228,125,.95), rgba(211,87,22,.95));box-shadow:0 0 18px rgba(255,134,43,.45);opacity:var(--boiler-fire, .42)}
                .steam-burst{width:10px;height:10px;background:rgba(226,226,214,.82);box-shadow:12px -8px 0 0 rgba(210,210,199,.58), -10px -12px 0 0 rgba(210,210,199,.44), 18px -22px 0 0 rgba(210,210,199,.32);opacity:calc(.18 + var(--steam-intensity, .2));animation:steamDrift 1.8s linear infinite}
                .pixel-fx.flashover .steam-burst{opacity:calc(.42 + var(--steam-intensity, .2));filter:drop-shadow(0 0 16px rgba(255,181,86,.38))}
                .vault-signal-path{fill:none;stroke-width:3.5;stroke-linecap:round;stroke-dasharray:10 9;filter:drop-shadow(0 0 10px rgba(109,245,255,.18));opacity:.9}
                .vault-signal-node{stroke:rgba(255,255,255,.42);stroke-width:1.2}
                .vault-signal-label{font-size:11px;letter-spacing:.16em;text-transform:uppercase;fill:rgba(240,252,255,.84)}
                .teleprinter-console{font-family:"VT323", "Courier New", monospace;background:linear-gradient(180deg, rgba(16,10,7,.95), rgba(6,4,3,.98));border:2px solid rgba(188,134,66,.46);color:#ffbf72;letter-spacing:.04em;text-shadow:0 0 8px rgba(255,186,104,.14);min-height:200px}
                .tele-line{min-height:1.05em;white-space:pre-wrap}
                .tele-line.typing::after{content:"_";animation:teleBlink .65s steps(1) infinite}
                @keyframes steamDrift{0%{transform:translate3d(0,0,0) scale(.92)}100%{transform:translate3d(8px,-56px,0) scale(1.38)}}
                @keyframes teleBlink{0%,49%{opacity:1}50%,100%{opacity:0}}
  </style>
</head>
<body>
  <div id="panel" class="panel">
    <div class="topline">
      <div>
                <div class="title">ORBSTUDIO // Pixel Grit Control Deck</div>
                <div class="subtitle">Isometric caveworks · rusted boiler hall · analog teleprinter command surface</div>
      </div>
      <div class="row">
        <div class="section-chip">Live Sidecar</div>
        <div id="tube" class="tube"></div>
        <div id="mode" class="badge">Reactor Stable</div>
      </div>
    </div>

        <div class="game-shell">
            <div class="card viewport">
                <div class="viewport-title">
                    <strong>Underground Tilemap</strong>
                    <span class="viewport-note">Pixel-cut isometric blocks, boiler-centered lighting, foreground occluders, and hand-drafted cave routing.</span>
                </div>
                <div id="vaultScene" class="vault-stage">
                    <div class="crt-overlay viewport-crt"></div>
                    <div class="vault-header-ribbon">
                        <div class="vault-ribbon-copy">
                            <strong>Seattle Underground // Live Cutaway</strong>
                            <span>Manual-drafted tiles stack like Xrefs: floor, riser, clutter, actors, steam, and foreground scrap.</span>
                            <div class="agent-camera-bar">
                                <button id="trackAgentToggle" data-track-agent-toggle type="button" onclick="toggleAgentTracking()">Follow Agent</button>
                                <select id="trackAgentSelect" data-track-agent-select class="agent-camera-select" onchange="selectTrackedAgent(this.value)">
                                    <option value="">No Agents</option>
                                </select>
                                <button id="trackAgentPrev" type="button" onclick="cycleTrackedAgent(-1)">Prev Agent</button>
                                <button id="trackAgentNext" type="button" onclick="cycleTrackedAgent(1)">Next Agent</button>
                                <span id="trackedAgentLabel" class="agent-camera-status">Camera: manual</span>
                            </div>
                        </div>
                        <span id="activePatrolLabel">Active patrol: idle</span>
                    </div>
                    <div class="vault-follow-dock">
                        <div class="vault-follow-header">
                            <span class="vault-follow-title">Follow Menu</span>
                            <button id="followMenuToggle" class="follow-collapse-button" type="button" onclick="toggleFollowMenu()" aria-expanded="true">Hide</button>
                        </div>
                        <div id="vaultFollowBody" class="vault-follow-body">
                            <div class="vault-follow-controls">
                                <button id="followAgentButton" data-track-agent-toggle type="button" onclick="toggleAgentTracking()">Follow Agent</button>
                                <span class="vault-follow-label">Select Agent</span>
                                <select id="followAgentSelect" data-track-agent-select class="agent-camera-select" onchange="selectTrackedAgent(this.value)">
                                    <option value="">No Agents</option>
                                </select>
                            </div>
                            <div class="vault-follow-zoom">
                                <span class="vault-follow-label">Follow Zoom</span>
                                <button class="follow-zoom-button" type="button" onclick="adjustTrackedZoom(-0.45)">-</button>
                                <span id="followZoomValue" class="vault-follow-zoom-value">5.6x</span>
                                <button class="follow-zoom-button" type="button" onclick="adjustTrackedZoom(0.45)">+</button>
                                <button class="follow-zoom-reset" type="button" onclick="resetTrackedZoom()">Reset</button>
                            </div>
                            <span class="vault-follow-copy">Camera lock for the selected dweller</span>
                        </div>
                    </div>
                    <div id="vaultGrid" class="vault-grid pixel-grid"></div>
                    <div id="vaultCameraHint" class="vault-camera-hint">Drag to pan, wheel to zoom, or lock onto a dweller. Dithering acts like a digital screen-door effect over the cave light.</div>
                </div>
            </div>
            <details class="card dossier-panel">
                <summary class="dossier-summary">Overseer Dossier</summary>
                <div class="dossier-body">
                    <div class="legend-list" style="margin-top:10px">
                        <div><span class="legend-swatch" style="background:#204967"></span>Command / reactor-grade room themes</div>
                        <div><span class="legend-swatch" style="background:#5c3024"></span>Foundry / heavy industry rooms</div>
                        <div><span class="legend-swatch" style="background:#1d4d39"></span>Hydro / bio-support rooms</div>
                        <div><span class="legend-swatch" style="background:#d0d7dd"></span>Doors, hallways, and ladder shafts</div>
                        <div><span class="legend-swatch" style="background:#f5c96b"></span>Dweller</div>
                        <div><span class="legend-swatch" style="background:#ff9f96"></span>Locked path</div>
                    </div>
                    <div style="margin-top:14px">
                        <div class="stat-label">Vault Load</div>
                        <div class="hud-bar"><span id="loadBar" style="width:0%"></span></div>
                    </div>
                    <div class="asset-stack">
                        <div>
                            <div class="row" style="margin-bottom:8px"><strong>Wall Blueprint</strong><button onclick="sendCommand('generate-texture')">Forge Texture</button></div>
                            <img id="texturePreview" class="asset-preview" alt="Generated texture preview" />
                            <div id="texturePrompt" class="asset-prompt">No generated blueprint texture yet.</div>
                        </div>
                        <div>
                            <div class="row" style="margin-bottom:8px"><strong>Dweller Portrait</strong><button onclick="sendCommand('generate-character')">Forge Dweller</button></div>
                            <img id="characterPreview" class="asset-preview" alt="Generated character preview" />
                            <div id="characterPrompt" class="asset-prompt">No generated dweller portrait yet.</div>
                        </div>
                        <div>
                            <div class="row" style="margin-bottom:8px"><strong>Room Style Pack</strong><button onclick="sendCommand('generate-room-styles')">Forge Rooms</button></div>
                            <div id="roomStyleRack" class="room-style-rack"></div>
                        </div>
                    </div>
                </div>
            </details>
        </div>

    <div class="grid">
      <div class="card"><div class="stat-label">Reactor Load</div><div id="pressure" class="stat-value">0</div></div>
      <div class="card"><div class="stat-label">Flow Rate</div><div id="velocity" class="stat-value">0.00</div></div>
      <div class="card"><div class="stat-label">Power Route</div><div id="bypass" class="stat-value">OFF</div></div>
      <div class="card"><div class="stat-label">Dwellers</div><div id="agents" class="stat-value">0</div></div>
      <div class="card"><div class="stat-label">Task Stack</div><div id="queueDepth" class="stat-value">0</div></div>
      <div class="card"><div class="stat-label">Last Order</div><div id="lastCommand" class="stat-value">idle</div></div>
    </div>

    <div class="row controls">
      <button onclick="sendCommand('save-state')">SAVE STATE</button>
            <button onclick="sendCommand('patch-config')">PATCH GAME.INI</button>
            <button onclick="sendCommand('rollback-config')">ROLLBACK CONFIG</button>
      <button onclick="sendCommand('enqueue-demo')">QUEUE DEMO</button>
      <button onclick="sendCommand('dispatch-next')">DISPATCH NEXT</button>
            <button onclick="sendCommand('process-queue')">PROCESS QUEUE</button>
            <button onclick="sendCommand('acknowledge-faults')">ACK FAULTS</button>
            <button onclick="sendCommand('bootstrap-report')">BOOT REPORT</button>
            <button onclick="sendCommand('health-check')">HEALTH CHECK</button>
            <button onclick="sendCommand('set-recovery-policy')">CYCLE POLICY</button>
            <button onclick="sendCommand('clear-stale-trip')">CLEAR STALE TRIP</button>
      <button onclick="sendCommand('trip-boiler')">TRIP BOILER</button>
      <button onclick="sendCommand('reset-boiler')">RESET BOILER</button>
    </div>

        <div class="subgrid">
            <div class="card"><div class="stat-label">Finished Orders</div><div id="completedJobs" class="stat-value">0</div></div>
            <div class="card"><div class="stat-label">Launch Path</div><div id="launcherPath">pending</div></div>
            <div class="card"><div class="stat-label">Recovery Trace</div><div id="recoveryState">nominal</div></div>
            <div class="card"><div class="stat-label">Recovery Policy</div><div id="recoveryPolicy">auto-reset</div></div>
            <div class="card"><div class="stat-label">Auto Director</div><div id="autonomousMode" class="stat-value">enabled</div></div>
            <div class="card"><div class="stat-label">Current Patrol</div><div id="autonomousTask">idle</div></div>
        </div>

        <div class="tables">
            <div class="card">
                <strong>Task Board</strong>
                <table>
                    <thead><tr><th>Task</th><th>Priority</th></tr></thead>
                    <tbody id="queueTable"><tr><td colspan="2">No queued jobs</td></tr></tbody>
                </table>
            </div>
            <div class="card">
                <strong>Dweller History</strong>
                <table>
                    <thead><tr><th>Task</th><th>Agent</th></tr></thead>
                    <tbody id="historyTable"><tr><td colspan="2">No completed jobs</td></tr></tbody>
                </table>
            </div>
            <div class="card">
                <strong>Locked Corridors</strong>
                <table>
                    <thead><tr><th>Agent</th><th>Cells</th></tr></thead>
                    <tbody id="reservationTable"><tr><td colspan="2">No reservations</td></tr></tbody>
                </table>
            </div>
            <div class="card">
                <strong>Incident Rack</strong>
                <table>
                    <thead><tr><th>Fault</th><th>Status</th></tr></thead>
                    <tbody id="faultTable"><tr><td colspan="2">No faults logged</td></tr></tbody>
                </table>
            </div>
        </div>

        <div id="console" class="console teleprinter-console">Waiting for overseer feed...</div>
  </div>

  <script>
    const wsScheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${wsScheme}://${location.host}/ws/teleprinter`);
    const panel = document.getElementById('panel');
    const consoleEl = document.getElementById('console');
    const pressureEl = document.getElementById('pressure');
    const velocityEl = document.getElementById('velocity');
    const bypassEl = document.getElementById('bypass');
    const agentsEl = document.getElementById('agents');
    const queueDepthEl = document.getElementById('queueDepth');
    const completedJobsEl = document.getElementById('completedJobs');
    const launcherPathEl = document.getElementById('launcherPath');
    const recoveryStateEl = document.getElementById('recoveryState');
    const recoveryPolicyEl = document.getElementById('recoveryPolicy');
    const autonomousModeEl = document.getElementById('autonomousMode');
    const autonomousTaskEl = document.getElementById('autonomousTask');
    const queueTableEl = document.getElementById('queueTable');
    const historyTableEl = document.getElementById('historyTable');
    const reservationTableEl = document.getElementById('reservationTable');
    const faultTableEl = document.getElementById('faultTable');
    const texturePreviewEl = document.getElementById('texturePreview');
    const texturePromptEl = document.getElementById('texturePrompt');
    const characterPreviewEl = document.getElementById('characterPreview');
    const characterPromptEl = document.getElementById('characterPrompt');
    const roomStyleRackEl = document.getElementById('roomStyleRack');
    const lastCommandEl = document.getElementById('lastCommand');
    const modeEl = document.getElementById('mode');
    const loadBarEl = document.getElementById('loadBar');
    const tubeEl = document.getElementById('tube');
    const vaultGridEl = document.getElementById('vaultGrid');
    const activePatrolLabelEl = document.getElementById('activePatrolLabel');
    const trackAgentToggleEls = Array.from(document.querySelectorAll('[data-track-agent-toggle]'));
    const trackAgentSelectEls = Array.from(document.querySelectorAll('[data-track-agent-select]'));
    const trackAgentPrevEl = document.getElementById('trackAgentPrev');
    const trackAgentNextEl = document.getElementById('trackAgentNext');
    const trackedAgentLabelEl = document.getElementById('trackedAgentLabel');
    const vaultCameraHintEl = document.getElementById('vaultCameraHint');
    const vaultFollowDockEl = document.querySelector('.vault-follow-dock');
    const followMenuToggleEl = document.getElementById('followMenuToggle');
    const followZoomValueEl = document.getElementById('followZoomValue');
    const consoleQueue = [];
    let consoleTyping = false;
    let latestPayload = null;
    let sceneLayoutKey = '';
    let sceneAnimationHandle = 0;
    const vaultViewState = {
        fitZoom: 1,
        userZoom: 1,
        panX: 0,
        panY: 0,
        layoutWidth: 0,
        layoutHeight: 0,
        pointerId: null,
        startPanX: 0,
        startPanY: 0,
        startPointerX: 0,
        startPointerY: 0,
        trackingEnabled: false,
        trackedAgentId: '',
        trackedZoomMin: 2.2,
        trackedZoomDefault: 5.6,
        trackedZoomMax: 8.6,
        maxUserZoom: 8,
        trackedZoomMultiplier: 5.6,
        renderedPanX: 0,
        renderedPanY: 0,
        renderedZoom: 1,
        followLerp: 0.18,
        followMenuCollapsed: false,
    };

    function clampTrackedZoom(nextZoom){
        return Math.min(vaultViewState.trackedZoomMax, Math.max(vaultViewState.trackedZoomMin, nextZoom));
    }

    function syncFollowMenuUI(){
        if (vaultFollowDockEl) {
            vaultFollowDockEl.classList.toggle('collapsed', vaultViewState.followMenuCollapsed);
        }
        if (followMenuToggleEl) {
            followMenuToggleEl.textContent = vaultViewState.followMenuCollapsed ? 'Show' : 'Hide';
            followMenuToggleEl.setAttribute('aria-expanded', vaultViewState.followMenuCollapsed ? 'false' : 'true');
        }
        if (followZoomValueEl) {
            followZoomValueEl.textContent = `${vaultViewState.trackedZoomMultiplier.toFixed(1)}x`;
        }
    }

    function toggleFollowMenu(){
        vaultViewState.followMenuCollapsed = !vaultViewState.followMenuCollapsed;
        syncFollowMenuUI();
    }

    function adjustTrackedZoom(delta){
        vaultViewState.trackedZoomMultiplier = clampTrackedZoom(vaultViewState.trackedZoomMultiplier + delta);
        syncFollowMenuUI();
        renderVaultScene();
    }

    function resetTrackedZoom(){
        vaultViewState.trackedZoomMultiplier = vaultViewState.trackedZoomDefault;
        syncFollowMenuUI();
        renderVaultScene();
    }

    function cellToIso(cellX, cellY, projection, layoutOrigin){
        const tileWidth = Number((projection && projection.tile_width) || 64);
        const tileHeight = Number((projection && projection.tile_height) || 32);
        return {
            x: layoutOrigin.x + (cellX - cellY) * (tileWidth * 0.5),
            y: layoutOrigin.y + (cellX + cellY) * (tileHeight * 0.5),
        };
    }

    function clampVaultPan(panX, panY, totalZoom){
        const rect = vaultGridEl.getBoundingClientRect();
        const scaledWidth = vaultViewState.layoutWidth * totalZoom;
        const scaledHeight = vaultViewState.layoutHeight * totalZoom;
        let nextPanX = panX;
        let nextPanY = panY;

        if (scaledWidth <= rect.width) {
            nextPanX = (rect.width - scaledWidth) * 0.5;
        } else {
            const minPanX = rect.width - scaledWidth;
            nextPanX = Math.min(0, Math.max(minPanX, nextPanX));
        }

        if (scaledHeight <= rect.height) {
            nextPanY = (rect.height - scaledHeight) * 0.5;
        } else {
            const minPanY = rect.height - scaledHeight;
            nextPanY = Math.min(0, Math.max(minPanY, nextPanY));
        }

        return { panX: nextPanX, panY: nextPanY };
    }

    function applyVaultTransform(focusPoint = null){
        const contentEl = document.getElementById('vaultContent');
        if (!contentEl) {
            return;
        }
        let totalZoom = vaultViewState.fitZoom * vaultViewState.userZoom;
        let panX = vaultViewState.panX;
        let panY = vaultViewState.panY;

        if (vaultViewState.trackingEnabled && focusPoint) {
            const rect = vaultGridEl.getBoundingClientRect();
            totalZoom = vaultViewState.fitZoom * Math.max(1.28, vaultViewState.trackedZoomMultiplier);
            panX = rect.width * 0.5 - focusPoint.x * totalZoom;
            panY = rect.height * 0.52 - focusPoint.y * totalZoom;
        }

        const clamped = clampVaultPan(panX, panY, totalZoom);
        if (vaultViewState.trackingEnabled && focusPoint) {
            const blend = vaultViewState.followLerp;
            vaultViewState.renderedPanX += (clamped.panX - vaultViewState.renderedPanX) * blend;
            vaultViewState.renderedPanY += (clamped.panY - vaultViewState.renderedPanY) * blend;
            vaultViewState.renderedZoom += (totalZoom - vaultViewState.renderedZoom) * blend;
        } else {
            vaultViewState.panX = clamped.panX;
            vaultViewState.panY = clamped.panY;
            vaultViewState.renderedPanX = clamped.panX;
            vaultViewState.renderedPanY = clamped.panY;
            vaultViewState.renderedZoom = totalZoom;
        }
        contentEl.style.transform = `translate3d(${vaultViewState.renderedPanX}px, ${vaultViewState.renderedPanY}px, 0) scale(${vaultViewState.renderedZoom})`;
    }

    function updateVaultFit(forceReset = false){
        if (!vaultViewState.layoutWidth || !vaultViewState.layoutHeight) {
            return;
        }
        const rect = vaultGridEl.getBoundingClientRect();
        const fitX = Math.max(0.1, (rect.width - 8) / Math.max(1, vaultViewState.layoutWidth));
        const fitY = Math.max(0.1, (rect.height - 8) / Math.max(1, vaultViewState.layoutHeight));
        vaultViewState.fitZoom = Math.min(fitX, fitY);
        if (forceReset) {
            vaultViewState.userZoom = 1;
            vaultViewState.panX = 0;
            vaultViewState.panY = 0;
        }
        applyVaultTransform();
    }

    function handleVaultZoom(delta, clientX, clientY){
        if (!vaultViewState.layoutWidth || !vaultViewState.layoutHeight) {
            return;
        }
        releaseAgentTracking();
        const rect = vaultGridEl.getBoundingClientRect();
        const offsetX = clientX - rect.left;
        const offsetY = clientY - rect.top;
        const oldZoom = vaultViewState.fitZoom * vaultViewState.userZoom;
        const worldX = (offsetX - vaultViewState.panX) / oldZoom;
        const worldY = (offsetY - vaultViewState.panY) / oldZoom;
        vaultViewState.userZoom = Math.min(vaultViewState.maxUserZoom, Math.max(1, vaultViewState.userZoom * delta));
        const newZoom = vaultViewState.fitZoom * vaultViewState.userZoom;
        vaultViewState.panX = offsetX - worldX * newZoom;
        vaultViewState.panY = offsetY - worldY * newZoom;
        vaultViewState.renderedPanX = vaultViewState.panX;
        vaultViewState.renderedPanY = vaultViewState.panY;
        vaultViewState.renderedZoom = newZoom;
        applyVaultTransform();
    }

    vaultGridEl.addEventListener('wheel', (event) => {
        event.preventDefault();
        const delta = event.deltaY < 0 ? 1.12 : 1 / 1.12;
        handleVaultZoom(delta, event.clientX, event.clientY);
    }, { passive: false });

    vaultGridEl.addEventListener('pointerdown', (event) => {
        if (event.button !== 0) {
            return;
        }
        if (event.target.closest('.dweller')) {
            return;
        }
        releaseAgentTracking();
        vaultViewState.pointerId = event.pointerId;
        vaultViewState.startPanX = vaultViewState.panX;
        vaultViewState.startPanY = vaultViewState.panY;
        vaultViewState.startPointerX = event.clientX;
        vaultViewState.startPointerY = event.clientY;
        vaultGridEl.classList.add('panning');
        vaultGridEl.setPointerCapture(event.pointerId);
    });

    vaultGridEl.addEventListener('pointermove', (event) => {
        if (vaultViewState.pointerId !== event.pointerId) {
            return;
        }
        vaultViewState.panX = vaultViewState.startPanX + (event.clientX - vaultViewState.startPointerX);
        vaultViewState.panY = vaultViewState.startPanY + (event.clientY - vaultViewState.startPointerY);
        vaultViewState.renderedPanX = vaultViewState.panX;
        vaultViewState.renderedPanY = vaultViewState.panY;
        applyVaultTransform();
    });

    function stopVaultPan(event){
        if (vaultViewState.pointerId !== event.pointerId) {
            return;
        }
        vaultGridEl.classList.remove('panning');
        try {
            vaultGridEl.releasePointerCapture(event.pointerId);
        } catch (error) {
        }
        vaultViewState.pointerId = null;
    }

    vaultGridEl.addEventListener('pointerup', stopVaultPan);
    vaultGridEl.addEventListener('pointercancel', stopVaultPan);
    vaultGridEl.addEventListener('dblclick', () => {
        vaultViewState.userZoom = 1;
        vaultViewState.panX = 0;
        vaultViewState.panY = 0;
        vaultViewState.renderedPanX = 0;
        vaultViewState.renderedPanY = 0;
        vaultViewState.renderedZoom = vaultViewState.fitZoom;
        applyVaultTransform();
    });

    function buildDisplayMaps(tiles){
        const xValues = Array.from(new Set(tiles.map(tile => Number(tile.x)))).sort((a, b) => a - b);
        const yValues = Array.from(new Set(tiles.map(tile => Number(tile.y)))).sort((a, b) => a - b);
        return {
            xMap: new Map(xValues.map((value, index) => [value, index])),
            yMap: new Map(yValues.map((value, index) => [value, index])),
            width: Math.max(1, xValues.length),
            height: Math.max(1, yValues.length),
        };
    }

    function motionProgress(agent){
        const motion = (agent && agent.motion) || {};
        const duration = Number(motion.duration_s || 0);
        const startedAt = Number(motion.started_at || 0);
        if (!duration || !startedAt) {
            return 1;
        }
        return Math.max(0, Math.min(1, (Date.now() / 1000 - startedAt) / duration));
    }

    function sortedAgentIds(activeAgents){
        return Object.keys(activeAgents || {}).sort((left, right) => left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' }));
    }

    function updateTrackedAgentUI(activeAgents = (latestPayload || {}).active_agents || {}){
        const ids = sortedAgentIds(activeAgents);
        const hasAgents = ids.length > 0;
        syncFollowMenuUI();
        trackAgentSelectEls.forEach((selectEl) => {
            const options = hasAgents
                ? ids.map((agentId) => `<option value="${agentId}" ${agentId === vaultViewState.trackedAgentId ? 'selected' : ''}>${agentId}</option>`).join('')
                : '<option value="">No Agents</option>';
            selectEl.innerHTML = options;
            selectEl.disabled = !hasAgents;
        });
        if (trackAgentPrevEl) {
            trackAgentPrevEl.disabled = !hasAgents;
        }
        if (trackAgentNextEl) {
            trackAgentNextEl.disabled = !hasAgents;
        }
        trackAgentToggleEls.forEach((buttonEl) => {
            buttonEl.disabled = !hasAgents;
            buttonEl.classList.toggle('active', vaultViewState.trackingEnabled && !!vaultViewState.trackedAgentId);
            buttonEl.textContent = vaultViewState.trackingEnabled && vaultViewState.trackedAgentId ? 'Release Follow' : 'Follow Agent';
        });
        if (!trackedAgentLabelEl) {
            return;
        }
        if (vaultCameraHintEl) {
            vaultCameraHintEl.textContent = hasAgents
                ? 'Drag to pan, wheel to zoom, or lock onto a dweller. Double-click resets the isometric camera.'
                : 'Waiting for active dwellers before the tracker can lock on.';
        }
        if (!hasAgents) {
            trackedAgentLabelEl.textContent = 'Camera: no agents online';
            return;
        }
        if (!vaultViewState.trackedAgentId || !activeAgents[vaultViewState.trackedAgentId]) {
            trackedAgentLabelEl.textContent = `Camera: ready · ${ids[0]}`;
            return;
        }
        const tracked = activeAgents[vaultViewState.trackedAgentId] || {};
        const state = String(tracked.state || 'idle').toLowerCase();
        trackedAgentLabelEl.textContent = vaultViewState.trackingEnabled
            ? `Camera: tracking ${vaultViewState.trackedAgentId} · ${state}`
            : `Camera: selected ${vaultViewState.trackedAgentId} · manual`;
    }

    function releaseAgentTracking(){
        if (!vaultViewState.trackingEnabled) {
            return;
        }
        vaultViewState.trackingEnabled = false;
        vaultViewState.panX = vaultViewState.renderedPanX;
        vaultViewState.panY = vaultViewState.renderedPanY;
        vaultViewState.userZoom = Math.max(1, vaultViewState.renderedZoom / Math.max(0.1, vaultViewState.fitZoom));
        updateTrackedAgentUI();
    }

    function syncTrackedAgent(activeAgents = (latestPayload || {}).active_agents || {}){
        const ids = sortedAgentIds(activeAgents);
        if (!ids.length) {
            vaultViewState.trackedAgentId = '';
            vaultViewState.trackingEnabled = false;
            updateTrackedAgentUI(activeAgents);
            return ids;
        }
        if (!ids.includes(vaultViewState.trackedAgentId)) {
            vaultViewState.trackedAgentId = ids[0];
        }
        updateTrackedAgentUI(activeAgents);
        return ids;
    }

    function setTrackedAgent(agentId, shouldTrack = true){
        const activeAgents = (latestPayload || {}).active_agents || {};
        const ids = syncTrackedAgent(activeAgents);
        if (!ids.length) {
            return;
        }
        if (agentId && activeAgents[agentId]) {
            vaultViewState.trackedAgentId = agentId;
        }
        vaultViewState.trackingEnabled = shouldTrack && !!vaultViewState.trackedAgentId;
        updateTrackedAgentUI(activeAgents);
        renderVaultScene();
    }

    function selectTrackedAgent(agentId){
        if (!agentId) {
            releaseAgentTracking();
            renderVaultScene();
            return;
        }
        setTrackedAgent(agentId, true);
    }

    function toggleAgentTracking(){
        const activeAgents = (latestPayload || {}).active_agents || {};
        const ids = syncTrackedAgent(activeAgents);
        if (!ids.length) {
            return;
        }
        if (!vaultViewState.trackedAgentId) {
            vaultViewState.trackedAgentId = ids[0];
        }
        vaultViewState.trackingEnabled = !vaultViewState.trackingEnabled;
        updateTrackedAgentUI(activeAgents);
        renderVaultScene();
    }

    function cycleTrackedAgent(direction){
        const activeAgents = (latestPayload || {}).active_agents || {};
        const ids = syncTrackedAgent(activeAgents);
        if (!ids.length) {
            return;
        }
        const currentIndex = Math.max(0, ids.indexOf(vaultViewState.trackedAgentId));
        const nextIndex = (currentIndex + direction + ids.length) % ids.length;
        vaultViewState.trackedAgentId = ids[nextIndex];
        vaultViewState.trackingEnabled = true;
        updateTrackedAgentUI(activeAgents);
        renderVaultScene();
    }

    function scenePositionForAgent(agent, agentIndex, projection, layoutOrigin, fallbackCellX, fallbackCellY){
        const motion = agent.motion || {};
        const fromCell = motion.from || [fallbackCellX, fallbackCellY];
        const toCell = motion.to || [fallbackCellX, fallbackCellY];
        const progress = motionProgress(agent);
        const displayX = Number(fromCell[0]) + (Number(toCell[0]) - Number(fromCell[0])) * progress;
        const displayY = Number(fromCell[1]) + (Number(toCell[1]) - Number(fromCell[1])) * progress;
        const iso = cellToIso(displayX, displayY, projection, layoutOrigin);
        const tileWidth = Number((projection && projection.tile_width) || 64);
        const tileHeight = Number((projection && projection.tile_height) || 32);
        const agentLift = Number((projection && projection.agent_lift) || 20);
        return {
            interpY: displayY,
            facingLeft: Number(toCell[0]) < Number(fromCell[0]),
            baseX: iso.x + tileWidth * 0.12 + agentIndex * 16,
            baseY: iso.y - agentLift + tileHeight * 0.08,
            focusX: iso.x + tileWidth * 0.5,
            focusY: iso.y - agentLift,
        };
    }

    function connectorTextureUrl(){
        const generated = ((latestPayload || {}).generated_assets || {});
        return ((generated.texture || {}).url) || roomStyleArt('transit') || roomStyleArt('foundry') || '';
    }

    function animateVaultScene(){
        if (latestPayload) {
            renderVaultScene('animate');
        }
        sceneAnimationHandle = window.requestAnimationFrame(animateVaultScene);
    }

    function trimConsoleLines(limit = 80){
        while (consoleEl.childElementCount > limit) {
            consoleEl.removeChild(consoleEl.firstElementChild);
        }
    }

    function drainConsoleQueue(){
        if (!consoleQueue.length) {
            consoleTyping = false;
            return;
        }
        consoleTyping = true;
        const line = String(consoleQueue.shift() || '');
        const teleprinter = (latestPayload && latestPayload.teleprinter) || {};
        const burst = Math.max(1, Number(teleprinter.backlog_burst || 4));
        const staggerMs = Math.max(8, Number(teleprinter.stagger_ms || 14));
        const lineEl = document.createElement('div');
        lineEl.className = 'tele-line typing';
        consoleEl.appendChild(lineEl);
        let index = 0;
        const typeChunk = () => {
            index = Math.min(line.length, index + burst);
            lineEl.textContent = line.slice(0, index);
            consoleEl.scrollTop = consoleEl.scrollHeight;
            if (index < line.length) {
                window.setTimeout(typeChunk, staggerMs);
                return;
            }
            lineEl.classList.remove('typing');
            trimConsoleLines();
            window.setTimeout(drainConsoleQueue, Math.max(12, staggerMs * 2));
        };
        typeChunk();
    }

    function logLine(text){
      const ts = new Date().toLocaleTimeString();
      consoleQueue.push(`[${ts}] ${text}`);
      if (!consoleTyping) {
        drainConsoleQueue();
      }
    }

        function roomThemeForTile(tile, index){
            const palette = ['reactor', 'foundry', 'hydro', 'archive', 'command', 'transit'];
            if (tile.kind === 'chamber') {
                return palette[index % palette.length];
            }
            return index % 2 === 0 ? 'transit' : 'archive';
        }

        function roomTitleForTheme(theme){
            const titles = {
                reactor: 'Reactor Bay',
                foundry: 'Forge Deck',
                hydro: 'Hydro Garden',
                archive: 'Signal Archive',
                command: 'Command Nest',
                transit: 'Transit Tube',
            };
            return titles[theme] || 'Vault Room';
        }

        function roomStyleLabel(theme){
            const styles = ((latestPayload || {}).room_styles || {});
            return (styles[theme] || {}).style || 'vault core';
        }

        function roomStyleArt(theme){
            const styles = ((latestPayload || {}).room_styles || {});
            return (styles[theme] || {}).url || '';
        }

        function renderRoomStyleRack(payload){
            const styles = (payload && payload.room_styles) || {};
            const entries = Object.entries(styles);
            if (!entries.length) {
                roomStyleRackEl.innerHTML = '<div class="small">No room style assets generated yet.</div>';
                return;
            }
            roomStyleRackEl.innerHTML = entries.map(([theme, meta]) => `
                <div class="room-style-chip">
                    ${meta.url ? `<img class="room-style-thumb" src="${meta.url}" alt="${meta.title} style preview" />` : '<div class="room-style-thumb"></div>'}
                    <div class="room-style-caption">${meta.title} · ${meta.status}</div>
                </div>`).join('');
        }

        function roomArtStyle(theme){
            const artUrl = roomStyleArt(theme);
            if (!artUrl) {
                return '--room-art-image:none;';
            }
            return `--room-art-image:url('${String(artUrl).replace(/'/g, '%27')}');`;
        }

        function signalColorForKind(kind){
            const colors = {
                token: '#6df5ff',
                control: '#77d2ff',
                trace: '#b894ff',
                deliverable: '#ffb75c',
                coolant: '#8bf1a7',
                telemetry: '#efe2ff',
                reserve: '#ffd990',
                watchdog: '#ff9f96',
                prompt: '#d8f7ff',
                tool: '#f5c96b',
                fault: '#ff8f87',
                mirror: '#d0d7dd',
            };
            return colors[String(kind || '').toLowerCase()] || '#6df5ff';
        }

        function roomRectForMeta(room, projection, layoutOrigin, wallHeight, tileWidth, tileHeight){
            const bounds = Array.isArray(room.tile_bounds) && room.tile_bounds.length === 4
                ? room.tile_bounds.map(Number)
                : [0, 0, 1, 1];
            const corners = [
                cellToIso(bounds[0], bounds[1], projection, layoutOrigin),
                cellToIso(bounds[2] + 1, bounds[1], projection, layoutOrigin),
                cellToIso(bounds[0], bounds[3] + 1, projection, layoutOrigin),
                cellToIso(bounds[2] + 1, bounds[3] + 1, projection, layoutOrigin),
            ];
            const left = Math.min(...corners.map(point => point.x)) - 26;
            const right = Math.max(...corners.map(point => point.x)) + tileWidth * 0.78;
            const top = Math.min(...corners.map(point => point.y)) - wallHeight - 36;
            const bottom = Math.max(...corners.map(point => point.y)) + tileHeight * 1.25;
            return {
                left,
                top,
                width: Math.max(164, right - left),
                height: Math.max(132, bottom - top),
                centerX: (left + right) * 0.5,
                centerY: (top + bottom) * 0.5,
            };
        }

        function buildRoomMarkup(room, rect){
            const theme = String(room.theme || 'transit');
            const roomId = String(room.id || 'room');
            const occupancy = Math.max(0, Number(room.occupancy || 0));
            const tokenUsage = Math.max(0, Math.min(100, Number(room.token_usage_pct || 0)));
            const signalUsage = Math.max(0, Math.min(100, Number(room.signal_load_pct || 0)));
            const agents = Array.isArray(room.agents) ? room.agents : [];
            const laneMarkup = (Array.isArray(room.lanes) ? room.lanes : []).map((lane, laneIndex) => `
                <div class="room-lane">
                    <span style="--lane-fill:${Math.max(24, signalUsage - laneIndex * 12)}%"></span>
                    <strong>${lane}</strong>
                </div>`).join('');
            const occupancyDots = Array.from({ length: 4 }, (_, index) => `<span class="${index < Math.min(4, occupancy) ? '' : 'off'}"></span>`).join('');
            const terminals = Array.isArray(room.terminals) ? room.terminals : ['terminal', 'relay'];
            const roomClasses = [
                'vault-room',
                `theme-${theme}`,
                room.locked ? 'locked' : '',
                room.boiler_room ? 'boiler-room' : '',
            ].filter(Boolean).join(' ');
            return `
                <div class="${roomClasses}" data-room-id="${roomId}" style="left:${Math.round(rect.left)}px;top:${Math.round(rect.top)}px;width:${Math.round(rect.width)}px;height:${Math.round(rect.height)}px;z-index:${120 + Number((room.grid || [0, 0])[1] || 0) * 12 + Number((room.grid || [0, 0])[0] || 0)};${roomArtStyle(theme)}--room-token-fill:${tokenUsage}%">
                    <div class="room-shell"></div>
                    <div class="room-ceiling"></div>
                    <div class="room-backdrop"><div class="room-art"></div><div class="room-pattern"></div></div>
                    <div class="room-wall-left"></div>
                    <div class="room-wall-right"></div>
                    <div class="room-floor"></div>
                    <div class="room-decal"></div>
                    <div class="room-light-strip"></div>
                    <div class="room-labels">
                        <div>
                            <div class="room-name">${room.title || roomId}</div>
                            <div class="room-style">${room.style || theme}</div>
                        </div>
                        <div class="room-grid-badge">${roomId}</div>
                    </div>
                    <div class="room-io"><span>${room.intake || 'inbound'}</span><span>${room.output || 'outbound'}</span></div>
                    <div class="room-terminal primary"><div class="room-terminal-title">${terminals[0] || 'terminal'}</div><div class="room-terminal-copy">${room.status || 'nominal'}</div></div>
                    <div class="room-terminal secondary"><div class="room-terminal-title">${terminals[1] || 'relay'}</div><div class="room-terminal-copy">${Math.round(signalUsage)}% signal</div></div>
                    <div class="room-lanes">${laneMarkup}</div>
                    <div class="room-machine"></div>
                    <div class="room-token-meter"><span></span></div>
                    <div class="room-signal-caption"><span>${room.detail || 'signal flow active'}</span><strong>${Math.round(tokenUsage)}% tokens</strong></div>
                    <div class="room-occupancy"><span class="room-code">${agents[0] || 'no crew'}${agents.length > 1 ? ' +' + (agents.length - 1) : ''}</span><div class="room-pop">${occupancyDots}</div></div>
                    <div class="room-wire-port left"></div>
                    <div class="room-wire-port right"></div>
                    <div class="room-wire-port top"></div>
                    <div class="room-wire-port bottom"></div>
                    <div class="room-door left"></div>
                    <div class="room-door right"></div>
                    <div class="room-door top"></div>
                    <div class="room-door bottom"></div>
                </div>`;
        }

        function buildConnectorMarkup(connectors, roomRects){
            return (Array.isArray(connectors) ? connectors : []).map((connector) => {
                const fromRect = roomRects.get(String(connector.from || ''));
                const toRect = roomRects.get(String(connector.to || ''));
                if (!fromRect || !toRect) {
                    return '';
                }
                const horizontal = String(connector.kind || '') === 'hallway';
                if (horizontal) {
                    const left = fromRect.left + fromRect.width - 10;
                    const right = toRect.left + 10;
                    const top = fromRect.centerY - 10;
                    return `<div class="vault-connector hallway" style="left:${Math.round(left)}px;top:${Math.round(top)}px;width:${Math.max(24, Math.round(right - left))}px"><div class="connector-door a"></div><div class="connector-door b"></div></div>`;
                }
                const left = fromRect.centerX - 12;
                const top = fromRect.top + fromRect.height - 10;
                const bottom = toRect.top + 10;
                return `<div class="vault-connector ladder" style="left:${Math.round(left)}px;top:${Math.round(top)}px;height:${Math.max(26, Math.round(bottom - top))}px"><div class="connector-door a"></div><div class="connector-door b"></div></div>`;
            }).join('');
        }

        function buildSignalOverlay(signalLinks, roomRects, layoutWidth, layoutHeight){
            const markup = (Array.isArray(signalLinks) ? signalLinks : []).map((link) => {
                const fromRect = roomRects.get(String(link.from || ''));
                const toRect = roomRects.get(String(link.to || ''));
                if (!fromRect || !toRect) {
                    return '';
                }
                const startX = fromRect.centerX;
                const startY = fromRect.centerY;
                const endX = toRect.centerX;
                const endY = toRect.centerY;
                const horizontalBias = Math.abs(endX - startX) >= Math.abs(endY - startY);
                const controlX1 = horizontalBias ? startX + (endX - startX) * 0.4 : startX;
                const controlY1 = horizontalBias ? startY : startY + (endY - startY) * 0.4;
                const controlX2 = horizontalBias ? endX - (endX - startX) * 0.4 : endX;
                const controlY2 = horizontalBias ? endY : endY - (endY - startY) * 0.4;
                const midX = (startX + endX) * 0.5;
                const midY = (startY + endY) * 0.5 - 12;
                const color = signalColorForKind(link.kind);
                return `
                    <g>
                        <path class="vault-signal-path" d="M ${startX} ${startY} C ${controlX1} ${controlY1}, ${controlX2} ${controlY2}, ${endX} ${endY}" stroke="${color}" opacity="${0.52 + Math.min(0.4, Number(link.load_pct || 0) / 180)}"></path>
                        <circle class="vault-signal-node" cx="${startX}" cy="${startY}" r="4.5" fill="${color}"></circle>
                        <circle class="vault-signal-node" cx="${endX}" cy="${endY}" r="4.5" fill="${color}"></circle>
                        <text class="vault-signal-label" x="${midX}" y="${midY}" text-anchor="middle">${link.label || link.kind || 'signal'}</text>
                    </g>`;
            }).join('');
            if (!markup) {
                return '';
            }
            return `<svg class="vault-signal-layer" viewBox="0 0 ${Math.round(layoutWidth)} ${Math.round(layoutHeight)}" preserveAspectRatio="none">${markup}</svg>`;
        }

        function renderVaultScene(renderMode = 'full'){
            if (!latestPayload || !latestPayload.world){
                if (renderMode !== 'animate') {
                    vaultGridEl.innerHTML = '<div class="card" style="position:absolute;left:18px;top:18px;right:18px">Waiting for vault telemetry...</div>';
                    activePatrolLabelEl.textContent = 'Active patrol: idle';
                }
                return;
            }

            const isAnimatedPass = renderMode === 'animate';
            const world = latestPayload.world;
            const projection = world.projection || { tile_width: 64, tile_height: 32, wall_height: 28, agent_lift: 20 };
            const activeAgents = latestPayload.active_agents || {};
            if (!isAnimatedPass) {
                syncTrackedAgent(activeAgents);
            }
            const tiles = world.tiles || [];
            const rooms = world.rooms || [];
            const roomConnectors = world.room_connectors || [];
            const signalLinks = world.signal_links || [];
            const rect = vaultGridEl.getBoundingClientRect();
            const gridWidth = Math.max(760, rect.width || 760);
            const gridHeight = Math.max(420, rect.height || 420);
            const tileWidth = Number(projection.tile_width || 64);
            const tileHeight = Number(projection.tile_height || 32);
            const wallHeight = Number(projection.wall_height || 28);
            const baseLayoutWidth = (world.grid_width + world.grid_height) * tileWidth * 0.5 + 240;
            const baseLayoutHeight = (world.grid_width + world.grid_height) * tileHeight * 0.5 + wallHeight + 220;
            const layoutWidth = Math.max(gridWidth, baseLayoutWidth);
            const layoutHeight = Math.max(gridHeight, baseLayoutHeight);
            const layoutOrigin = {
                x: world.grid_height * tileWidth * 0.5 + 92,
                y: 78,
            };
            const reservedCells = new Set(
                Object.values(latestPayload.reserved_paths || {}).flat().map(cell => `${cell[0]},${cell[1]}`)
            );
            const agentsByCell = new Map();
            for (const [agentId, agent] of Object.entries(activeAgents)) {
                const cell = agent.cell || [0, 0];
                const key = `${cell[0]},${cell[1]}`;
                const bucket = agentsByCell.get(key) || [];
                bucket.push([agentId, agent]);
                agentsByCell.set(key, bucket);
            }

            if (!isAnimatedPass) {
                const taskLabel = ((latestPayload.autonomous || {}).last_task || 'idle').replace(/_/g, ' ');
                activePatrolLabelEl.textContent = `Active patrol: ${taskLabel}`;
            }

            const layoutKey = JSON.stringify({
                grid: [world.grid_width, world.grid_height],
                projection: [projection.tile_width, projection.tile_height, projection.wall_height, projection.agent_lift],
                tiles: tiles.map(tile => [tile.x, tile.y, tile.kind, tile.theme, tile.foreground, tile.clutter]),
                rooms: rooms.map(room => [room.id, room.theme, room.tile_bounds, room.locked, room.boiler_room]),
                connectors: roomConnectors.map(connector => [connector.from, connector.to, connector.kind]),
                boiler_tile: Array.isArray(world.boiler_tile) ? world.boiler_tile : [],
            });
            const layoutChanged = layoutKey !== sceneLayoutKey;
            if (!isAnimatedPass && layoutChanged) {
                sceneLayoutKey = layoutKey;
                const tileMarkup = tiles.map((tile, index) => {
                    const iso = cellToIso(Number(tile.x), Number(tile.y), projection, layoutOrigin);
                    const theme = String(tile.theme || roomThemeForTile(tile, index));
                    const palette = (world.palette || {})[theme] || {};
                    const lockedClass = reservedCells.has(`${tile.x},${tile.y}`) ? ' locked' : '';
                    return `
                        <div class="pixel-tile theme-${theme}${lockedClass}" data-cell="${tile.x},${tile.y}" style="left:${Math.round(iso.x)}px;top:${Math.round(iso.y)}px;width:${tileWidth}px;height:${tileHeight}px;z-index:${80 + tile.x + tile.y * 4};--tile-base:${palette.base || '#6f4b35'};--tile-accent:${palette.accent || '#cfad7d'};--tile-shadow:${palette.shadow || '#21160f'};--wall-height:${wallHeight}px">
                            <div class="pixel-diamond pixel-tile-riser"></div>
                            <div class="pixel-diamond pixel-tile-riser right"></div>
                            <div class="pixel-diamond pixel-tile-top"></div>
                            <div class="pixel-grit"></div>
                            <div class="pixel-clutter ${tile.clutter || 'crate'}"></div>
                        </div>`;
                }).join('');
                const occluderMarkup = tiles.filter(tile => tile.foreground).map((tile) => {
                    const iso = cellToIso(Number(tile.x), Number(tile.y), projection, layoutOrigin);
                    return `<div class="pixel-occluder" data-occluder-cell="${tile.x},${tile.y}" style="left:${Math.round(iso.x - 2)}px;top:${Math.round(iso.y - wallHeight - 28)}px;z-index:${180 + tile.x + tile.y * 4}"><div class="pixel-clutter"></div></div>`;
                }).join('');
                const boilerTile = Array.isArray(world.boiler_tile) ? world.boiler_tile : [];
                let boilerMarkup = '';
                let steamRackMarkup = '';
                if (boilerTile.length === 2) {
                    const boilerIso = cellToIso(Number(boilerTile[0]), Number(boilerTile[1]), projection, layoutOrigin);
                    boilerMarkup = `<div id="pixelBoiler" class="pixel-boiler" style="left:${Math.round(boilerIso.x - 26)}px;top:${Math.round(boilerIso.y - 112)}px;z-index:${260 + boilerTile[0] + boilerTile[1] * 4}"><div class="pixel-boiler-gauge"><div id="boilerNeedle" class="pixel-boiler-needle"></div></div><div class="pixel-boiler-body"></div><div class="pixel-boiler-door"></div><div class="pixel-boiler-pipe"></div><div id="boilerValve" class="pixel-boiler-valve"></div><div id="boilerFire" class="pixel-boiler-fire"></div></div>`;
                    steamRackMarkup = `<div id="boilerSteamRack" style="position:absolute;left:${Math.round(boilerIso.x + 12)}px;top:${Math.round(boilerIso.y - 136)}px;z-index:${320 + boilerTile[0] + boilerTile[1] * 4};--steam-intensity:.2">${Array.from({ length: 5 }, (_, index) => `<div class="steam-burst" style="left:${18 + index * 12}px;top:${20 + (index % 2) * 10}px;animation-delay:${index * 0.18}s"></div>`).join('')}</div>`;
                }
                vaultGridEl.innerHTML = tileMarkup
                    ? `<div id="vaultContent" class="vault-content pixel-world" style="width:${layoutWidth}px;height:${layoutHeight}px"><div class="pixel-layer">${tileMarkup}</div><div id="vaultAgentLayer" class="pixel-agents"></div><div id="vaultOccluderLayer" class="pixel-occluders">${occluderMarkup}</div><div id="vaultFxLayer" class="pixel-fx">${boilerMarkup}${steamRackMarkup}</div></div>`
                    : '<div class="card" style="position:absolute;left:18px;top:18px;right:18px">No rooms available.</div>';
            }

            vaultViewState.layoutWidth = layoutWidth;
            vaultViewState.layoutHeight = layoutHeight;
            updateVaultFit(layoutChanged && !isAnimatedPass);

            if (!isAnimatedPass) {
                document.querySelectorAll('.pixel-tile').forEach((tileEl) => {
                    const cellKey = tileEl.getAttribute('data-cell') || '';
                    tileEl.classList.toggle('locked', reservedCells.has(cellKey));
                });
            }

            const agentLayerEl = document.getElementById('vaultAgentLayer');
            if (!agentLayerEl) {
                return;
            }
            const seen = new Set();
            let trackedFocusPoint = null;
            for (const [cellKey, roomAgents] of agentsByCell.entries()) {
                const [cellX, cellY] = cellKey.split(',').map(Number);
                roomAgents.forEach(([agentId, agent], agentIndex) => {
                    seen.add(agentId);
                    let dwellerEl = agentLayerEl.querySelector(`[data-agent-id="${agentId}"]`);
                    if (!dwellerEl) {
                        dwellerEl = document.createElement('div');
                        dwellerEl.className = 'dweller idle';
                        dwellerEl.setAttribute('data-agent-id', agentId);
                        dwellerEl.setAttribute('tabindex', '0');
                        dwellerEl.innerHTML = '<div class="dweller-tag"></div><div class="dweller-rig"><div class="dweller-shadow"></div><div class="dweller-limb dweller-leg leg-a"></div><div class="dweller-limb dweller-leg leg-b"></div><div class="dweller-limb dweller-arm arm-a"></div><div class="dweller-limb dweller-arm arm-b"></div><div class="dweller-body"></div><div class="dweller-head"></div></div>';
                        dwellerEl.addEventListener('click', () => setTrackedAgent(agentId, true));
                        dwellerEl.addEventListener('keydown', (event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setTrackedAgent(agentId, true);
                            }
                        });
                        agentLayerEl.appendChild(dwellerEl);
                    }
                    const state = String(agent.state || 'IDLE').toLowerCase();
                    dwellerEl.className = `dweller ${state}`;
                    dwellerEl.classList.toggle('is-tracked', vaultViewState.trackedAgentId === agentId);
                    const tagEl = dwellerEl.querySelector('.dweller-tag');
                    if (tagEl) {
                        tagEl.textContent = agentId;
                    }
                    let crateEl = dwellerEl.querySelector('.dweller-crate');
                    if (state === 'carry') {
                        if (!crateEl) {
                            crateEl = document.createElement('div');
                            crateEl.className = 'dweller-crate';
                            dwellerEl.appendChild(crateEl);
                        }
                    } else if (crateEl) {
                        crateEl.remove();
                    }
                    const scenePosition = scenePositionForAgent(agent, agentIndex, projection, layoutOrigin, cellX, cellY);
                    dwellerEl.classList.toggle('facing-left', !!scenePosition.facingLeft);
                    const armA = dwellerEl.querySelector('.arm-a');
                    const armB = dwellerEl.querySelector('.arm-b');
                    const legA = dwellerEl.querySelector('.leg-a');
                    const legB = dwellerEl.querySelector('.leg-b');
                    armA?.style.setProperty('--limb-rest', 'translateX(-11px)');
                    armB?.style.setProperty('--limb-rest', 'translateX(6px)');
                    legA?.style.setProperty('--limb-rest', 'translateX(-8px)');
                    legB?.style.setProperty('--limb-rest', 'translateX(3px)');
                    dwellerEl.style.zIndex = `${220 + Math.round(scenePosition.interpY * 10)}`;
                    dwellerEl.style.transform = `translate3d(${scenePosition.baseX}px, ${scenePosition.baseY}px, 0)`;
                    if (vaultViewState.trackedAgentId === agentId) {
                        trackedFocusPoint = { x: scenePosition.focusX, y: scenePosition.focusY };
                    }
                });
            }
            Array.from(agentLayerEl.querySelectorAll('[data-agent-id]')).forEach((node) => {
                if (!seen.has(node.getAttribute('data-agent-id'))) {
                    node.remove();
                }
            });
            if (!isAnimatedPass) {
                updateTrackedAgentUI(activeAgents);
            }
            const boiler = latestPayload.boiler || {};
            const boilerNeedleEl = document.getElementById('boilerNeedle');
            const boilerValveEl = document.getElementById('boilerValve');
            const boilerFireEl = document.getElementById('boilerFire');
            const boilerSteamRackEl = document.getElementById('boilerSteamRack');
            const fxLayerEl = document.getElementById('vaultFxLayer');
            if (boilerNeedleEl) {
                const needleRotation = -110 + Math.min(220, Math.max(0, Number(boiler.ratio || 0) * 220));
                boilerNeedleEl.style.transform = `rotate(${needleRotation}deg)`;
            }
            if (boilerValveEl) {
                boilerValveEl.style.transform = `rotate(${Math.round(Number(boiler.valve_phase || 0) * 38)}deg)`;
            }
            if (boilerFireEl) {
                boilerFireEl.style.setProperty('--boiler-fire', `${0.28 + Math.min(0.72, Number(boiler.steam_level || 0) * 0.88)}`);
            }
            if (boilerSteamRackEl) {
                boilerSteamRackEl.style.setProperty('--steam-intensity', `${Math.min(1, Number(boiler.steam_level || 0))}`);
            }
            if (fxLayerEl) {
                fxLayerEl.classList.toggle('flashover', String(boiler.state || '') === 'flashover');
            }
            applyVaultTransform(trackedFocusPoint);
        }

        function renderRows(tbody, rows, emptyText){
            if (!rows.length){
                tbody.innerHTML = `<tr><td colspan="2">${emptyText}</td></tr>`;
                return;
            }
            tbody.innerHTML = rows.join('');
        }

        function updateGeneratedAssets(payload){
            const generated = (payload && payload.generated_assets) || {};
            const texture = generated.texture || {};
            const character = generated.character || {};

            texturePreviewEl.src = texture.url || '';
            texturePreviewEl.style.display = texture.url ? 'block' : 'none';
            texturePromptEl.textContent = texture.prompt ? `${texture.status || 'idle'} :: ${texture.prompt}` : 'No generated blueprint texture yet.';

            characterPreviewEl.src = character.url || '';
            characterPreviewEl.style.display = character.url ? 'block' : 'none';
            characterPromptEl.textContent = character.prompt ? `${character.status || 'idle'} :: ${character.prompt}` : 'No generated dweller portrait yet.';
            renderRoomStyleRack(payload);
        }

        async function refreshOperations(){
            const jobs = await fetch('/jobs').then(resp => resp.json());
            const status = await fetch('/status').then(resp => resp.json());
            latestPayload = status;
            updateGeneratedAssets(status);
            renderVaultScene();

            renderRows(
                queueTableEl,
                (jobs.queue || []).map(item => `<tr><td>${item.task_id}</td><td>${item.priority}</td></tr>`),
                'No queued jobs'
            );
            renderRows(
                historyTableEl,
                (jobs.completed || []).slice(-6).map(item => `<tr><td>${item.task_id}</td><td>${item.agent_id}</td></tr>`),
                'No completed jobs'
            );
            const reserved = Object.entries(status.reserved_paths || {});
            renderRows(
                reservationTableEl,
                reserved.map(([agent, cells]) => `<tr><td>${agent}</td><td>${cells.map(cell => '[' + cell.join(',') + ']').join(' ')}</td></tr>`),
                'No reservations'
            );
            renderRows(
                faultTableEl,
                ((status.faults && status.faults.recent) || []).map(item => `<tr><td>${item.kind}</td><td class="${item.acknowledged ? '' : 'fault-unacked'}">${item.acknowledged ? 'ACKED' : 'UNACKED'}</td></tr>`),
                'No faults logged'
            );
        }

    async function sendCommand(action){
            let body = {action};
            if (action === 'set-recovery-policy') {
                const next = recoveryPolicyEl.textContent === 'strict' ? 'auto-reset' : (recoveryPolicyEl.textContent === 'auto-reset' ? 'cautious' : 'strict');
                body = {action, policy: next};
            } else if (action === 'process-queue') {
                body = {action, lookahead: 3};
            }
            const resp = await fetch('/command', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
                body: JSON.stringify(body)
      });
      const data = await resp.json();
      lastCommandEl.textContent = action;
      logLine(`command=${action} :: ok=${data.ok !== false}`);
            await refreshOperations();
    }

    socket.onopen = () => {
            consoleEl.innerHTML = '';
            logLine('Overseer uplink connected. Awaiting vault telemetry...');
      socket.send('teleprinter-online');
            syncFollowMenuUI();
            renderVaultScene();
            if (!sceneAnimationHandle) {
            sceneAnimationHandle = window.requestAnimationFrame(animateVaultScene);
            }
    };

    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
            latestPayload = payload;
    updateGeneratedAssets(payload);
      pressureEl.textContent = `${payload.boiler_pressure} / ${payload.burst_limit}`;
      velocityEl.textContent = Number(payload.token_velocity || 0).toFixed(2);
      bypassEl.textContent = payload.local_bypass ? 'LOCAL PORT 1234' : 'PRIMARY';
      agentsEl.textContent = Object.keys(payload.active_agents || {}).length;
      queueDepthEl.textContent = payload.job_queue_depth || 0;
    completedJobsEl.textContent = (payload.completed_jobs || []).length;
    launcherPathEl.textContent = payload.launcher_path || 'pending';
    const recovery = payload.startup_recovery || { performed:false, actions:[] };
    recoveryStateEl.textContent = recovery.performed ? recovery.actions.join(', ') : 'nominal';
    recoveryPolicyEl.textContent = payload.recovery_policy || 'auto-reset';
            const autonomy = payload.autonomous || { mode:'enabled', last_task:'idle' };
            autonomousModeEl.textContent = autonomy.mode || 'enabled';
            autonomousTaskEl.textContent = autonomy.last_task || 'idle';
            loadBarEl.style.width = `${Math.min(100, Math.max(0, (Number(payload.boiler_pressure || 0) / Math.max(1, Number(payload.burst_limit || 1))) * 100))}%`;
      const recent = payload.recent_commands || [];
      if (recent.length) {
        lastCommandEl.textContent = recent[recent.length - 1].event;
      }
            modeEl.textContent = payload.is_tripped ? 'Reactor Flashover' : 'Reactor Stable';
      panel.classList.toggle('tripped', !!payload.is_tripped);
      const duration = Math.max(0.45, 1.8 - (Number(payload.token_velocity || 0) * 0.18));
      tubeEl.style.setProperty('--pulse-speed', `${duration}s`);
    renderVaultScene();
      logLine(`${payload.event} :: pressure=${payload.boiler_pressure} :: bypass=${payload.local_bypass ? 'ON' : 'OFF'} :: reason=${payload.trip_reason}`);
    };

        socket.onerror = () => logLine('Overseer uplink fault detected.');
        socket.onclose = () => {
            logLine('Overseer uplink closed.');
            if (sceneAnimationHandle) {
                window.cancelAnimationFrame(sceneAnimationHandle);
                sceneAnimationHandle = 0;
            }
        };
        setInterval(refreshOperations, 3000);
      window.addEventListener('resize', renderVaultScene);
  </script>
</body>
</html>
"""


# ELI5: This builds the FastAPI service shell so a browser sidecar and WebSocket can watch the plant in real time.
def create_app(master_control: SITKMasterControl) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("FastAPI and uvicorn are required to serve the teleprinter UI.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Initializing ORBSTUDIO Subterranean API Router...")
        await master_control.start_background_tasks()
        yield
        await master_control.stop_background_tasks()
        logger.info("Shutting down API Router. Venting remaining steam pressure.")

    app = FastAPI(title="ORBSTUDIO Command Center", lifespan=lifespan)

    @app.get("/")
    async def index() -> Any:
        entrypoint = _pixel_engine_asset("index.html")
        if entrypoint:
            return RedirectResponse("/pixel-engine", status_code=302)
        return HTMLResponse(build_teleprinter_template())

    @app.get("/pixel-engine")
    async def pixel_engine_preview() -> Any:
        entrypoint = _pixel_engine_asset("index.html")
        if entrypoint:
            return FileResponse(entrypoint)
        return HTMLResponse(build_pixel_engine_preview_html())

    @app.get("/pixel-engine/themes")
    async def pixel_engine_themes() -> Any:
        return JSONResponse(pixel_engine_theme_presets())

    @app.get("/pixel-engine/{asset_path:path}")
    async def pixel_engine_asset_route(asset_path: str) -> Any:
        asset = _pixel_engine_asset(asset_path)
        if asset:
            return FileResponse(asset)
        return JSONResponse({"ok": False, "error": "pixel-engine-asset-missing", "asset": asset_path}, status_code=404)

    @app.get("/status")
    async def status() -> Any:
        return JSONResponse(master_control.serialize_status())

    @app.get("/jobs")
    async def jobs() -> Any:
        return JSONResponse({
            "queue": master_control.job_queue,
            "completed": master_control.completed_jobs[-10:],
            "recent_commands": master_control.command_log[-10:],
        })

    @app.get("/chatlog")
    async def chatlog() -> Any:
        return JSONResponse({
            "path": str(master_control.chatlog_path),
            "recent": master_control.chat_history[-40:],
            "turn_count": len(master_control.chat_history),
        })

    @app.get("/generated-assets/{kind}")
    async def generated_asset(kind: str) -> Any:
        meta = master_control.generated_assets.get(kind, {})
        path = Path(str(meta.get("path", ""))) if meta.get("path") else None
        if not path or not path.exists():
            return JSONResponse({"ok": False, "error": "asset-missing"}, status_code=404)
        return FileResponse(path)

    @app.get("/health")
    async def health() -> Any:
        return JSONResponse(master_control.health_snapshot())

    @app.post("/command")
    async def command(payload: Dict[str, Any]) -> Any:
        result = await master_control.execute_command(str(payload.get("action", "status")), payload)
        return JSONResponse(result)

    @app.websocket("/ws/teleprinter")
    async def teleprinter_endpoint(websocket: WebSocket) -> None:
        await master_control.switchboard.connect(websocket)
        await websocket.send_text(json.dumps(master_control.serialize_status(event="connected")))
        master_control._record_chat_exchange(
            "assistant",
            "Teleprinter connected. Live plant telemetry is online.",
            channel="teleprinter",
            event="connected",
        )
        try:
            while True:
                message = await websocket.receive_text()
                master_control._record_chat_exchange(
                    "user",
                    message,
                    channel="teleprinter",
                    event="received",
                )
                await master_control.broadcast_status(event="acknowledged")
                master_control._record_chat_exchange(
                    "assistant",
                    f"Telemetry acknowledged: {master_control._chat_text(message)}",
                    channel="teleprinter",
                    event="acknowledged",
                )
        except WebSocketDisconnect:
            master_control.switchboard.disconnect(websocket)

    return app


# ELI5: This is the front-desk switch parser. It lets the foreman choose smoke test,
# server mode, and a repeatable tunnel seed without hand-editing the source.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ORBSTUDIO SITK Phase 6 bootstrap and teleprinter runtime.")
    parser.add_argument("--serve", action="store_true", help="Start the FastAPI teleprinter sidecar.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for the sidecar server.")
    parser.add_argument("--port", type=int, default=8765, help="Port for the teleprinter server.")
    parser.add_argument("--seed", type=int, default=13, help="Random seed for the cave random-walk generator.")
    parser.add_argument("--layout-steps", type=int, default=260, help="Number of random-walk excavation steps.")
    parser.add_argument("--smoke-test", action="store_true", help="Run the AGD and boiler routing smoke test.")
    parser.add_argument("--trip-boiler", action="store_true", help="Force the smoke test to trip the boiler.")
    parser.add_argument("--apply-phase2-config", action="store_true", help="Apply the real Game.ini Phase 2 patch set.")
    parser.add_argument("--config-root", default="", help="Optional override for the Game.ini config directory.")
    parser.add_argument("--state-path", default="", help="Optional path for persistent SITK state JSON.")
    parser.add_argument("--bootstrap-report", action="store_true", help="Generate the Phase 6 bootstrap report and launcher.")
    parser.add_argument("--recovery-policy", default="auto-reset", choices=["auto-reset", "cautious", "strict"], help="Startup recovery policy for stale tripped state.")
    return parser.parse_args()


# ELI5: This is the ignition key. It backs up the configs first, then runs either a
# quick proving cycle or the live browser sidecar depending on the selected switches.
def main() -> int:
    print("\n" + "=" * 58)
    print(" ORBSTUDIO PHASE 6 // THE FAULT RACK ")
    print("=" * 58 + "\n")

    args = parse_args()
    ensure_backup_vault_available()
    execute_ark_backup_protocol()

    master_control = SITKMasterControl(
        seed=args.seed,
        layout_steps=args.layout_steps,
        state_path=args.state_path or None,
        config_root=args.config_root or None,
        recovery_policy=args.recovery_policy,
    )

    if args.apply_phase2_config:
        patch_result = master_control.apply_phase2_config()
        logger.info("PHASE 2 CONFIG PATCH: %s", json.dumps(patch_result, indent=2, default=str))

    if args.bootstrap_report:
        bootstrap_result = master_control.bootstrap.generate_report()
        logger.info("PHASE 6 BOOTSTRAP REPORT: %s", json.dumps(bootstrap_result, indent=2, default=str))

    if args.smoke_test or not args.serve:
        result = asyncio.run(master_control.run_smoke_test(simulate_trip=args.trip_boiler or not args.serve))
        logger.info("SMOKE TEST COMPLETE: %s", json.dumps(result["status"], indent=2, default=str))

    if args.serve:
        if not FASTAPI_AVAILABLE or uvicorn is None:
            logger.error("FastAPI/uvicorn are not installed, so the teleprinter sidecar cannot start.")
            return 2
        app = create_app(master_control)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
