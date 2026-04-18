from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
import winreg


DEFAULT_NODE_DIRS = (
	Path(r"C:\Program Files\nodejs"),
	Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs")),
)


def _split_path(path_value: str) -> list[str]:
	if not path_value:
		return []
	return [entry for entry in path_value.split(os.pathsep) if entry]


def _merge_path(existing_path: str, additions: list[str]) -> str:
	merged: list[str] = []
	seen: set[str] = set()

	for entry in [*_split_path(existing_path), *additions]:
		normalized = os.path.normcase(os.path.normpath(entry))
		if normalized in seen:
			continue
		seen.add(normalized)
		merged.append(entry)

	return os.pathsep.join(merged)


def _path_contains_all(path_value: str, expected_entries: list[str]) -> bool:
	normalized_existing = {
		os.path.normcase(os.path.normpath(entry))
		for entry in _split_path(path_value)
	}
	normalized_expected = {
		os.path.normcase(os.path.normpath(entry))
		for entry in expected_entries
	}
	return normalized_expected.issubset(normalized_existing)


def discover_node_paths() -> list[str]:
	discovered: list[str] = []

	for directory in DEFAULT_NODE_DIRS:
		node_exe = directory / "node.exe"
		npm_cmd = directory / "npm.cmd"
		if node_exe.exists() and npm_cmd.exists():
			discovered.append(str(directory))

	which_node = shutil.which("node")
	if which_node:
		discovered.append(str(Path(which_node).resolve().parent))

	roaming_npm = Path(os.path.expandvars(r"%USERPROFILE%\AppData\Roaming\npm"))
	if roaming_npm.exists():
		discovered.append(str(roaming_npm))

	return _split_path(_merge_path("", discovered))


def _resolve_executable(command_names: list[str], search_paths: list[str]) -> str | None:
	for command_name in command_names:
		resolved = shutil.which(command_name, path=os.pathsep.join(search_paths))
		if resolved:
			return resolved
	return None


def get_user_path() -> str:
	try:
		with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as environment_key:
			value, _ = winreg.QueryValueEx(environment_key, "Path")
			return value
	except FileNotFoundError:
		return ""
	except OSError:
		return ""


def update_process_path(paths: list[str]) -> str:
	updated_path = _merge_path(os.environ.get("PATH", ""), paths)
	os.environ["PATH"] = updated_path
	return updated_path


def persist_user_path(paths: list[str]) -> str:
	current_user_path = get_user_path()
	updated_user_path = _merge_path(current_user_path, paths)
	with winreg.OpenKey(
		winreg.HKEY_CURRENT_USER,
		r"Environment",
		0,
		winreg.KEY_READ | winreg.KEY_SET_VALUE,
	) as environment_key:
		winreg.SetValueEx(environment_key, "Path", 0, winreg.REG_EXPAND_SZ, updated_user_path)

	ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0, 1000, None)
	return updated_user_path


def validate_node_tools(search_paths: list[str] | None = None) -> tuple[str | None, str | None, list[str]]:
	issues: list[str] = []
	path_entries = search_paths or _split_path(os.environ.get("PATH", ""))
	node_executable = _resolve_executable(["node.exe", "node"], path_entries)
	npm_executable = _resolve_executable(["npm.cmd", "npm.exe", "npm"], path_entries)

	node_version: str | None = None
	npm_version: str | None = None

	if node_executable:
		try:
			node_version = subprocess.check_output([node_executable, "-v"], text=True).strip()
		except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
			issues.append(f"Node.js validation failed: {exc}")
	else:
		issues.append("Node.js validation failed: node.exe was not found on the repaired PATH.")

	if npm_executable:
		try:
			npm_version = subprocess.check_output([npm_executable, "-v"], text=True).strip()
		except (FileNotFoundError, subprocess.CalledProcessError, OSError) as exc:
			issues.append(f"npm validation failed: {exc}")
	else:
		issues.append("npm validation failed: npm was not found on the repaired PATH.")

	return node_version, npm_version, issues


@dataclass(slots=True)
class CircuitBreakerStatus:
	discovered_paths: list[str]
	process_path: str
	user_path: str
	user_path_contains_discovered: bool
	user_path_updated: bool
	node_version: str | None
	npm_version: str | None
	issues: list[str]

	@property
	def node_ready(self) -> bool:
		return self.node_version is not None

	@property
	def npm_ready(self) -> bool:
		return self.npm_version is not None

	@property
	def persist_recommended(self) -> bool:
		return bool(self.discovered_paths) and self.npm_ready and not self.user_path_contains_discovered

	def to_dict(self) -> dict[str, object]:
		return asdict(self)


def assess_node_tooling(*, persist: bool = False) -> CircuitBreakerStatus:
	node_paths = discover_node_paths()
	issues: list[str] = []

	process_path = os.environ.get("PATH", "")
	user_path = get_user_path()
	user_path_contains_discovered = False
	user_path_updated = False

	if not node_paths:
		issues.append("No Node.js installation was discovered on this machine.")
	else:
		process_path = update_process_path(node_paths)
		user_path_contains_discovered = _path_contains_all(user_path, node_paths)
		if persist and not user_path_contains_discovered:
			updated_user_path = persist_user_path(node_paths)
			user_path_updated = updated_user_path != user_path
			user_path = updated_user_path
			user_path_contains_discovered = _path_contains_all(user_path, node_paths)

	node_version: str | None = None
	npm_version: str | None = None
	node_version, npm_version, validation_issues = validate_node_tools(_split_path(process_path))
	issues.extend(validation_issues)

	return CircuitBreakerStatus(
		discovered_paths=node_paths,
		process_path=process_path,
		user_path=user_path,
		user_path_contains_discovered=user_path_contains_discovered,
		user_path_updated=user_path_updated,
		node_version=node_version,
		npm_version=npm_version,
		issues=issues,
	)


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Repair Node.js command discovery for this Windows workstation."
	)
	parser.add_argument(
		"--persist",
		action="store_true",
		help="Write the discovered Node.js directories into the user PATH.",
	)
	parser.add_argument(
		"--json",
		action="store_true",
		help="Emit the circuit breaker status as JSON.",
	)
	args = parser.parse_args()

	status = assess_node_tooling(persist=args.persist)

	if args.json:
		import json

		print(json.dumps(status.to_dict(), indent=2))
	else:
		if status.discovered_paths:
			print("[*] Discovered Node.js directories:")
			for path in status.discovered_paths:
				print(f"    {path}")
		else:
			print("[!] No Node.js installation was discovered on this machine.")

		print("[+] Updated PATH for this process.")

		if args.persist:
			if status.user_path_updated:
				print("[+] Updated the user PATH. Restart terminals or VS Code to pick it up.")
			elif status.user_path_contains_discovered:
				print("[=] User PATH already contains the discovered Node.js directories.")

		if status.node_version:
			print(f"[+] node {status.node_version}")
		if status.npm_version:
			print(f"[+] npm {status.npm_version}")
		for issue in status.issues:
			print(f"[!] {issue}")

	return 0 if status.npm_ready else 1


if __name__ == "__main__":
	sys.exit(main())