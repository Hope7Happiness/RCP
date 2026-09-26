from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "packaging" / "release_build.py"
SPEC = importlib.util.spec_from_file_location("release_build", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_build)


@pytest.fixture
def desktop_copy(tmp_path: Path) -> Path:
    for name in (
        "package.json",
        "package-lock.json",
        "src-tauri/Cargo.toml",
        "src-tauri/Cargo.lock",
    ):
        destination = tmp_path / "web" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SCRIPT.parent.parent / "web" / name, destination)
    return tmp_path


def test_desktop_versions_match_the_python_version() -> None:
    namespace: dict[str, str] = {}
    exec((SCRIPT.parent.parent / "src/rcp/__init__.py").read_text(), namespace)
    release_build.check_desktop_version(namespace["__version__"])


def test_check_desktop_version_rejects_one_stale_field(desktop_copy: Path) -> None:
    version = release_build.desktop_versions(desktop_copy)["web/package.json"]
    release_build.check_desktop_version(version, project_root=desktop_copy)
    cargo = desktop_copy / "web/src-tauri/Cargo.toml"
    cargo.write_text(cargo.read_text().replace(f'version = "{version}"', 'version = "0.0.1"', 1))
    with pytest.raises(release_build.ReleaseBuildError):
        release_build.check_desktop_version(version, project_root=desktop_copy)


def test_stamp_version_stamps_plain_version(tmp_path: Path) -> None:
    version_file = tmp_path / "__init__.py"
    version_file.write_text('"""RCP."""\n\n__version__ = "0.3.2"\n', encoding="utf-8")

    stamped = release_build.stamp_version(
        "412",
        "FE06636abcde0123456789abcdef0123456789ab",
        version_file=version_file,
    )

    assert stamped == "0.3.2+build.412.gfe06636"
    assert '__version__ = "0.3.2+build.412.gfe06636"' in version_file.read_text(encoding="utf-8")


def test_stamp_version_refuses_existing_local_segment(tmp_path: Path) -> None:
    version_file = tmp_path / "__init__.py"
    original = '__version__ = "0.3.2+build.411.g0123456"\n'
    version_file.write_text(original, encoding="utf-8")

    with pytest.raises(release_build.ReleaseBuildError):
        release_build.stamp_version(
            "412",
            "fe06636abcde0123456789abcdef0123456789ab",
            version_file=version_file,
        )

    assert version_file.read_text(encoding="utf-8") == original


def test_manifest_round_trip_detects_tampered_asset(tmp_path: Path) -> None:
    (tmp_path / "a.whl").write_bytes(b"wheel")
    (tmp_path / "requirements.lock.txt").write_bytes(b"locked")

    manifest = release_build.write_manifest(tmp_path, Path("manifest.sha256"))

    assert manifest.read_text(encoding="utf-8").splitlines() == sorted(
        manifest.read_text(encoding="utf-8").splitlines(),
        key=lambda line: line.split("  ", maxsplit=1)[1],
    )
    release_build.verify_manifest(tmp_path, Path("manifest.sha256"))

    (tmp_path / "a.whl").write_bytes(b"Wheel")
    with pytest.raises(release_build.ReleaseBuildError):
        release_build.verify_manifest(tmp_path, Path("manifest.sha256"))


def test_verify_manifest_accepts_manifest_outside_asset_directory(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "a.whl").write_bytes(b"wheel")
    manifest = release_build.write_manifest(assets, tmp_path / "manifest.sha256")

    release_build.verify_manifest(assets, manifest)


def test_verify_manifest_reports_missing_listed_asset(tmp_path: Path) -> None:
    asset = tmp_path / "a.whl"
    asset.write_bytes(b"wheel")
    release_build.write_manifest(tmp_path, Path("manifest.sha256"))
    asset.unlink()

    with pytest.raises(release_build.ReleaseBuildError) as error:
        release_build.verify_manifest(tmp_path, Path("manifest.sha256"))
    assert str(error.value) == "asset a.whl is missing"


def test_verify_manifest_reports_extra_unlisted_asset(tmp_path: Path) -> None:
    (tmp_path / "a.whl").write_bytes(b"wheel")
    release_build.write_manifest(tmp_path, Path("manifest.sha256"))
    (tmp_path / "extra.whl").write_bytes(b"extra")

    with pytest.raises(release_build.ReleaseBuildError) as error:
        release_build.verify_manifest(tmp_path, Path("manifest.sha256"))
    assert str(error.value) == "asset extra.whl is not listed in manifest"


def test_promotion_accepts_matching_base_version() -> None:
    release_build.check_promotion(Path("rcp-0.3.2+build.412.gfe06636-py3-none-any.whl"), "v0.3.2")


def test_promotion_refuses_mismatched_base_version() -> None:
    with pytest.raises(
        release_build.ReleaseBuildError,
    ):
        release_build.check_promotion(
            Path("rcp-0.3.2+build.412.gfe06636-py3-none-any.whl"), "v0.4.0"
        )


def test_promotion_refuses_invalid_tag() -> None:
    with pytest.raises(release_build.ReleaseBuildError):
        release_build.check_promotion(
            Path("rcp-0.3.2+build.412.gfe06636-py3-none-any.whl"), "0.3.2"
        )


