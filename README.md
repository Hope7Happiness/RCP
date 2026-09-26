# RCP

**A control panel for research done with coding agents.** RCP turns your Codex
and Claude Code sessions into one durable research graph of questions,
hypotheses, experiments, evidence, and decisions. Agents propose; you decide.
Run it alone on a Mac, or share one team space with your lab on a Linux server.

![The research graph, one node, and the Agents hub](docs/media/graph.gif)

## Who it's for today

- **Agents:** Codex and Claude Code. More to come.
- **Platforms:** macOS 13+ on Apple Silicon for the desktop app; Ubuntu 22.04
  or 24.04 LTS on x86-64 for the web app and team server.
- **Install:** the unsigned macOS app from the releases page, or from source
  with the steps below. RCP shows a notice when a newer release is out.

## Set up with your agent

Send this to your agent:

> Clone Zhi0467/RCP from GitHub. Build the web app and, on macOS, the desktop app
> from source, following the README and docs/desktop.md. Then walk me through
> using RCP.

For a Linux machine your team will share as an RCP server, make sure you have SSH
access, then send:

> Set up my RCP team server using `<ssh-host>` as the SSH host, following
> docs/server.md. Pause and ask about optional setup choices or when you need
> sudo access. Then show me how to use my team space in the desktop app,
> including inviting people, transferring projects, and creating shared projects.

## What it does

- **One graph, append-only history.** Questions, hypotheses, experiments,
  evidence, decisions, and blockers, replayable from a patch log and versioned
  in Git.
- **Agents propose, you decide.** Agents create nodes and file Proposals; only
  a human approves one, promotes a claim to project truth, or authorizes an
  autonomous episode.
- **Bounded autonomy.** One click starts an Experiment or an Auto-research
  episode from the graph, with a budget and a Stop. Watchers, recovery, and
  visual reports keep running without an open tab, and the phone UI shows them.
- **Artifacts with a reply path.** Inspect generated artifacts in the built-in
  viewer, annotate text or image regions, and send the annotation back to the
  agent that made it.
- **Your machines, your subscriptions.** Codex or Claude Code, locally or over
  SSH, with provider, runtime, and model settings per agent role. A team space
  on your own Linux server adds shared projects, member attribution, central
  Git checkouts, and backup/restore.

![Runs: control, timeline, and report](docs/media/runs.gif)

## Install and run

**macOS app.** From each release on, the
[releases page](https://github.com/Zhi0467/RCP/releases) has a
`desktop-vX.Y.Z` pre-release with `RCP-vX.Y.Z-macos-arm64.zip`. Unzip it and
move `RCP.app` to Applications. The app is not signed by Apple, so macOS blocks
the first launch: open System Settings → Privacy & Security and choose
**Open Anyway**. A manually downloaded update may ask again.

**From source.** You need Git, Node.js, [`uv`](https://docs.astral.sh/uv/), and Codex CLI or
Claude Code signed in. Build the web app and run it in your browser:

```bash
git clone https://github.com/Zhi0467/RCP.git
cd RCP
git checkout --detach <tag>   # the vX.Y.Z tag of the latest release
npm --prefix web ci && npm --prefix web run build
uv sync
uv run rcp open
```

For the macOS app, also install [Rust](https://rustup.rs) and the Xcode
command-line tools, then build and open it:

```bash
npm --prefix web run desktop:build-dev
open web/src-tauri/target/debug/bundle/macos/RCP.app
```

Development runs, verification, and updating a source checkout with
`scripts/update-from-source` are in [docs/install.md](docs/install.md).

A shared team space on your own Ubuntu server is set up through the
[team server guide](docs/server.md). Design and behavior live in
[docs/design.md](docs/design.md) and [docs/specs/](docs/specs/).
