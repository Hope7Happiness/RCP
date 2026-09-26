# Tell people when an update is out

Status on 2026-09-26: design confirmed by the human, revised after a Codex
xhigh design review and the GitHub review, and implemented on this pull request.

- Implemented and verified: changes 1–7. Python, web, and Rust suites pass,
  and a served personal space with a fake GitHub showed the source notice on
  the index, persisted its dismissal across a reload, and logged no errors.
- Remains, all live checks:
  - Run `publish-desktop.yml` for a throwaway tag, including a rerun after a
    failed upload, and confirm `/releases/latest` still returns `vX.Y.Z`.
  - Download that app on a Mac, approve it once, and drive the Download
    button, quit and reopen, and a team connection.
  - The team-space notice on a served team fixture one release behind.
  - Historical supervisors (`b65422dd`, `94f37f43`) fetching `stable` against
    a fake GitHub that holds a companion; only the current one is unit-tested.
- Settled (human, 2026-09-26):
  - Desktop and local Web installs follow promoted releases, not `main`. See
    [the decision record](../decisions/2026-09-26-desktop-installs-follow-releases.md).
  - No Apple signing and no paid Apple account.
  - Every promoted release also publishes an unsigned prebuilt macOS app. It
    becomes the normal desktop install. Building from source stays for
    developers. This ships in the same pull request.
  - Notify only. There is no one-click update. Each notice has a Copy command
    or Download button.
  - The notice is app-wide, not only in Settings.
  - The prebuilt app keeps today's Keychain storage. The spec now accepts the
    same same-user exposure for it as for source builds. App-bound credential
    access is later work.
