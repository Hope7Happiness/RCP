# Install and run RCP from source

Build order, local runs, the desktop app, and the checks that verify a
checkout. The [README](../README.md) is the short version.

## Install from source

Requirements:

- Git;
- Node.js and npm;
- [`uv`](https://docs.astral.sh/uv/); and
- Codex CLI or Claude Code, installed and authenticated separately if you want
  to run agent tasks.

Open the [latest release](https://github.com/Zhi0467/RCP/releases/latest) and
copy its `vX.Y.Z` tag. Clone, select that release, and build in this order
(replace `<tag>` with the copied tag):

```bash
git clone https://github.com/Zhi0467/RCP.git
cd RCP
git checkout --detach refs/tags/<tag>
npm --prefix web ci
npm --prefix web exec playwright -- install chromium
npm --prefix web run build
uv sync
```

The Playwright command installs the managed Chromium binary used by the web
interaction tests and is needed once after `npm ci`. The build order matters
because the Python build includes `web/dist`.

Every `uv run` command rebuilds this checkout's editable install, so the same
order applies to each new checkout, including a new Git worktree. Neither
`web/dist` nor `web/node_modules` is tracked, so run both steps there before the
first `uv run` in it:

```bash
npm --prefix web ci && npm --prefix web run build
```

The `web/dist present` hook in `.pre-commit-config.yaml` stops a commit with
that instruction if you forget, because otherwise the build failure appears as a
long traceback above the later passing hooks.

## Update a source checkout

Quit the desktop app with Cmd+Q and stop every backend using this checkout,
including backends with other data directories. Commit or move any local changes
and untracked files before updating. Copy the `vX.Y.Z` tag from the latest
release, then run from the checkout (replace `<tag>`):

```bash
scripts/update-from-source <tag>
```

For a source-built desktop app, include the desktop build:

```bash
scripts/update-from-source <tag> --desktop
```

The script refuses a running backend or missing build tools before changing the
checkout. It records the starting branch or commit, fetches the exact tag, checks
it out detached, installs Web dependencies, builds `web/dist`, and runs `uv sync`.
With `--desktop`, it also builds the development app and requires Rust and the
Xcode command-line tools. A failed step stops the update. After a failure past
the checkout, the script restores the recorded start by itself: it checks that
revision out again, reinstalls Web dependencies, rebuilds `web/dist`, and runs
`uv sync`. Only if that restore also fails does it print the remaining commands to
run by hand. The app in `/Applications` is never replaced, and no local branch is
reset.

For the Web app, restart with `uv run rcp serve`. For the desktop app, replace
`/Applications/RCP.app` with `web/src-tauri/target/debug/bundle/macos/RCP.app` and
reopen it, as described below.

## Run the local Web app

For development with backend reload and automatic Web rebuild:

```bash
uv run rcp serve --reload
```

Open <http://127.0.0.1:8421>. React and CSS changes rebuild the bundle; refresh
the page to see them.

For a normal non-reloading launch that opens the browser:

```bash
uv run rcp open
```

Register and open a checkout at launch:

```bash
uv run rcp open /absolute/path/to/project
```

Serve without opening a browser:

```bash
uv run rcp serve --host 127.0.0.1 --port 8421
```

On macOS, local app data defaults to:

```text
~/Library/Application Support/research-control-panel/
```

Set `RCP_DATA_DIR` before launch to use another data directory. Canonical
research history remains in each project's configured state repository.

## Run the source-built macOS desktop app

The desktop app additionally requires Rust and the Xcode command-line tools.

Run directly from the checkout:

```bash
npm --prefix web run desktop:dev
```

Build a Finder-launchable development app:

```bash
npm --prefix web run desktop:build-dev
```

The app is written to:

```text
web/src-tauri/target/debug/bundle/macos/RCP.app
```

Launch that exact bundle. If you keep a Dock/Finder copy at
`/Applications/RCP.app`, rebuilding does not update it: quit RCP with Cmd+Q,
then replace the installed copy before reopening it:

```bash
ditto web/src-tauri/target/debug/bundle/macos/RCP.app /Applications/RCP.app
open /Applications/RCP.app
```

Closing the red window hides RCP. Use **Quit RCP** or Cmd+Q to end the
desktop-owned backend. See [docs/desktop.md](desktop.md) for native build,
logging, and verification details.

## Team server

RCP can run a shared team space from source on a lab-owned Ubuntu server.
Installation, member invitations and joining, shared-project setup, provider
maintenance, updates, backup, restore, member removal, verification, and
recovery are all documented in the [team server guide](server.md); connecting
phones and other devices is in [docs/device-pairing.md](device-pairing.md).
Maintainers release through the build, tag, and promote process in
[docs/release.md](release.md).

## Verify a checkout

```bash
uv run pytest
uv run ruff check src tests packaging web/src-tauri/scripts
npm --prefix web exec playwright -- install chromium
npm --prefix web test
npm --prefix web run build
uv run pre-commit run --all-files
```

### Opt-in test gates

Some tests skip unless a tool is installed or an environment variable is set, so
a clean run still reports skips. CI installs `age` and runs the exact-base
upgrade; the rest need real credentials or a reachable host and are opt-in
locally.

| Gate | Unlocks |
| --- | --- |
| `age` and `age-keygen` on `PATH` | real age encryption of a backup archive, rather than the stub |
| `systemd-run` on `PATH` | the compute-job backend probe |
| `RCP_RUN_EXACT_BASE_UPGRADE=1` | upgrade from the exact previous commit's data, and release updates from every published non-prerelease `v*` release with current and stale caches, including the switched release's live check (needs authenticated `gh` and every release tag fetched) |
| `RCP_FROZEN_BACKEND=<path to the built backend binary>` | local unpushed commits through a frozen desktop backend |
| `RCP_RUN_GIT_CREDENTIALS_LIVE=1` plus `RCP_LIVE_GITHUB_ADMIN_TOKEN` and `RCP_LIVE_GITHUB_REPOSITORY` | live GitHub credential checks |
| `RCP_RUN_PROJECT_CHECKOUT_LIVE=1` plus `RCP_LIVE_PROJECT_CHECKOUT_SSH_HOST` and `RCP_LIVE_PROJECT_CHECKOUT_SSH_ACCOUNT` | project checkout over real SSH |
| `RCP_RUN_PROVIDER_READINESS_LIVE=1` | provider readiness against real logins |
| `RCP_LIVE_TRANSFER_GIT_HOST` | transfer against a real Git host |

Point the live gates at a throwaway account, repository, or host. Never at a
real project's data.
