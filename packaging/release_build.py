#!/usr/bin/env python3
"""Build and promotion helpers for GitHub release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = PROJECT_ROOT / "src" / "rcp" / "__init__.py"
# Retention chosen in docs/decisions/2026-09-02-deployment-moves-to-an-external-supervisor.md.
STALE_BUILD_DAYS = 14

_VERSION_ASSIGNMENT = re.compile(
    r'^(?P<prefix>__version__\s*=\s*["\'])(?P<version>[^"\']+)(?P<suffix>["\']\s*)$',
    re.MULTILINE,
)
# These identity rules must stay identical to the supervisor's release verifier:
# no leading zeros, build numbers from one, ASCII digits only.
_STABLE = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
_TAG = re.compile(rf"^v{_STABLE}$", re.ASCII)
_BUILD_TAG = re.compile(r"^build/[1-9][0-9]*$", re.ASCII)
_BUILD_VERSION = re.compile(r"\+build\.(?P<run>[1-9][0-9]*)\.g[0-9a-f]{7}$", re.ASCII)
_RCP_WHEEL = re.compile(
    rf"^rcp-{_STABLE}\+build\.[1-9][0-9]*\.g[0-9a-f]{{7}}-py3-none-any\.whl$", re.ASCII
)
_SUPERVISOR_WHEEL = re.compile(rf"^rcp_supervisor-{_STABLE}-py3-none-any\.whl$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReleaseBuildError(RuntimeError):
    """An expected, user-facing release validation failure."""


class _PlainArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ReleaseBuildError(message)


def stamp_version(run_number: str, sha: str, *, version_file: Path | None = None) -> str:
    if not run_number.isdecimal() or int(run_number) < 1:
        raise ReleaseBuildError(f"invalid build run number: {run_number}")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
        raise ReleaseBuildError(f"invalid commit SHA: {sha}")

    path = version_file or VERSION_FILE
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseBuildError(f"could not read {path}: {exc}") from exc
    match = _VERSION_ASSIGNMENT.search(source)
    if match is None:
        raise ReleaseBuildError(f"could not find __version__ in {path}")
    current = match.group("version")
    if "+" in current:
        raise ReleaseBuildError(f"version {current} already has a local segment")

    stamped = f"{current}+build.{int(run_number)}.g{sha[:7].lower()}"
    replacement = f"{match.group('prefix')}{stamped}{match.group('suffix')}"
    try:
        path.write_text(
            f"{source[: match.start()]}{replacement}{source[match.end() :]}",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ReleaseBuildError(f"could not write {path}: {exc}") from exc
    return stamped


def desktop_versions(project_root: Path | None = None) -> dict[str, str]:
    """Read the four native version fields that must equal the Python version."""
    web = (project_root or PROJECT_ROOT) / "web"
    try:
        package = json.loads((web / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((web / "package-lock.json").read_text(encoding="utf-8"))
        cargo = tomllib.loads((web / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
        cargo_lock = tomllib.loads((web / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
        locked = [p["version"] for p in cargo_lock["package"] if p["name"] == "rcp-desktop"]
        if len(locked) != 1:
            raise ValueError("expected exactly one rcp-desktop package in Cargo.lock")
        return {
            "web/package.json": package["version"],
            "web/package-lock.json": lock["version"],
            'web/package-lock.json packages[""]': lock["packages"][""]["version"],
            "web/src-tauri/Cargo.toml": cargo["package"]["version"],
            "web/src-tauri/Cargo.lock": locked[0],
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReleaseBuildError(f"could not read desktop versions: {exc}") from exc


def check_desktop_version(version: str, *, project_root: Path | None = None) -> None:
    mismatched = {
        field: found for field, found in desktop_versions(project_root).items() if found != version
    }
    if mismatched:
        detail = ", ".join(f"{field}={found}" for field, found in sorted(mismatched.items()))
        raise ReleaseBuildError(f"desktop versions differ from {version}: {detail}")


def _resolved_file(directory: Path, value: Path) -> Path:
    """Resolve relative values against the asset directory, not the working directory."""
    return value if value.is_absolute() else directory / value


def _assets(directory: Path, manifest_name: str) -> list[Path]:
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise ReleaseBuildError(f"could not read asset directory {directory}: {exc}") from exc
    return sorted(
        (entry for entry in entries if entry.is_file() and entry.name != manifest_name),
        key=lambda entry: entry.name,
    )


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    try:
        with path.open("rb") as asset:
            for chunk in iter(lambda: asset.read(1024 * 1024), b""):
                checksum.update(chunk)
    except OSError as exc:
        raise ReleaseBuildError(f"could not read asset {path.name}: {exc}") from exc
    return checksum.hexdigest()


def write_manifest(directory: Path, output: Path) -> Path:
    manifest = _resolved_file(directory, output)
    lines = [f"{_digest(asset)}  {asset.name}\n" for asset in _assets(directory, manifest.name)]
    try:
        manifest.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:
        raise ReleaseBuildError(f"could not write manifest {manifest}: {exc}") from exc
    return manifest


def _read_manifest(manifest: Path) -> dict[str, str]:
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReleaseBuildError(f"could not read manifest {manifest}: {exc}") from exc

    expected: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        checksum, separator, name = line.partition("  ")
        if not separator or not _SHA256.fullmatch(checksum) or not name or Path(name).name != name:
            raise ReleaseBuildError(f"invalid manifest entry on line {line_number}")
        if name in expected:
            raise ReleaseBuildError(f"duplicate manifest entry for {name}")
        expected[name] = checksum
    return expected


def verify_manifest(directory: Path, manifest_value: Path) -> None:
    manifest = _resolved_file(directory, manifest_value)
    expected = _read_manifest(manifest)
    actual_names = {asset.name for asset in _assets(directory, manifest.name)}

    for name in sorted(expected):
        asset = directory / name
        if name not in actual_names:
            raise ReleaseBuildError(f"asset {name} is missing")
        if _digest(asset) != expected[name]:
            raise ReleaseBuildError(f"asset {name} has a SHA-256 mismatch")
    for name in sorted(actual_names - expected.keys()):
        raise ReleaseBuildError(f"asset {name} is not listed in manifest")


def check_assets(directory: Path, *, require_supervisor: bool) -> None:
    """Accept complete current builds, or complete historical builds at promotion."""
    names = {asset.name for asset in _assets(directory, "manifest.sha256")}
    wheels = {name for name in names if _RCP_WHEEL.fullmatch(name)}
    if len(wheels) != 1:
        raise ReleaseBuildError("release requires exactly one stamped RCP wheel")
    expected = wheels | {"requirements.lock.txt"}
    supervisor_wheels = {name for name in names if _SUPERVISOR_WHEEL.fullmatch(name)}
    has_supervisor_assets = any(
        name.startswith(("rcp_supervisor", "supervisor-")) for name in names
    )
    if require_supervisor or has_supervisor_assets:
        if len(supervisor_wheels) != 1:
            raise ReleaseBuildError(
                "release requires exactly one independently versioned supervisor wheel"
            )
        expected |= supervisor_wheels | {"supervisor-requirements.lock.txt"}
    missing = expected - names
    if missing:
        raise ReleaseBuildError(f"release is missing required assets: {', '.join(sorted(missing))}")
    unexpected = names - expected
    if unexpected:
        raise ReleaseBuildError(f"release has unexpected assets: {', '.join(sorted(unexpected))}")
    empty = sorted(name for name in names if (directory / name).stat().st_size == 0)
    if empty:
        raise ReleaseBuildError(f"release has empty assets: {', '.join(empty)}")


def check_promotion(wheel: Path, tag: str) -> None:
    if not _TAG.fullmatch(tag):
        raise ReleaseBuildError(f"invalid release tag {tag}; expected vX.Y.Z")

    components = wheel.name.split("-")
    if len(components) < 5 or wheel.suffix != ".whl" or components[0] != "rcp":
        raise ReleaseBuildError(f"invalid wheel filename: {wheel.name}")
    version = components[1]
    build = _BUILD_VERSION.search(version)
    if build is None:
        raise ReleaseBuildError(f"wheel {wheel.name} does not contain a build version")

    base_version = version.split("+", maxsplit=1)[0]
    if base_version != tag[1:]:
        raise ReleaseBuildError(
            f"build {build.group('run')} has base version {base_version} but tag {tag} was "
            "requested; bump src/rcp/__init__.py first"
        )


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ReleaseBuildError(f"release {field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseBuildError(f"invalid {field} timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ReleaseBuildError(f"{field} timestamp has no timezone: {value}")
    return parsed.astimezone(UTC)


def select_stale_builds(releases_file: Path, now: str, days: int) -> list[str]:
    if days < 0:
        raise ReleaseBuildError("retention days must not be negative")
    try:
        releases = json.loads(releases_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError(f"could not read releases from {releases_file}: {exc}") from exc
    if not isinstance(releases, list):
        raise ReleaseBuildError("release list must be a JSON array")

    cutoff = _timestamp(now, "now") - timedelta(days=days)
    stale: list[tuple[datetime, str]] = []
    for release in releases:
        if not isinstance(release, dict):
            raise ReleaseBuildError("release list contains a non-object entry")
        tag_name = release.get("tagName")
        is_prerelease = release.get("isPrerelease")
        if not isinstance(tag_name, str) or not isinstance(is_prerelease, bool):
            raise ReleaseBuildError("release entry has invalid tagName or isPrerelease")
        if (
            is_prerelease
            and _BUILD_TAG.fullmatch(tag_name)
            and _timestamp(release.get("createdAt"), "createdAt") < cutoff
        ):
            stale.append((_timestamp(release["createdAt"], "createdAt"), tag_name))
    return [tag_name for _, tag_name in sorted(stale)]


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = _PlainArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    stamp = subparsers.add_parser("stamp-version")
    stamp.add_argument("--run-number", required=True)
    stamp.add_argument("--sha", required=True)

    desktop = subparsers.add_parser("check-desktop-version")
    desktop.add_argument("version")

    write = subparsers.add_parser("write-manifest")
    write.add_argument("directory", type=Path)
    write.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify-manifest")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--manifest", type=Path, required=True)

    assets = subparsers.add_parser("check-assets")
    assets.add_argument("directory", type=Path)
    assets.add_argument("--require-supervisor", action="store_true")

    promotion = subparsers.add_parser("check-promotion")
    promotion.add_argument("--wheel", type=Path, required=True)
    promotion.add_argument("--tag", required=True)

    stale = subparsers.add_parser("select-stale-builds")
    stale.add_argument("--releases", type=Path, required=True)
    stale.add_argument("--now", required=True)
    stale.add_argument("--days", type=int, default=STALE_BUILD_DAYS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _arguments(argv)
        if arguments.command == "stamp-version":
            print(stamp_version(arguments.run_number, arguments.sha))
        elif arguments.command == "check-desktop-version":
            check_desktop_version(arguments.version)
        elif arguments.command == "write-manifest":
            write_manifest(arguments.directory, arguments.output)
        elif arguments.command == "verify-manifest":
            verify_manifest(arguments.directory, arguments.manifest)
        elif arguments.command == "check-assets":
            check_assets(arguments.directory, require_supervisor=arguments.require_supervisor)
        elif arguments.command == "check-promotion":
            check_promotion(arguments.wheel, arguments.tag)
        elif arguments.command == "select-stale-builds":
            for tag_name in select_stale_builds(arguments.releases, arguments.now, arguments.days):
                print(tag_name)
    except ReleaseBuildError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