def test_select_stale_builds_selects_only_expired_prerelease_builds(tmp_path: Path) -> None:
    releases_file = tmp_path / "releases.json"
    releases_file.write_text(
        json.dumps(
            [
                {
                    "tagName": "v0.3.2",
                    "isPrerelease": False,
                    "createdAt": "2026-06-01T00:00:00Z",
                },
                {
                    "tagName": "build/413",
                    "isPrerelease": True,
                    "createdAt": "2026-08-20T00:00:00Z",
                },
                {
                    "tagName": "build/412",
                    "isPrerelease": True,
                    "createdAt": "2026-07-01T00:00:00Z",
                },
                {
                    "tagName": "build/manual",
                    "isPrerelease": True,
                    "createdAt": "2026-07-01T00:00:00Z",
                },
                {
                    "tagName": "build/412/candidate",
                    "isPrerelease": True,
                    "createdAt": "2026-07-01T00:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )

    assert release_build.select_stale_builds(
        releases_file, "2026-09-02T00:00:00Z", release_build.STALE_BUILD_DAYS
    ) == ["build/412"]


RCP_WHEEL = "rcp-0.3.2+build.412.gfe06636-py3-none-any.whl"
SUPERVISOR_WHEEL = "rcp_supervisor-0.1.0-py3-none-any.whl"


@pytest.mark.parametrize("supervisor", [False, True])
def test_promotion_asset_contract_accepts_complete_generations(
    tmp_path: Path, supervisor: bool
) -> None:
    names = [RCP_WHEEL, "requirements.lock.txt"]
    if supervisor:
        names += [SUPERVISOR_WHEEL, "supervisor-requirements.lock.txt"]
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    release_build.write_manifest(tmp_path, Path("manifest.sha256"))

    release_build.verify_manifest(tmp_path, Path("manifest.sha256"))
    release_build.check_assets(tmp_path, require_supervisor=False)
    release_build.check_promotion(tmp_path / RCP_WHEEL, "v0.3.2")
    if supervisor:
        release_build.check_assets(tmp_path, require_supervisor=True)
    else:
        with pytest.raises(release_build.ReleaseBuildError):
            release_build.check_assets(tmp_path, require_supervisor=True)


@pytest.mark.parametrize(
    ("names", "message"),
    [
        ([RCP_WHEEL, "requirements.lock.txt", SUPERVISOR_WHEEL], "supervisor-requirements"),
        (
            [RCP_WHEEL, "requirements.lock.txt", "supervisor-requirements.lock.txt"],
            "supervisor wheel",
        ),
        ([RCP_WHEEL], "requirements.lock.txt"),
        (["requirements.lock.txt"], "RCP wheel"),
        ([RCP_WHEEL, "requirements.lock.txt", "other.whl"], "unexpected assets"),
        (
            [RCP_WHEEL, "requirements.lock.txt", "rcp_supervisor-0.1.0+build.2-py3-none-any.whl"],
            "supervisor wheel",
        ),
        (
            [
                RCP_WHEEL,
                "requirements.lock.txt",
                SUPERVISOR_WHEEL,
                "rcp_supervisor-0.2.0-py3-none-any.whl",
            ],
            "supervisor wheel",
        ),
    ],
)
def test_asset_contract_refuses_incomplete_or_unrecognized_release(
    tmp_path: Path, names: list[str], message: str
) -> None:
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    release_build.write_manifest(tmp_path, Path("manifest.sha256"))
    release_build.verify_manifest(tmp_path, Path("manifest.sha256"))

    with pytest.raises(release_build.ReleaseBuildError):
        release_build.check_assets(tmp_path, require_supervisor=False)


def test_asset_contract_refuses_an_empty_asset(tmp_path: Path) -> None:
    for name in (RCP_WHEEL, SUPERVISOR_WHEEL, "requirements.lock.txt"):
        (tmp_path / name).write_bytes(name.encode())
    (tmp_path / "supervisor-requirements.lock.txt").touch()

    with pytest.raises(release_build.ReleaseBuildError):
        release_build.check_assets(tmp_path, require_supervisor=True)


def test_promotion_rejects_supervisor_wheel_as_rcp_version() -> None:
    with pytest.raises(release_build.ReleaseBuildError):
        release_build.check_promotion(Path(SUPERVISOR_WHEEL), "v0.1.0")


@pytest.mark.parametrize(
    "wheel",
    [
        "rcp-0.3.2+build.0.gfe06636-py3-none-any.whl",
        "rcp-0.3.2+build.01.gfe06636-py3-none-any.whl",
        "rcp-01.3.2+build.412.gfe06636-py3-none-any.whl",
        "rcp_supervisor-01.0.0-py3-none-any.whl",
    ],
)
def test_asset_contract_refuses_noncanonical_version(tmp_path: Path, wheel: str) -> None:
    supervisor = wheel.startswith("rcp_supervisor-")
    names = [
        RCP_WHEEL if supervisor else wheel,
        wheel if supervisor else SUPERVISOR_WHEEL,
        "requirements.lock.txt",
        "supervisor-requirements.lock.txt",
    ]
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
    release_build.write_manifest(tmp_path, Path("manifest.sha256"))
    with pytest.raises(release_build.ReleaseBuildError):
        release_build.check_assets(tmp_path, require_supervisor=True)


def test_promotion_refuses_leading_zero_build() -> None:
    with pytest.raises(release_build.ReleaseBuildError):
        release_build.check_promotion(
            Path("rcp-0.3.2+build.01.gfe06636-py3-none-any.whl"), "v0.3.2"
        )
