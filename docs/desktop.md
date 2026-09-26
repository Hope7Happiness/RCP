# Desktop testing and release

RCP's desktop shell is a native macOS entrance to the same React interface and FastAPI
backend used by the browser path. This document covers the desktop-specific development,
verification, and release work that does not belong in the main README.

The current desktop target is Apple Silicon macOS. Read `web/src-tauri/tauri.conf.json`
for the authoritative platform settings and `web/package.json` for the available commands.

## Prerequisites

Start with the source installation in the [install guide](install.md#install-from-source). Desktop work
also requires the Rust toolchain from [rustup](https://rustup.rs). rustup installs `cargo`
under `~/.cargo/bin` and offers to add that directory to your shell's PATH. If you declined,
or a `desktop:*` command fails with `failed to run 'cargo metadata' command ... No such file
or directory`, load it in that shell first:

```bash
. "$HOME/.cargo/env"
```

Codex CLI or Claude Code must be installed and authenticated separately to exercise agent
features.

## Test the desktop app

Run the Rust checks when native code or desktop packaging changes:

```bash
cargo fmt --manifest-path web/src-tauri/Cargo.toml -- --check
cargo clippy --manifest-path web/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path web/src-tauri/Cargo.toml --locked
```

Use the live shell for the normal native development loop:

```bash
npm --prefix web run desktop:dev
```

This starts Vite, compiles the Rust shell in debug mode, and starts or reuses the Python
backend from the checkout.

Use the same-origin mode when the behavior depends on the frontend being served by the
backend rather than by Vite:

```bash
npm --prefix web run desktop:same-origin
```

Build a Finder-launchable development app when the behavior depends on application launch,
window lifecycle, native dialogs, or `Info.plist` configuration:

```bash
npm --prefix web run desktop:build-dev
```

The bundle is written to:

```text
web/src-tauri/target/debug/bundle/macos/RCP.app
```

`RCP.app` records the checkout and absolute `uv` executable in its `Info.plist` and
launches the backend from source. Rebuild it after Rust or Tauri configuration changes.
An older `/Applications/RCP.app` is a separate copy and is not changed by that build.
Quit RCP with Cmd+Q before replacing and reopening that copy:

```bash
ditto web/src-tauri/target/debug/bundle/macos/RCP.app /Applications/RCP.app
open /Applications/RCP.app
```

### Only the menu Quit stops the backend

`Quit RCP` in the application menu, and its Cmd+Q accelerator, are one custom
`MenuItem` routed through `on_menu_event` to `request_app_quit`. That path runs the
shutdown and stops the backend the app owns.

Every other quit gesture leaves that backend running: the Dock icon's Quit,
`osascript -e 'quit app "RCP"'`, and logout or restart. macOS terminates the process
without Tauri emitting `RunEvent::ExitRequested`, so the handler in `src/lib.rs` never
runs. Measured on 2026-08-29 by logging every `ExitRequested` and observing none, while
the shell exited and its backend kept serving.

This matters because a leaked backend still holds 8421, so the next launch adopts it
through `--reuse-existing` and source edits do not take effect. Stop it explicitly:

```bash
pkill -f "rcp serve"
```

A fix belongs in the macOS `applicationShouldTerminate:` delegate, not in a wider match
arm. The handler's `code: None` guard is deliberate: the shutdown's own `app.exit(code)`
re-enters that event with `Some(code)`, so matching every code would re-enter quit.

A successful build is not the desktop test. Open the relevant bundle through Finder,
exercise the affected workflow, inspect the visible result, and check the backend log for
errors. Native window, Quit, artifact, packaged-environment, update, and text-scale
behavior are verified through the desktop itself; a browser check does not stand in
for any of them.

## WebView origin probes

Two example probes drive a real WKWebView to answer questions browser tests
cannot. The original HTTP probe remains evidence only. The HTTPS probe exercises
the same native trust primitive now linked into every macOS desktop build; its
test servers and automatic navigation remain example-only.

`run-loopback-origin-probe.py` is the original HTTP drive. It records that a
`Secure` session cookie is lost on plain loopback origins, including exact
`localhost`:

```bash
python3 web/src-tauri/scripts/run-loopback-origin-probe.py --mode aliases --phase login
```

`run-local-https-origin-probe.py` repeats that drive over local HTTPS with a
certificate the probe generates for itself, pinned in the WebView's own
server-trust challenge. Its `https-trust-probe` Cargo feature enables only the
standalone GUI example. `--cert-dir` reuses one certificate across runs so the
restart phase measures cookie persistence rather than a changed certificate:

```bash
python3 web/src-tauri/scripts/run-local-https-origin-probe.py --phase login --cert-dir /tmp/rcp-probe-certs
```

Run `--phase resume` afterwards against the same directory to check that the
session survives an application restart. Each run first asserts that the host
does not already trust the probe certificate, so a success cannot be confused
with pre-existing system trust.

Production startup loads or creates one versioned local-HTTPS identity in
`local-https-identity-v1.sealed` under the app configuration directory. The file
is authenticated encryption with mode `0600`; its 32-byte key is the Keychain
item at service `app.researchcontrolpanel.rcp.local-https`, account
`desktop-identity-sealing-key/source-v1`. Never print or export the Keychain
value or decrypted identity. The source-built app accesses that short key only
through `/usr/bin/security`, whose ACL remains stable across ad-hoc rebuilds.
That ACL authorizes the Apple tool, not the calling RCP process: it prevents
rebuild churn and keeps secrets out of argv/page/log state, but it does not
protect them from another process deliberately invoking the tool as the same
macOS user. The current cooperative provider model accepts that limitation for
source builds and the unsigned prebuilt app alike; app-bound credential access
is later work.
Permanent team member tokens use the same bounded helper under service
`app.researchcontrolpanel.rcp.team-member-token.source-v1`, with one
`team-connection/<uuid>` account per saved connection.
Saved team connections use connection-bound `rcp-<uuid>.rcp.localhost` origins;
only their exact validated origins may enter the main window, and only the
stored certificate fingerprint is passed to the native trust hook.
The encrypted version-4 identity records a 365-day certificate lifetime and
rotates atomically during the final seven days. Its leaf explicitly carries
`CA:FALSE`, TLS server-auth usage, and the key usages required by WKWebView.
Startup reissues valid earlier identity records and migrates the exact previously
shipped `rcp-<uuid>.localhost` registry origin; malformed or partial identity
state still fails closed. Both macOS bundle plists grant the manual-trust ATS
exception only to `rcp.localhost` and its direct connection subdomains. That
exception does not authorize HTTP: the native navigation owner still admits
only exact saved HTTPS origins and the trust handler still requires the pinned
certificate to pass hostname, validity, and server-use evaluation.

The ignored D3 live test uses the same production tunnel owner with an existing
system SSH login, forwards only the remote host's loopback SSH banner, then
stops and reaps the local child. It does not start or stop a remote service:

```bash
RCP_LIVE_SSH_TARGET=<ssh-alias-or-user@host> \
  cargo test --manifest-path web/src-tauri/Cargo.toml \
  team_tunnel::tests::live_system_ssh_child_forwards_through_owned_tls_proxy \
  -- --ignored --nocapture
```

## Build and test a release candidate

Before packaging, verify that the intended revision is checked out, the version is
intentional, no unrelated changes will enter the artifact, and the baseline and desktop
checks pass. Building requires Python and `uv`, Node.js and npm, and Rust.

Build the application:

```bash
npm --prefix web run desktop:build
```

This command compiles the frontend, freezes the Python backend with PyInstaller, prepares
the target-specific sidecar, and assembles:

```text
web/src-tauri/target/release/bundle/macos/RCP.app
```

Smoke-test the backend inside that exact bundle:

```bash
uv run python packaging/smoke-backend.py \
  web/src-tauri/target/release/bundle/macos/RCP.app/Contents/MacOS/rcp-backend
```

Then open that bundle through Finder and exercise the desktop workflows affected by
the candidate. Confirm that the project index opens, a project can be read, provider
readiness is truthful, desktop-only interactions work, and the app owns or reuses the
expected backend. Source behavior is not evidence for the packaged artifact.

When final desktop verification is complete and no more native work is planned, remove
disposable Rust build output:

```bash
cargo clean --manifest-path web/src-tauri/Cargo.toml
```

## Publish the desktop companion release

Each promotion ends by calling `.github/workflows/publish-desktop.yml`, which
can also be run by hand for the same tag. It builds the exact commit of the
published `vX.Y.Z` release on an Apple Silicon runner, checks that the native
versions equal the tag (`packaging/release_build.py check-desktop-version`),
smoke-tests the bundled backend, and uploads `RCP-vX.Y.Z-macos-arm64.zip` and
its `.sha256` to a draft `desktop-vX.Y.Z` release. It downloads both back,
verifies them, and only then publishes the draft as a pre-release that is not
latest. The app cannot live in `vX.Y.Z` itself: installed supervisors accept a
server release only with exactly its five files. A failed run leaves the server
release unchanged and can be rerun; a published companion is never replaced.

The native versions in `web/package.json`, `web/package-lock.json`, and
`web/src-tauri/Cargo.toml`/`Cargo.lock` must equal `src/rcp/__init__.py`; a test
enforces it, so a version bump changes all of them.

Apple signing is not planned. It needs a paid Apple Developer account, and a
locally built app is never gatekept, so it would only spare prebuilt-app users
the one-time Open Anyway approval. The release build is ad-hoc signed, without
the hardened runtime: an unsealed bundle makes macOS call the downloaded app
damaged instead of offering Open Anyway, and the hardened runtime stops the
backend from loading its unpacked Python library. Without a signing identity the Keychain
cannot bind credentials to the app, so the prebuilt app keeps the source build's
Keychain storage. The Tauri updater stays disabled: nothing sets
`RCP_UPDATE_ENDPOINT` or `RCP_UPDATE_PUBKEY`, so every build reports
`enabled: false` and the app says nothing about it. Update notices come from the
release check instead.
