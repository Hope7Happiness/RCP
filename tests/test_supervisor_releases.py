from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from rcp_supervisor import limits, releases
from rcp_supervisor.errors import SupervisorError

from tests.supervisor_helpers import (
    RCP_WHEEL,
    SUPERVISOR_WHEEL,
    VERSION,
    bundle_assets,
    make_bundle,
    refresh_manifest,
    wheel_bytes,
)


def _metadata(assets: dict[str, bytes], *, tag: str = "v0.3.2") -> dict:
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "target_commitish": "fe06636" + "0" * 33,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": len(data),
                "browser_download_url": (
                    f"https://github.com/Zhi0467/RCP/releases/download/{tag}/"
                    f"{urllib.parse.quote(name)}"
                ),
            }
            for name, data in assets.items()
        ],
    }


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch):
    """Real HTTP reads with a test-only mapping from fixed GitHub URLs to loopback."""
    assets = bundle_assets()
    fixture = {
        "assets": assets,
        "metadata": _metadata(assets),
        "requests": [],
        "status": 200,
        "length": True,
        "redirect": None,
        "companion": None,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            fixture["requests"].append(self.path)
            if self.path.startswith("/repos/"):
                if "/tags/desktop-" in self.path:
                    metadata = fixture["companion"]
                elif self.path.endswith("/releases"):
                    metadata = [fixture["metadata"], fixture["companion"]]
                else:
                    metadata = fixture["metadata"]
                data = json.dumps(metadata).encode()
            else:
                name = urllib.parse.unquote(self.path.rsplit("/", 1)[-1])
                data = fixture["assets"][name]
            self.send_response(fixture["status"])
            if fixture["redirect"]:
                self.send_header("Location", fixture["redirect"])
            if fixture["length"]:
                self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def open_local(request, timeout):
        local = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}{urllib.parse.urlsplit(request.full_url).path}",
            headers=dict(request.header_items()),
        )
        response = urllib.request.build_opener(releases._GitHubRedirects()).open(
            local, timeout=timeout
        )
        response.url = request.full_url
        return response

    monkeypatch.setattr(releases, "_open", open_local)
    try:
        yield fixture
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_verify_release_binds_both_wheel_identities_without_imports(tmp_path: Path) -> None:
    directory = tmp_path / "release"
    make_bundle(directory)

    verified = releases.verify_release(directory)

    assert verified.directory == directory
    assert (
        verified.manifest_sha256
        == hashlib.sha256((directory / "manifest.sha256").read_bytes()).hexdigest()
    )
    assert (verified.version, verified.build, verified.commit) == (VERSION, 412, "fe06636")
    assert verified.wheel == directory / RCP_WHEEL
    assert verified.requirements == directory / "requirements.lock.txt"
    assert verified.supervisor_wheel == directory / SUPERVISOR_WHEEL
    assert verified.supervisor_requirements == directory / "supervisor-requirements.lock.txt"
    assert verified.supervisor_version == "0.1.0"


def test_verified_manifest_digest_seals_the_bytes_actually_checked(
    tmp_path: Path, monkeypatch
) -> None:
    directory = make_bundle(tmp_path / "release")
    manifest = directory / "manifest.sha256"
    checked = manifest.read_bytes()
    parse = releases._manifest

    def replace_after_parse(data: bytes) -> dict[str, str]:
        expected = parse(data)
        manifest.write_bytes(b"".join(reversed(data.splitlines(keepends=True))))
        return expected

    monkeypatch.setattr(releases, "_manifest", replace_after_parse)

    verified = releases.verify_release(directory)

    assert verified.manifest_sha256 == hashlib.sha256(checked).hexdigest()
    assert verified.manifest_sha256 != hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_wheel_metadata_uses_the_hashed_bytes_despite_path_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    directory = make_bundle(tmp_path / "release")
    wheel = directory / RCP_WHEEL
    checked = wheel.read_bytes()
    parse = releases._wheel_version

    def replace_before_metadata(path: Path, distribution: str, *args) -> str:
        if path == wheel:
            path.write_bytes(wheel_bytes("rcp", VERSION, metadata_version="0.3.1"))
        return parse(path, distribution, *args)

    monkeypatch.setattr(releases, "_wheel_version", replace_before_metadata)

    verified = releases.verify_release(directory)

    assert verified.version == VERSION
    assert wheel.read_bytes() != checked


