# Desktop installs follow releases

Date: 2026-09-26. Status: active.

## Decision

Desktop and local Web installs follow promoted releases (`vX.Y.Z` tags), the
same releases team servers install. Every release also publishes an unsigned
prebuilt macOS app, in a companion `desktop-vX.Y.Z` pre-release. That app is
the normal desktop install. A source checkout follows release tags too, and is
for developers. RCP does not pursue Apple signing. RCP tells people when an
update is out, but does not apply it.

## Why

- Team servers ran numbered releases while desktop apps were built from any
  commit on `main`. The desktop could be ahead of every team server, and a
  version mismatch showed up only as a failed team connection.
- Following `main` would make an update notice fire on every merge.
- Building from source asked every desktop user for Rust, the Xcode tools,
  Node, and uv. A prebuilt app removes all of that.
- Apple signing costs a yearly paid developer account. Without it, macOS blocks
  the first launch of a downloaded app until the user approves it once in
  System Settings. That one-time step is an acceptable cost for a free,
  open-source tool.
- The app lives in a companion release because installed supervisors accept a
  server release only when it holds exactly their five files. Adding the app to
  `vX.Y.Z` would break every existing server's update.
- One-click update was rejected for now. On a team server it needs a new
  channel from the unprivileged service to root, plus an operator role. For a
  source install it would run builds inside a checkout that may hold local
  work.

## Consequences

- The README leads with the app download. A source install, described in
  `docs/install.md`, checks out the latest release tag, not `main`.
- A development build from `main` that is ahead of the latest release sees no
  update notice.
- Each manual update of the unsigned app asks for approval again. The Tauri
  updater might avoid that, and is the first thing to revisit.
- The prebuilt app keeps the source build's Keychain storage, which any
  process running as the same user can read. The spec now accepts that for both
  kinds of build; app-bound access is later work, and easier once the app has
  a stable signing identity.
- If RCP ever pays for signing, the prebuilt app, the updater, and app-bound
  credentials change together.
