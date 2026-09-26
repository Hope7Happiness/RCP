# Active implementation handoffs

Active:

- [Tell people when an update is out](handoff-2026-09-26-update-notices.md)
  — design confirmed and implemented 2026-09-26; live release, Mac download,
  and team-space checks remain. One cached release check in
  `rcp serve` drives an app-wide banner with a Copy command button: team
  spaces compare the installed release, local installs compare the checkout.
  Every release also ships an unsigned prebuilt macOS app in a companion
  `desktop-vX.Y.Z` pre-release; source checkouts follow release tags and
  update with one script. No Apple signing, no one-click update.

Earlier on 2026-09-26 every open handoff was closed: ten had shipped their code,
and the refusal-explains-itself handoff (a refused dispatch or Apply reported
where the human clicked, with no task row) was closed unbuilt because the human
chose not to pursue it. Git history holds their full text.

## Open live checks

These are manual drives the closed handoffs left unexecuted. Each needs real
hardware, a real provider login, or a disposable server, so no unit test
stands in for it. Run one on disposable data, then delete its line here.

- Worktree execution: two chats editing one repository; Discuss in the bound
  chat seeing the worktree's edits; native session continuation, Pause,
  Resume, Retry, and app restart finding the same worktree; the same over SSH;
  each Integrate option's refusal and success; a rejected integration and
  Remove without losing unmerged commits.
- Supervisor recovery: the `supervisor-recovery-live` workflow on disposable
  Ubuntu 22.04 and 24.04 guests, covering reboot recovery, repeated rollback,
  protected restore, and offline update.
- Compute jobs: a long-running job through real Codex and a disposable Slurm
  queue, with provider exit, RCP restart, watcher wake, native-session
  continuation, child budget, child Stop, and Cancel; plus the Experiment-loop
  and child-Work handoffs and wakes, missing-handoff correction, Cancel of a
  stopped watcher, degradation when work is unobservable, the served-browser
  drive, and the slow staged-command deadline.
- Live steering: same-session Claude follow-ups and Codex injection through the
  served UI with real local and SSH providers, including transport loss and
  restart with an unacknowledged message, Work containment, and on the
  execution host both a working sandbox and the missing-sandbox readiness
  diagnostic.
- Episode lifecycle: device-code sign-in, the Claude token journey, an
  "Add N turns" continuation, a branch merge that runs to completion, and wake
  suppression (mail that arrived mid-turn or a child login failure spends no
  wake) on a team server with a real login.
- Project terminals: a conflicted `git rebase -i` in the Terminals destination,
  including after navigating away and back.
- Operator stops: the deploy-key stop panel driven from the desktop app against
  a real saved operator route. Known gap: **Copy server command** copies the
  bare `operator_argv` with no statement of where it runs; giving it an
  execution context is a separate contract change.
- Pushes: the live team-space push run and real remote-machine SSH.
- Phone UI: the real-iPhone journey and its screenshot review.
- Runs loading: the team-server measurement of first open against the 2 s target.