def test_download_failure_does_not_expose_signed_redirect_url(tmp_path: Path, monkeypatch) -> None:
    signed_url = "https://release-assets.githubusercontent.com/asset?sig=private-value"
    failure = urllib.error.URLError(f"failed to read {signed_url}")

    def fail_transport(request, timeout):
        raise failure

    monkeypatch.setattr(releases, "_open", fail_transport)

    with pytest.raises(SupervisorError) as error:
        releases.fetch_release("stable", tmp_path / "release")

    assert error.value.__cause__ is failure


@pytest.mark.parametrize("selector, endpoint", [("stable", "/latest"), ("v0.3.2", "/tags/v0.3.2")])
def test_fetch_publishes_verified_bundle_and_reuses_it(
    github, tmp_path: Path, selector, endpoint
) -> None:
    directory = tmp_path / "cache" / "release"

    verified = releases.fetch_release(selector, directory)

    assert verified.version == VERSION
    assert github["requests"][0] == f"/repos/Zhi0467/RCP/releases{endpoint}"
    assert {path.name for path in directory.iterdir()} == github["assets"].keys()
    assert not list(directory.parent.glob(".release.fetch-*"))
    identities = {path.name: path.stat().st_ino for path in directory.iterdir()}
    count = len(github["requests"])

    assert releases.fetch_release(selector, directory) == verified

    assert len(github["requests"]) == count + 2  # Resolve identity and compare manifest only.
    assert {path.name: path.stat().st_ino for path in directory.iterdir()} == identities


def test_stable_accepts_five_assets_with_companion_but_rejects_sixth(github, tmp_path) -> None:
    companion = _metadata({"RCP.zip": b"desktop"}, tag="desktop-v0.3.2")
    companion["prerelease"] = True
    github["companion"] = companion

    verified = releases.fetch_release("stable", tmp_path / "accepted")

    assert verified.release_tag == "v0.3.2"
    assert len(list(verified.directory.iterdir())) == 5
    assert github["requests"][0] == "/repos/Zhi0467/RCP/releases/latest"
    assert not any("desktop-v" in path for path in github["requests"])
    github["metadata"]["assets"].extend(_metadata({"RCP.zip": b"desktop"})["assets"])
    github["requests"].clear()

    with pytest.raises(SupervisorError):
        releases.fetch_release("stable", tmp_path / "rejected")

    assert github["requests"] == ["/repos/Zhi0467/RCP/releases/latest"]
    assert not (tmp_path / "rejected").exists()


@pytest.mark.parametrize(
    "selector",
    ["main", "build/412", "v0.3.2rc1", "v0.3.2+build.412", "../../x", "https://example.com"],
)
def test_fetch_rejects_nonrelease_selectors_before_network(
    github, tmp_path: Path, selector
) -> None:
    with pytest.raises(SupervisorError, match="selector"):
        releases.fetch_release(selector, tmp_path / "release")
    assert not github["requests"]


@pytest.mark.parametrize(
    "field,value", [("prerelease", True), ("draft", True), ("tag_name", "build/412")]
)
def test_fetch_rejects_unpromoted_release_metadata(github, tmp_path: Path, field, value) -> None:
    github["metadata"][field] = value
    with pytest.raises(SupervisorError, match="published stable"):
        releases.fetch_release("stable", tmp_path / "release")
    assert len(github["requests"]) == 1


@pytest.mark.parametrize("missing", [SUPERVISOR_WHEEL, "supervisor-requirements.lock.txt"])
def test_fetch_reports_old_release_missing_supervisor(github, tmp_path: Path, missing: str) -> None:
    github["metadata"]["assets"] = [
        asset for asset in github["metadata"]["assets"] if asset["name"] != missing
    ]
    with pytest.raises(SupervisorError, match="missing the supervisor"):
        releases.fetch_release("stable", tmp_path / "release")
    assert len(github["requests"]) == 1