- Closure: the pull request merges, the checks in
  [Verification](#verification) pass, the spec sentences are added, and this
  handoff is deleted.

## Why

Today nothing tells anyone that an update exists.

- Desktop: the UI already calls the Tauri updater (`refreshDesktopUpdate` →
  `check_for_update`), but no build configures its endpoint or key, so it
  always reports `enabled: false` and shows nothing.
- Team server: Settings → Server has an "Update is available" label that never
  turns on. `_inspect_source` in `server_ops/doctor.py` reports the installed
  release as its own upstream.
- So a security fix reaches team members only when an operator happens to run
  `rcp server update`.

Releases also carry no desktop app, so every desktop user needs Rust, the Xcode
tools, Node, and uv, and a build of several minutes. And team servers run
numbered releases while desktop apps run whatever commit the checkout is on.

## Design

### 1. One release check

- New module `src/rcp/release_check.py` owns one cache and one poller. The
  poller starts and stops in `create_app`'s lifespan, next to the existing
  background owners. No import-time worker, no second process.
- It reads GitHub's latest published stable release (`/releases/latest`) with
  the supervisor's stable rules: not a draft, not a pre-release, a `vX.Y.Z`
  tag. First check shortly after startup, then every 6 hours. Interval,
  deadline, and response-size bounds live in `limits.py`.
- HTTP routes read only the cache. They never call GitHub.
- Transport: a fixed repository, bounded response reads, redirects only to
  GitHub hosts. A `403` or `429` waits for the next cycle with no immediate
  retry. Unauthenticated calls share GitHub's 60-per-hour limit per IP, which
  matters for a lab behind one NAT; one install makes about 4 calls a day, 8
  with the companion lookup.
- Nothing from GitHub is rendered as HTML or used as a URL or command. The code
  validates the tag, then builds the command and download URL itself from that
  tag and the fixed repository.
- Privacy: requests carry the repository, the tag, and ordinary HTTP headers,
  and reveal the machine's IP and timing. They carry no project data, no
  credentials, and no install identifier.
- `RCP_UPDATE_CHECK=off` turns all network calls off.
- Companion lookup: `/releases/tags/desktop-vX.Y.Z`. It runs whenever a newer
  `vX.Y.Z` exists, whatever kind of install the backend is, because a prebuilt
  shell may reuse a backend of the other kind. Once confirmed it is not asked
  again for that release. It is ready only when it is published (not a draft), its tag matches, its
  target commit equals the `vX.Y.Z` commit, and both the app zip and its
  checksum are uploaded. A missing or incomplete companion is rechecked every
  cycle, even when `/latest` has not changed. Desktop availability is its own
  field, separate from whether an update exists.

### 2. Identities and comparison

- Versions compare as numeric `X.Y.Z` triples. A `+build.N.gSHA` suffix is
  ignored (`build_identity.py` already extracts the base). `0.4.10` is newer
  than `0.4.9`. A malformed version gives status `unknown` and no banner.
- Only a strictly newer release counts. A build ahead of the latest release,
  such as a development build from `main`, sees nothing. "Ahead" means by
  version number; Git ancestry is not checked.
- Team server: the installed tag comes from the selected release receipt,
  through the doctor's validated receipt reader, shared rather than running
  the whole doctor. A release pin in the server config gives status `pinned`
  and no banner.
- Desktop app: the notice uses the native shell's identity, not the backend's.
  A desktop may reuse a running backend of the same version but a different
  kind (`--reuse-existing`), so `sys.frozen` would mislabel it. The native
  shell reports its own version and a build kind compiled in by its build
  script: `prebuilt` from the release build, `source` from the development
  build, which also records its checkout path.
- Local Web app without the desktop: it is a source checkout only when the
  running package sits in a Git checkout. Otherwise the notice gives the
  version but no command.

### 3. One endpoint, and status kept separate

- `GET /api/update-notice` returns, from the cache: the latest release, the
  last check time, a status (`update_available`, `current`, `pinned`,
  `unchecked`, `failed`, `off`, or `unknown`), and, for a team space, the
  installed release. It always says whether the companion release is ready;
  only the native shell decides whether that matters.
- Any signed-in member may read it. It carries no secrets.
- Release-check status stays separate from installation integrity. The
  doctor's `source_state` keeps meaning "is the installed release consistent".
  A GitHub failure never makes a healthy server look broken.
- Settings → Server gains a release-check row from the same cache, and its
  "Update is available" label follows that row. Personal Settings gains an
  "Updates" row too, so a failed check is visible there.
- `rcp server doctor` makes one bounded live lookup and reports it as its own
  field.

### 4. The notice

- It reuses the existing update surface: `updateSurface` and
  `DesktopUpdateNotice` in `App.tsx`. That surface already appears on the
  project index, the setup screens, and every project view. It becomes one
  update notice with three kinds, fed by `/api/update-notice` and the native
  shell identity.
- Team server: "RCP v0.4.3 is out. This team server runs v0.4.2." Then "The
  server operator updates it with:", the command `sudo rcp server update`, and
  a Copy command button.
- Prebuilt app: "RCP v0.4.3 is out. This app is v0.4.2." A Download v0.4.3
  button appears only once the companion release is ready. It opens the
  release page through the existing external-link path, in the system browser.
  Until then the notice says the app build is not published yet.
- Source checkout: "RCP v0.4.3 is out. This app is built from v0.4.2." Then
  `scripts/update-from-source v0.4.3`, run in the checkout, and a Copy command
  button. A source-built desktop app copies it with `--desktop`.
- The client polls `/api/update-notice` while the window is visible: every
  30 seconds while the status is `unchecked`, then every 10 minutes, and once
  more whenever the window becomes visible again. The endpoint reads only the
  cache, so polling costs no GitHub calls. A first check that lands after the
  page opened, or a companion release that becomes ready later, updates an
  open notice without a reload. Both intervals live beside the client's other
  poll timings.
- Dismissal hides the notice for that release. A prebuilt notice dismissed
  before its download existed shows again once the Download button is ready. It is saved in `localStorage`
  and falls back to memory for the session when storage is unavailable. A
  newer release shows the notice again.
- Every team member sees the team notice. Team spaces have no operator role,
  and a member who is not the operator can pass the message on.
- Limitation: in the desktop app the page comes from whichever space is open.
  The desktop notice shows in the personal space, the team notice in a team
  space.

### 5. One update command for source checkouts

New script `scripts/update-from-source <tag> [--desktop]`. `--desktop` asks
for the desktop app; without it the script updates the local Web app only and
never mentions `/Applications`.

Every `rcp serve` started from a source checkout holds a shared OS lock on one
lock file in that checkout, whatever its data directory. This is new, and it
follows invariant 8: an OS lock, not a path's existence, proves a live owner.

1. Refuses while any RCP backend from this checkout is running: it takes that
   checkout lock exclusively, without waiting. A backend with reload on would
   otherwise pick up half-updated code, and two backends with different data
   directories would each be missed by a data-directory lock.
2. Checks that `git`, `uv`, and `npm` are present, and with `--desktop` that
   Rust and the Xcode tools are present too. A missing tool stops the script
   before anything changes.
3. Validates the tag's `vX.Y.Z` form, fetches that exact `refs/tags/<tag>`,
   and refuses a tree with uncommitted or untracked changes.
4. Records where the checkout started (branch or commit) and prints it.
5. Checks out the tag, detached. Local branches and detached commits stay
   reachable; nothing is reset or cleaned.
6. Runs `npm --prefix web ci`, builds `web/dist`, then runs `uv sync`. With `--desktop` it then runs
   `desktop:build-dev`, and a failed app build fails the script.
7. Prints how to restart: with `--desktop`, replace `/Applications/RCP.app`
   and reopen it; otherwise rerun `uv run rcp serve`.

It stops at the first failed step and names it. After a failure past step 5 it
returns to the recorded start by itself: it checks that revision out again,
runs `npm --prefix web ci`, rebuilds `web/dist`, and runs `uv sync` there, so old code never runs against
the new release's frontend or dependencies. It never replaced the app in
`/Applications`, so the running app is unchanged. If that restore fails too, it
prints each remaining command.

`docs/install.md` changes from "clone `main`" to "clone, then check out the
latest release", and gains an "Update a source checkout" section.

### 6. Version-mismatch messages

- `team_session.rs` tells a desktop that is too old to rebuild "from current
  origin/main". The new message depends on the native build kind, which the
  shell knows before any team space opens. A prebuilt app never sees the
  script. When the personal backend's cached notice confirms the companion
  release, it is pointed to that download. When the check succeeded but found
  no companion, it is told the app build is not published yet. When the check
  is `off`, `failed`, `unchecked`, or `unknown`, availability is unknown: it is
  pointed to the fixed releases page instead. Both URLs are built locally. A
  source build is pointed to the script.
- Compatibility is decided by protocol overlap. The message says to install a
  compatible release, not that the latest one always fixes it.
- `docs/desktop.md` states that Apple signing is not planned, and why.

### 7. A prebuilt unsigned app in every release

- The app cannot go into the `vX.Y.Z` release. Installed supervisors accept a
  release only with exactly its five server files (`_bundle_names` in
  `supervisor/.../releases.py`); the review confirmed this for historical
  supervisors too. One more file would break `rcp server update` on every
  existing team server.
- A new workflow, `publish-desktop.yml`, builds a companion release
  `desktop-vX.Y.Z`. `promote.yml` starts it after promotion, and it can be
  rerun on its own for the same tag. It never touches `vX.Y.Z`.
- It reads the exact commit of the published `vX.Y.Z` release and builds that
  commit on an Apple Silicon macOS runner.
- One version everywhere: the repository keeps `web/package.json`, the root
  version in `web/package-lock.json`, `Cargo.toml`, and its `Cargo.lock` entry
  equal to `src/rcp/__init__.py`. A test enforces it, and a version bump
  changes all of them. So a source app built from a release tag reports that
  release's version, and the native identity is correct without stamping.
  They move from `0.3.2` to the current version in this pull request. Tauri
  keeps reading `package.json`.
- Before building, the workflow checks that those versions equal the tag and
  stops if not. The Python version is stamped by `release_build.py` with the
  promoted build number and commit, not this workflow's run number.
- It runs `npm --prefix web run desktop:build`, then
  `packaging/smoke-backend.py` against that exact bundle, then zips it with
  `ditto` so macOS metadata survives, and writes a SHA-256 checksum.
- It uploads both files to a draft, downloads them again, and verifies them.
  Only then does it publish the draft as a pre-release that is not latest.
  GitHub's `/releases/latest` skips pre-releases, so supervisors and the
  release check still see only `vX.Y.Z`. A leftover draft from a failed run is
  deleted and rebuilt; an already published companion is never replaced.
  Pruning selects only `build/N` releases, so it never removes the companion.
- The README leads with the download and explains the one-time approval: the
  first launch is blocked, then System Settings → Privacy & Security → Open
  Anyway. A manually downloaded update may ask again.
- Credentials: the desktop keeps team member tokens and the local HTTPS key in
  the Keychain with access granted to `/usr/bin/security` (`keychain.rs`), so
  any process running as the same macOS user can read them. The prebuilt app
  keeps this unchanged. This pull request amends the spec, which had required
  app-bound access before wider distribution, to accept the same exposure for
  the unsigned prebuilt app.

## Out of scope

- One-click update for team servers. The server runs as `rcp`, and updating
  needs root. A button would need a new privileged channel and an operator
  role that team spaces do not have. It would be its own project.
- The Tauri updater. It might remove the repeated approval for manual updates,
  but whether it works without Apple signing is unverified. Revisit after the
  prebuilt app has shipped.
- Apple signing.
- App-bound credential access. Without signing, macOS ties Keychain access to
  each build's hash, so every app update would ask the user to allow access
  again.

## Verification

- Python: the checkout lock is held by every source `rcp serve` and released
  on exit. `release_check` against a fake GitHub server: newer, equal, older,
  `0.4.10` against `0.4.9`, a stamped equal version, malformed, pre-release,
  `403`/`429`, timeout, oversized body, and `off`. The companion lookup:
  missing, draft, wrong commit, one asset missing, then published on a later
  cycle, from a source backend as well as a frozen one. The poller starts and stops with the app. The endpoint's shape. The
  GitHub base URL is overridable only in tests.
- Team comparison: installed behind, current, pinned, and an invalid receipt,
  which leaves `source_state` alone.
- Supervisor acceptance: the current supervisor and historical supervisors
  (`b65422dd`, `94f37f43`) run `fetch stable` into disposable directories
  against a fake GitHub that also holds a companion pre-release. They accept
  `vX.Y.Z`, ignore the companion, and still reject a sixth asset in
  `vX.Y.Z`. The existing installed-upgrade CI journey keeps passing.
- Web: each notice kind and status; without a reload, an open page moves from
  `unchecked` to `update_available`, and a prebuilt notice gains its Download
  button when the companion becomes ready; refetch on visibility; dismissal per release, dismissal without `localStorage`, the
  copy button, and the notice on the index, setup, and project views.
- Served app: a team fixture one release behind with a fake GitHub server
  shows the notice everywhere, and Settings agrees. A personal space shows the
  source notice.
- Script: on a throwaway clone, from an older tag, a detached commit, a local
  branch, and a branch named like the tag. It ends on the new tag with a built
  `web/dist`, refuses a dirty tree, refuses while either of two backends with
  different data directories is running, and after an injected failure in
  `uv sync` ends back on the start revision with that revision's `web/dist`. With `--desktop` and no Rust it stops
  before changing anything.
- Native: rebuild Tauri; the build kind is reported; the `team_session`
  mismatch message for a prebuilt app with the companion ready, a prebuilt app
  whose successful check found none, a prebuilt app whose check is `off` or
  `failed`, and a source build.
- Versions: the test that the four native version fields equal
  `src/rcp/__init__.py`.
- Prebuilt app: run `publish-desktop.yml` for a throwaway tag, including a
  rerun after an injected upload failure. On a Mac, download the zip, approve
  it once, open it: the project index opens, the Download button opens the
  browser, quit and reopen reuse the backend, and a team connection works.
- Specs at closure: `docs/specs/server-and-machine-operations.md` and
  `docs/specs/api-web-and-desktop-projections.md`.
