# Herdr session continuation and message sync

## Implemented

Local Discuss and Work turns for Codex and Claude can run as interactive agents
in RCP-created Herdr panes. RCP persists task, native session, answer, and
pane/process binding receipts, enforces its ordinary Work profile, and closes
the pane at the end of the attempt. Existing background runtimes remain
selectable. A Codex session from an existing pane can be imported into Agents
as a bounded provider-history snapshot by native session id. Its appended
messages refresh while the detail is visible. After its old process exits, a
human can explicitly continue the same native session in Discuss or Work from
the Agents composer. A durable exclusive claim binds the original transcript,
repository, project, chat, first task, and execution machine. Ordinary task admission
cannot bypass that handoff. A disposable end-to-end run proved the same native
session could answer from prior context and later edit a file in Work.
The continued chat shows the exact imported handoff prefix above its RCP turns
in the same scroll area, with bounded pages and Load earlier messages.

## Remaining work

- Define a user-facing way to enter a new RCP-authorized task from Herdr itself.
  The current inbound observation refreshes provider history only; direct
  Herdr prompts have no RCP task, mode, answer, or graph authority.
- Decide how an RCP-owned chat presents externally entered messages after
  handoff alongside canonical task turns without conflating their authority.
  The pre-handoff context is inline; later direct Herdr activity still appears
  in the provider-history detail.
- Complete a disposable interruption/restart/Stop exercise of an imported
  continuation while its Herdr pane is active. Focused tests cover durable
  claim idempotency, live-pane refusal, exact process binding, and task
  admission; the served-app success check covered settled Discuss and Work.

The existing external pane remains untouched. If it still owns the session,
the continuation action names it and waits for the human to exit it before
RCP resumes that same session under its own permission profile.