@pytest.mark.parametrize("change", ["duplicate", "unsafe", "wrong-url", "huge", "unuploaded"])
def test_fetch_rejects_invalid_asset_metadata(github, tmp_path: Path, change: str) -> None:
    assets = github["metadata"]["assets"]
    if change == "duplicate":
        assets.append(assets[0])
    elif change == "unsafe":
        assets[0]["name"] = "../rcp.whl"
    elif change == "wrong-url":
        assets[0]["browser_download_url"] = (
            "https://github.com/other/repo/releases/download/v0.3.2/a.whl"
        )
    elif change == "huge":
        assets[0]["size"] = limits.MAX_WHEEL_BYTES + 1
    else:
        assets[0]["state"] = "new"
    with pytest.raises(SupervisorError):
        releases.fetch_release("stable", tmp_path / "release")
    assert len(github["requests"]) == 1
    assert not (tmp_path / "release").exists()


def test_fetch_hash_failure_never_publishes_partial_bundle(github, tmp_path: Path) -> None:
    github["assets"][RCP_WHEEL] = b"x" * len(github["assets"][RCP_WHEEL])
    directory = tmp_path / "release"
    with pytest.raises(SupervisorError, match="SHA-256 mismatch"):
        releases.fetch_release("stable", directory)
    assert not directory.exists()
    assert not list(tmp_path.glob(".release.fetch-*"))


def test_fetch_never_replaces_different_verified_cache(github, tmp_path: Path) -> None:
    directory = tmp_path / "release"
    make_bundle(directory)
    prior = (directory / "requirements.lock.txt").read_bytes()
    github["assets"]["requirements.lock.txt"] = b"# a republished lock\n"
    refresh_manifest(github["assets"])
    github["metadata"] = _metadata(github["assets"])

    with pytest.raises(SupervisorError, match="immutable release bundle differs"):
        releases.fetch_release("stable", directory)

    assert (directory / "requirements.lock.txt").read_bytes() == prior
    assert len(github["requests"]) == 2


def test_fetch_reverifies_cache_and_refuses_to_repair_tampering(github, tmp_path: Path) -> None:
    directory = tmp_path / "release"
    make_bundle(directory)
    (directory / RCP_WHEEL).write_bytes(b"tampered")

    with pytest.raises(SupervisorError, match="SHA-256 mismatch"):
        releases.fetch_release("stable", directory)

    assert (directory / RCP_WHEEL).read_bytes() == b"tampered"
    assert len(github["requests"]) == 2


def test_fetch_rejects_tag_wheel_version_mismatch(github, tmp_path: Path) -> None:
    github["metadata"] = _metadata(github["assets"], tag="v0.4.0")
    with pytest.raises(SupervisorError, match="wheel base version"):
        releases.fetch_release("stable", tmp_path / "release")
    assert not (tmp_path / "release").exists()


def test_fetch_refuses_wrong_pinned_tag(github, tmp_path: Path) -> None:
    with pytest.raises(SupervisorError, match="different release"):
        releases.fetch_release("v0.4.0", tmp_path / "release")


@pytest.mark.parametrize("length", [True, False])
def test_http_response_size_is_bounded(github, tmp_path: Path, monkeypatch, length: bool) -> None:
    github["length"] = length
    monkeypatch.setattr(limits, "MAX_RELEASE_METADATA_BYTES", 20)
    with pytest.raises(SupervisorError, match="size limit"):
        releases.fetch_release("stable", tmp_path / "release")


def test_http_status_failure_is_actionable(github, tmp_path: Path) -> None:
    github["status"] = 404
    with pytest.raises(SupervisorError, match="404"):
        releases.fetch_release("stable", tmp_path / "release")


def test_http_redirect_never_contacts_an_unapproved_host(github, tmp_path: Path) -> None:
    github["status"] = 302
    github["redirect"] = "https://example.invalid/steal"
    with pytest.raises(SupervisorError, match="approved public GitHub HTTPS host"):
        releases.fetch_release("stable", tmp_path / "release")
    assert len(github["requests"]) == 1


