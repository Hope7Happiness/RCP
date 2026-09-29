# Herdr session continuation and message sync

## Implemented

Local Discuss and Work turns for Codex and Claude can run as interactive agents
in RCP-created Herdr panes. RCP persists task, native session, answer, and
pane/process binding receipts, enforces its ordinary Work profile, and closes
the pane at the end of the attempt. Existing background runtimes remain
selectable. A Codex session from an existing pane can be imported into Agents
as a bounded read-only snapshot by native session id.

## Remaining work

- Define an inbound observation channel for messages typed directly into a
  Herdr agent. These messages may update a clearly labelled provider-history
  display, but cannot become RCP Work turns, answers, or graph changes without
  RCP's captured task authority and structured receipts. The current import
  refresh is explicit; it does not tail a live session.
- Let a human continue an imported native session from the RCP composer only
  after RCP proves there is no concurrent writer and reopens it in a controlled
  Herdr pane. The previous process may have been launched with permissions
  outside the project's RCP profile. Do not inject a task prompt into that
  process or run two agents against one native transcript. Preserve the
  imported source identity and original working-directory binding, and test
  the provider's resume behavior when RCP's task stage uses a different cwd.
- Decide how an RCP-owned chat displays externally entered messages with
  provenance. Direct Herdr messages must not silently consume a Discuss or
  Work mode or gain Patch authority. Verify Stop, restart, idempotent replay,
  and session/pane rebinding on disposable data.

The present trial service leaves the existing external pane untouched. New
RCP chat turns can already use Herdr; the imported history view cannot send
to or take over that pane.