def test_fetch_enforces_total_deadline(github, tmp_path: Path, monkeypatch) -> None:
    times = iter([0, 1, 1, limits.FETCH_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(releases, "time", SimpleNamespace(monotonic=lambda: next(times)))
    with pytest.raises(SupervisorError, match="time limit"):
        releases.fetch_release("stable", tmp_path / "release")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/Zhi0467/RCP/releases/download/v0.3.2/a.whl",
        "https://release-assets.githubusercontent.com.evil.test/a.whl",
        "https://user:password@release-assets.githubusercontent.com/a.whl",
        "https://release-assets.githubusercontent.com:8443/a.whl",
        "file:///tmp/a.whl",
        "https://127.0.0.1/a.whl",
        "https://raw.githubusercontent.com/Zhi0467/RCP/main/a.whl",
    ],
)
def test_asset_transport_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(SupervisorError):
        releases._validate_url(url)


@pytest.mark.parametrize(
    "host",
    [
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    ],
)
def test_asset_redirect_accepts_documented_exact_hosts(host: str) -> None:
    request = urllib.request.Request(
        "https://github.com/Zhi0467/RCP/releases/download/v0.3.2/a.whl"
    )
    redirected = releases._GitHubRedirects().redirect_request(
        request, None, 302, "Found", {}, f"https://{host}/asset?token=public-signed"
    )
    assert urllib.parse.urlsplit(redirected.full_url).hostname == host


@pytest.mark.parametrize(
    "change", ["duplicate", "traversal", "backslash", "extra", "missing", "self"]
)
def test_verify_rejects_invalid_manifest(tmp_path: Path, change: str) -> None:
    assets = bundle_assets()
    manifest = assets["manifest.sha256"]
    if change == "duplicate":
        manifest += manifest.splitlines(keepends=True)[0]
    elif change == "traversal":
        manifest = manifest.replace(b"  requirements.lock.txt", b"  ../requirements.lock.txt")
    elif change == "backslash":
        manifest = manifest.replace(b"  requirements.lock.txt", b"  a\\requirements.lock.txt")
    elif change == "extra":
        manifest += b"0" * 64 + b"  unexpected.txt\n"
    elif change == "missing":
        manifest = b"".join(manifest.splitlines(keepends=True)[1:])
    else:
        manifest += b"0" * 64 + b"  manifest.sha256\n"
    assets["manifest.sha256"] = manifest
    directory = tmp_path / "release"
    make_bundle(directory, assets)
    with pytest.raises(SupervisorError):
        releases.verify_release(directory)


@pytest.mark.parametrize("target", ["directory", RCP_WHEEL])
def test_verify_rejects_symlinked_bundles_or_assets(tmp_path: Path, target: str) -> None:
    directory = tmp_path / "release"
    make_bundle(directory)
    if target == "directory":
        linked = tmp_path / "linked"
        linked.symlink_to(directory)
        directory = linked
    else:
        outside = tmp_path / "outside.whl"
        (directory / target).rename(outside)
        (directory / target).symlink_to(outside)
    with pytest.raises(SupervisorError, match="real directory|regular file"):
        releases.verify_release(directory)


def test_verify_rejects_extra_unlisted_files(tmp_path: Path) -> None:
    directory = tmp_path / "release"
    make_bundle(directory)
    (directory / "extra").write_bytes(b"unexpected")
    with pytest.raises(SupervisorError, match="five required"):
        releases.verify_release(directory)


def test_verify_rejects_wheel_metadata_not_matching_filename(tmp_path: Path) -> None:
    assets = bundle_assets()
    assets[RCP_WHEEL] = wheel_bytes("rcp", VERSION, metadata_version="0.3.1")
    refresh_manifest(assets)
    directory = tmp_path / "release"
    make_bundle(directory, assets)
    with pytest.raises(SupervisorError, match="metadata does not match"):
        releases.verify_release(directory)


@pytest.mark.parametrize(
    "entry", ["../outside", "/absolute", "a\\outside", "rcp/../outside", "rcp//alias"]
)
def test_verify_rejects_unsafe_wheel_members(tmp_path: Path, entry: str) -> None:
    assets = bundle_assets()
    output = io.BytesIO(assets[RCP_WHEEL])
    with zipfile.ZipFile(output, "a") as wheel:
        wheel.writestr(entry, "bad")
    assets[RCP_WHEEL] = output.getvalue()
    refresh_manifest(assets)
    directory = tmp_path / "release"
    make_bundle(directory, assets)
    with pytest.raises(SupervisorError, match="unsafe or duplicate"):
        releases.verify_release(directory)


def test_verify_bounds_wheel_decompression(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "release"
    make_bundle(directory)
    monkeypatch.setattr(limits, "MAX_UNPACKED_WHEEL_BYTES", 10)
    with pytest.raises(SupervisorError, match="unpacked contents"):
        releases.verify_release(directory)


def test_verify_bounds_wheel_metadata(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "release"
    make_bundle(directory)
    monkeypatch.setattr(limits, "MAX_WHEEL_METADATA_BYTES", 10)
    with pytest.raises(SupervisorError, match="metadata exceeds"):
        releases.verify_release(directory)


@pytest.mark.parametrize("commit", [None, "main", "a" * 7, "A" * 40, "b" * 40])
def test_fetch_requires_full_release_commit_bound_to_wheel(tmp_path, github, commit):
    github["metadata"]["target_commitish"] = commit
    with pytest.raises(SupervisorError, match="commit|identity"):
        releases.fetch_release("stable", tmp_path / "bundle")


def test_local_verification_never_invents_a_full_commit(tmp_path):
    release = releases.verify_release(make_bundle(tmp_path / "bundle"))
    assert release.full_commit is None
    assert release.release_tag is None


def test_verify_rejects_non_ascii_metadata_name(tmp_path: Path) -> None:
    assets = bundle_assets()
    assets[RCP_WHEEL] = wheel_bytes(
        "rcp",
        VERSION,
        raw_metadata=b"Metadata-Version: 2.3\nName: rcp\xff\nVersion: " + VERSION.encode() + b"\n",
    )
    refresh_manifest(assets)
    directory = make_bundle(tmp_path / "release", assets)
    with pytest.raises(SupervisorError, match="metadata does not match"):
        releases.verify_release(directory)


def test_verify_rejects_fifo_substitution_without_blocking(tmp_path: Path, monkeypatch) -> None:
    directory = make_bundle(tmp_path / "release")
    read_regular = releases._read_regular
    errors = []

    def substitute_fifo(path, maximum):
        if path.name == RCP_WHEEL:
            path.unlink()
            os.mkfifo(path)
        return read_regular(path, maximum)

    def verify():
        try:
            releases.verify_release(directory)
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(releases, "_read_regular", substitute_fifo)
    thread = threading.Thread(target=verify, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive(), "verification blocked on a substituted FIFO"
    assert len(errors) == 1
    assert isinstance(errors[0], SupervisorError)
    assert f"release asset {RCP_WHEEL} must be a regular file" in str(errors[0])


def test_download_bounds_slow_response_headers(monkeypatch) -> None:
    stop = threading.Event()
    started = threading.Event()
    opened = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
            started.set()
            try:
                for _ in range(60):
                    if stop.wait(0.05):
                        break
                    self.wfile.write(b"a")
                self.wfile.write(b"\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def open_local(request, timeout):
        try:
            response = urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/", timeout=timeout
            )
            response.url = request.full_url
            return response
        finally:
            opened.set()

    monkeypatch.setattr(releases, "_open", open_local)
    monkeypatch.setattr(limits, "FETCH_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(limits, "HTTP_TIMEOUT_SECONDS", 1)
    start = time.monotonic()
    try:
        with pytest.raises(SupervisorError, match="time limit"):
            releases._download(
                "https://release-assets.githubusercontent.com/asset",
                io.BytesIO(),
                1024,
                start + limits.FETCH_TIMEOUT_SECONDS,
            )
        assert time.monotonic() - start < 1.5
        assert started.is_set()
    finally:
        stop.set()
        assert opened.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_download_closes_response_returned_after_deadline(monkeypatch) -> None:
    finish = threading.Event()
    closed = threading.Event()

    def open_late(request, timeout):
        assert finish.wait(timeout=5)
        return SimpleNamespace(close=closed.set)

    monkeypatch.setattr(releases, "_open", open_late)
    try:
        with pytest.raises(SupervisorError, match="time limit"):
            releases._download(
                "https://release-assets.githubusercontent.com/asset",
                io.BytesIO(),
                1024,
                time.monotonic() + 0.1,
            )
    finally:
        finish.set()
    assert closed.wait(timeout=5)
