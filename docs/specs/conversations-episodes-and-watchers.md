# Conversations, episodes, and watchers

This specification owns ordinary conversations, bounded Experiment control,
common episode lifecycle, watcher observation/delivery, and visual wrap-up.
Auto-research-specific orchestration and graph branches are in
[Auto-research and branch merge](auto-research-and-branch-merge.md).

## Discuss and Work turns

Discuss and Work are explicit per-turn modes in one conversation. Submit time
captures the mode; Pause, Resume, Retry, and correction preserve it. Changing the
composer's mode or configuration affects only the next ordinary turn; while the
running attempt can take input, the composer's message uses that attempt's
runtime behavior instead, as described under conversation scratch and human
input below.

- **Discuss** reasons and answers with no repository mutation or active Patch.
- **Work** authorizes operational execution within its exact project write
  scope and one optional semantic `patch.json`.

Work pursues the requested outcome through the investigation, execution,
verification, and repair it needs. The agent inspects results and iterates while
useful authorized work remains, rather than stopping at the first attempt or
returning feasible next steps for the human to perform. It finishes when the
outcome is achieved, hands off ongoing work through the watcher contract, or
explains the concrete unavailable prerequisite or new authority needed for
further useful progress. This does not widen the requested objective or grant
another invocation.

A Work turn may finish without a Patch; no net graph change spends no revision.
The answer and graph outcome remain independently visible. A stray Patch left by
Discuss is retained as a receipt and discarded; a file cannot grant its author a
different mode.

## Native chat context

Chat is not transcript ingestion. Canonical chat history exists for display,
but RCP never reads, indexes, copies, projects, validates, or authorizes from
prior RCP transcript text. Provider-native session continuation may retain the
provider's context without making the displayed transcript an RCP input.

In a personal local project, a human may explicitly import one Codex native
session by its UUID from the configured local Codex log roots. The source's
native session id and working directory must match exactly one repository in
that project. RCP stores a bounded snapshot of user and assistant text in its
SQLite app data, including Codex's commentary/final labels, and shows it as
read-only provider history in the Agents list and Project Settings. Reimporting
the same source is idempotent and refreshes the snapshot when new records
appear. There is no automatic tailing, bidirectional Herdr message sync,
native session takeover, or conversion into canonical RCP chat, task, answer,
or graph authority. A
separate RCP turn never consumes this displayed history as task context.

The first ordinary turn in an RCP-owned native session receives one master
context. It supplies shared project context once: the current graph target and
head, focused node, exact run-scope repository pointers, enabled-package
pointers, and selected non-secret compute connection metadata. Separate Discuss
and Work contracts define their authority, schemas, and outputs against that
shared context. Seeing both grants no cumulative authority: each turn carries
one explicit mode marker. A refreshed master replaces earlier master
instructions while retaining the conversation's native progress.

Later ordinary resumes repeat only the master-context path, then send the marker,
logical turn id, human message unchanged, resolved artifact directory, and a
compact replacement delta only when stable context changed. The repeated path is
a pointer, not an instruction to reread unchanged context. A new baseline commits
only after a mechanically successful turn and is bound to provider, host, native
session, project, graph target, conversation, and focused node. Failed or
interrupted work does not advance it.

Compute selection is stable conversation context, persisted independently on
the task request and canonical chat record for truthful recovery. Ordinary turns
send a concise added/removed/updated delta: additions and updates carry the
selected profile's non-secret access metadata so a resumed agent can use it,
while removals need only the display name. The resource metadata cannot change
the provider, execution machine, `run_on`, graph target, or write scope.

An exact conversation/native session cannot be reused across a different chat
or graph target. Main and branch-bound stages fail closed instead of silently
continuing with the other target's authority.

Opening an Auto-research branch exposes the ordinary node and project composers
for that graph target, during and after the episode. These chats have independent
human authorization and sessions; they do not route through the orchestrator or
spend its budget. Canonical chat records carry their graph target. Older records
resolve it from their durable task/session binding before appearing in a target's
chat list. A branch id never upgrades Discuss or expands repository write scope.
Every recovery and watcher continuation preserves that original target.

A human may also start an ordinary Experiment loop on the branch. It owns a new
Experiment episode and budget, without an Auto-research child route. Its Run,
Stop, control projection, recovery, and watchers all use the exact branch target.

## Conversation worktrees

Before a conversation has a Work turn, its composer may select **Work in a
worktree**. The first ticked Work turn binds exactly one run-scope repository on
the execution machine. RCP persists an immutable binding before creation:
project/chat/focus, repository alias, machine and execution host, canonical shared
and worktree paths, Git common metadata directory, real worktree and starting
branch names, and starting commit.
The new branch starts at the shared checkout's captured commit; uncommitted
shared edits are excluded. Detached starting HEAD is refused. A deterministic
sibling path and branch derive from the chat id. No worktree belongs to an
episode or worker, and a path alone never establishes a binding.

Every later Discuss or Work turn uses the bound repository pointer. Discuss
still has no repository write authority. Native continuation, Pause, Resume,
Retry, and server restart retain this binding; missing or moved worktrees fail
before launch without falling back to the shared checkout. A partially created
binding can prove and finish its exact Git registration; an unregistered orphan
branch requires explicit human repair. Worktree selection cannot change after
any Work turn.

**Integrate** starts an ordinary Work turn with an RCP-authored instruction and
the execution account's own Git/GitHub credentials. The backend offers **Open a
pull request**, **Merge into <starting branch>**, and **Merge into <default
branch>**, hiding the duplicate branch. Default-branch identity comes from
`origin/HEAD`; an unavailable default is explicit, never guessed as `main`.
All integrations refuse dirty worktrees and show the tracked/untracked changes.
Local merges also preflight a clean shared checkout and an existing local target
branch. Pull requests keep worktree-only repository scope and do not require a
clean destination. A local filesystem origin is pushed without invoking GitHub.
The provider rechecks the preflight facts immediately before acting. If the
target is checked out in the shared checkout, merge there; otherwise the provider
may switch to the target inside the worktree and must restore the worktree
branch afterwards, including after aborting its own failed merge. A saved
integration Resume/Retry may find only that operation's exact admitted target
checked out in the worktree; it reruns the same clean-checkout and target-existence
preflight before admission and provider launch. Ordinary turns still require the
bound branch. RCP never merges, commits dirty files, resets, stashes, or force-pushes. Task completion is
not an integration receipt.

**Remove worktree** is explicit, refuses an active/paused turn or dirty worktree,
and serializes with fresh, Resume, Retry, and graph-repair task admission for that
chat. It shows commits ahead of the current starting branch and an explicit `origin`
branch lookup (unknown with a reason if unavailable),
and removes only the checkout. The branch and unmerged commits remain. Binding
removal has a durable intent and terminal tombstone; later turns in that chat
fail clearly and require a new chat. Failed turns retain the worktree. Project
record removal likewise never deletes repository worktrees.

## Conversation scratch and human input

One conversation owns one reusable scratch stage because provider-native resume
depends on its original working directory. Each logical turn owns one exact
`turns/<turn-id>/artifacts` directory. Stale `patch.json` and `watch.json` are
cleared fail-closed before a new turn that could misattribute them. A committed
native chat-session context retains that stage, including its immutable master
context, even while no turn is active.

While an ordinary human-triggered Discuss or Work turn runs, the human may send
plain text to it through the ordinary composer: while the watched attempt can
receive input, Send addresses that attempt: Codex app-server injects into its
running turn, and Claude delivers the message to the running attempt and
decides itself whether it joins that turn or runs as the next one in the same
session.
There is no separate steering control. The backend supplies whether the
exact attempt can receive input, its action label, and its disabled reason, using
the actual runtime, including a fallback to exec. The composer renders the action
label as a hint and send-button label, or the unavailable reason while running.
The mode toggle is disabled exactly while the composer addresses the running
attempt, because a follow-up uses that attempt's captured mode. A turn that
cannot receive input leaves the toggle available for the next ordinary turn.
Episode workers cannot be steered; the human continues to message their orchestrator
through the episode's ordinary mail path.
Herdr native turns accept the initial RCP prompt in the visible Claude pane,
but do not offer an RCP composer steer during an active attempt. The human may
inspect the pane; extra direct terminal input is outside the captured RCP turn
and cannot supply its structured answer or graph patch. The native turn's
captured capability and stage still govern its task result.

Each steer is stored as the human's chat message with its addressed task attempt
and a **delivered**, **refused**, or **unknown** receipt. A delivered receipt is
labelled **Delivered** for every runtime; Claude's carries a reason saying the
provider decides whether it joins the running turn or runs next. A refused
receipt retains the reason. Reload reads that stored record; it does not infer delivery from
answer text or replay the input. Provider acknowledgment means delivery, not a
promise that the model followed the instruction. The message remains human input,
never an assistant answer, provider trace, or graph-change channel. It cannot
upgrade Discuss to Work or change the active turn's scope, target, budget, or
permission. Refused and unknown input is not silently sent as a subsequent turn.
The [provider lifecycle](providers-and-containment.md#live-human-steering) owns
acknowledgment, completion races, and disconnect handling.

The desktop composer may turn one bounded macOS dictation segment into editable
text. It never sends automatically or retains audio. Temporary input attachments
are claimed atomically for one nonblank Discuss or Work message, bounded by the
current file allow-list and size/count limits, staged immutably on the execution
host, and reused exactly by task recovery. A partial or unprovable transfer
fails the task rather than dropping files and running text-only.

Attachment bytes, hashes, and paths never become canonical chat or graph data.
Chat history retains only display metadata and expiry. Files are untrusted
temporary context and cannot be the sole durable provenance for Evidence.

An assistant answer also supports temporary selection comments for the next
human turn. Pointer-selecting answer text opens a comment composer beside the
selection when the pointer lifts, wherever it lifts; a sweep that overshoots the
answer is clamped to the answer's text. A visible Comment command opens the same
floating flow with the answer in a real keyboard-selectable text control. At
every layout width, the composer stays inside the soft-keyboard-adjusted visual
viewport and scrolls when necessary.
Each submitted comment becomes one editable or removable composer annotation,
and the main composer shows their count. Several annotations may be staged. They
remain a per-chat draft, including after a comment is edited blank, and block
send until completed or removed. On send, each contributes only its copied
selected text followed by `comment: <comment>` to the ordinary human message.
There are no message references, source identifiers, offsets, durable
annotation records, or graph authority. Staging clears when the turn is accepted
and otherwise remains a client-side draft for that chat.

## Common episode parent

Auto-research and Experiment-loop are modes of one persisted episode parent.
The parent owns identity, human authorizer, graph target, lifecycle, durable
ending, native-session binding, operational ceiling, Stop state, report state,
and restart reconciliation. Mode adapters own their distinct admission,
authority, watcher/child settlement, and compact wrap-up facts.

The parent's recorded human authorizer is the authority for every turn inside the
episode, so a different current human pressing Resume or Retry cannot stand in for
it. An episode with no recorded authorizer therefore has no recoverable turn, and
RCP refuses that recovery by naming the situation and the remaining action — a
fresh human Run, which starts a new episode and records its own authorizer.

Every episode has exactly one validated native-session binding at a time:
provider, session id, execution host, exact reusable stage, project, graph
target, and actor conversation. A human Run always starts a fresh episode and
fresh native session. A provider switch is a deliberate recovery that becomes
active only after a mechanically successful handoff; automatic work never
silently switches or starts fresh. The switch is offered only where the actor
can accept a new binding: a rebinding starts a clean native session, which an
Auto-research worker never gets and which a stopping episode refuses from
anyone, so neither shows one beside the exact Retry they do permit. An
orchestrator wake is offered the switch like any other orchestrator turn: the
wake names the delivery attached to the turn, and that delivery is staged from
the paid allocation, so a clean session still receives it. The switch rebinds
that one turn, so an Auto-research switch names the children it leaves behind:
they resolve their own binding from the project's node_chat profile, which only
Settings moves. Because the switch exists to change the binding, it holds its
submission until the selection actually differs from the one that failed, and
the execution machine is part of that selection wherever the recovery is free to
move it. A run that can retry unchanged keeps its own plain Retry and never
routes through the switch to get one.

Only operational provider turns spend the operational ceiling. Validation,
same-invocation Patch/watcher correction, exact Resume/Retry, and hidden report
generation do not consume another operational unit.

### Episode archive

A project member may archive any episode and unarchive it later, including an
episode that is running, waiting, recovering, stopping, or generating its report.
The archive is shared by every member of the project in personal and team
spaces. It records the acting human and time independently of the episode's
original authorizer. It changes presentation only: lifecycle, budgets, reports,
tasks, watchers, retained stages, and canonical graph history remain intact.
Archive does not stop or settle work. Running tasks, admitted children, watchers,
and reports continue, and lifecycle changes do not undo the archive choice.

Archive applies to the selected episode. A child Experiment has its own archive
control; archiving its parent does not archive the child. Starting another
episode creates an unarchived run. Existing archives survive restart, backup,
and project transfer without conferring authority on historical identities.

`POST /api/projects/{project_id}/episodes/{episode_id}/archive` accepts exactly
`{"archived": true}` or `{"archived": false}` under ordinary human project
membership and write admission. It checks project and member access atomically
with the archive mutation and returns the episode. Episode projections export
`archived` and `can_archive`; the browser never infers eligibility from status.
Lists retain archived records for the explicit **Show archived** view.

## Experiment readiness and budget

An Experiment can start a new bounded episode only when:

1. each `governed_by` Decision is decided with a selected option;
2. none of those Decisions has a pending Proposal;
3. no `blocked_by` Blocker is open; and
4. no current episode still has a queued/running automatic invocation or a
   deliverable live watcher; and
5. no episode parent is still live at all. A turn can succeed below the ceiling
   while arming no observer and taking no exit, which leaves the parent live with
   nothing to wake it. The loop then reads as inactive, admission still refuses a
   second live parent, and **Stop loop** is the control that releases it; and
6. the Experiment itself is not `completed`, `abandoned`, or `superseded`.

Readiness reports its graph gates and its operational reasons as separate lists,
so no surface has to tell them apart by reading the sentences.

Graph prerequisites derive from the exact graph target's final graph. A closed
Experiment separately refuses a fresh episode: Runs says the Experiment is
complete and offers no episode-start action until a human or already-authorized
graph-writing task edits the node back to a nonterminal status. This fresh-start
gate does not revoke an invocation already authorized inside the current episode.
Before any episode the action says **Start episode**; after history exists it says
**Start new episode**. The node's current `invocation_ceiling` is the default
pinned operational ceiling; a human Run may authorize an explicit count instead,
which pins that episode without a graph revision and leaves the node's own limit
unchanged. Runs is where that count is chosen: on a terminal episode with no
live turn its control says **Add N turns** and creates a continuation episode
on the same node, graph target, and native session, chained by
`continues_episode_id`; **Start new episode** remains the fresh start. The node
inspector keeps the plain start against the node's own limit, which it shows
beside it. Historical episodes
retain their pinned used/ceiling values while the current node value remains
separately visible as **Next episode limit**.

Human Experiment-loop episode starts, including a completed-watcher start, are
not gated on compute readiness. The helper probes when invoked; Settings shows
the stored probe. Stop and pause do not cancel jobs. The
[compute jobs spec](compute-jobs.md) owns scheduler prerequisites, the generic
helper, and explicit human Cancel.

Starting an episode does not create an ExperimentAttempt. Attempts are semantic
agent-authored bookkeeping and never control budget, watcher identity, or
episode admission. A nonblank human initial goal is retained exactly; only blank
input receives the RCP fallback objective.

Only the newest unresolved operational task in the newest episode may perform
operational Resume or Retry. Patch-only repair may reflect retained completed
work but cannot rerun side effects or reopen an old episode.

## Experiment-loop graph authority

Each invocation receives a dedicated Experiment contract and compact control
file with phase, episode, graph target, invocation counts, pinned Decisions,
current drift, completion criteria, and delivered watcher identities. Watcher
state is a separate exact file. The provider never receives prior chat
transcripts. An automatic wake repeats one path to the full Experiment contract
that initialized its exact current native session; it does not tell the provider
to reread that unchanged contract. Current focused authority, causal guidance,
execution instructions, control inputs, schema, and output/validator paths
replace earlier instructions while the objective, attempt ledger, and completed
native-session progress remain intact.

The Experiment-loop Patch may update its own attempt/status and guidance, create
Evidence and Blockers, assert legal epistemic and output edges, and create the
permitted Proposal shapes within its pinned upstream/tested boundary. It may not
set standing, decide a Decision, apply a Hypothesis transition, change its pinned
Decision bundle, remove nodes, or treat Experiment status as automatic
invocation control. Fresh human episode admission owns the closed-status gate.

Validation and Apply both use the episode's exact project and graph target.
When a child belongs to an Auto-research episode, every graph context, Patch,
watcher, correction, settlement, and report input remains branch-targeted.

## Graceful Stop and recovery

**Stop loop** persists intent before returning and before an unclaimed compatible
watcher can win a new claim. It means: finish the already-authorized turn, retain
its valid Patch and semantic result, stop existing and newly emitted compatible
watchers, and admit no automatic continuation.

The current loop's Stop also retires unclaimed observations adopted from older
episodes on the same Experiment, graph target, and execution host. Their origin
remains intact, but a later episode cannot revive their delivery. Reconciliation
of a historical Stop never retires a replacement episode's observations.

If no unresolved task remains, Stop settles immediately. While the current turn
is queued, running, or pausing, Runs shows **Stopping gracefully** and recommends
waiting. If that turn pauses, fails, or is interrupted, the episode shows
**Needs action** and only the exact available Resume, Retry, or Switch-provider
recovery. Recovery cannot clear Stop or reenable watcher delivery.

Stop and pause do not cancel compute jobs. Stop does not cancel external work,
delete watcher history, edit Experiment status, create or close an attempt, or
discard a valid Patch. If the exact saved
session is unusable, Stop may durably abandon only recovery of that already
terminal task while preserving history, then settle.

Budget exhaustion starts no automatic wake. Pending completion remains visible
and unconsumed. Once the final operational turn settles, non-Stop endings enter
wrap-up; a later human **Add N turns** continues the same session with a new
ceiling and may claim retained compatible completion as its invocation one, and
**Start new episode** remains the fresh start.

## Watcher resources

Conversation, Experiment, and Auto-research child Work watcher targets are
separate exact resources, not a client-chosen mode field.

- A conversation `watch.json` wakes that same conversation.
- An Experiment watcher resource is keyed by project, exact graph target,
  Experiment node, and compatible episode, and wakes that bounded episode.
- A child Work watcher retains the parent episode and child route worker id and
  wakes that same route and native session, never the Auto-research root.

A branch watcher can never wake a main task, and a main watcher can never spend
a branch episode. Watcher selection, staging, atomic claim, task creation, and
episode association retain the same target.

An Experiment episode adopts unclaimed compatible observations from earlier
episodes of that Experiment on the same exact graph target and execution host.
Completions may coalesce across those origin episodes, including on a branch.
The receiving episode supplies the human authorization, native session, stage,
pinned Experiment policy (including workflow and skill packages), and invocation
budget; watcher origin is immutable provenance, including when another human
created or maintained the observation.
This adoption does not change ordinary conversation, Auto-research root, or
child Work routing. Existing group readiness and atomic, once-only claims still
apply. A child Experiment also retains its receiving parent's admission and
shared Experiment allowance gates.

Every watcher file has two all-or-none lists:

- `external` observations with required literal `check_command`, absolute
  `log_path`, and absolute `cwd`, plus optional nonblank `cancel_command`; and
- `graph` conditions from a closed vocabulary.

This is one external watcher form for direct scheduler submissions and
helper-launched processes. Experiment items may additionally carry their
existing `group` label; ordinary conversation items cannot. A helper's returned
watcher object uses these same fields; there is no job-id observer form.

The graph vocabulary is exactly: a named node reaching one of named statuses,
or a named Proposal being resolved after arming. There is no arbitrary query,
standing predicate, new-node arrival, or relation predicate.

## Graph-condition delivery

Graph conditions evaluate at accepted revision boundaries and at startup, using
the exact target's canonical transition order. A staged draft never fires them.
Halted/degraded replay means not yet for that target; other targets still
reconcile, and their callbacks cannot clear a pending transient retry elsewhere.
A node removed after arming retires its condition.

Each condition stores its arming head. A node status already true at that head
is immediately ready; Proposal resolution is prospective and requires the
specific later resolution event. A resolved Blocker transition is observed from
the retained final node/event, with no delete operation.

Every graph wake spends one permitted invocation, including one caused by a
human Sync. External and graph completions that become ready together coalesce
into one target-consistent wake. Canonical event watermarks make crash/restart
delivery idempotent.

## External observation

Shell checks run in a cold login shell with a hard timeout. A timeout kills
the check's process group on its execution machine, including shell children;
it never cancels the separate external job being observed. SSH checks carry
their own bounded timeout owner so a lost client cannot abandon the check.
Exit `0` means the named work is gone, `1` means still present, and any other result is
unobservable. Active observations use the normal interval; repeated failures
persist bounded exponential backoff and identity jitter. Only exit `1` resets
the error count. A degraded observation is never inferred complete or dead.

Shell completion reports operational liveness, not scientific success. The
Experiment watcher-state file and generic Work wake message, including child
Work, retain the shell watcher's log-path evidence and ordinary coalescing and
claim path. The [compute jobs spec](compute-jobs.md) owns direct scheduler
submission, generic helper launch, and human cancellation.

A human may also retire one live Experiment observer directly once its episode
carries a durable ending. While the episode can still take a graceful **Stop
loop** that control owns its watchers; after the ending fence Stop is refused, so
the observer would otherwise keep the loop shut with no control but Cancel.
Retiring is not cancelling: the observed job keeps running, and the retired
observer can no longer deliver a retained completion. It is offered for one lone
external observation on the graph target being shown: a grouped member cannot be
retired alone, because a human-stopped member makes its whole group
undeliverable; a completed observation is a retained result to claim rather than
an observer to retire; and an Experiment graph condition runs no job, so this
control is not its answer. A live condition can therefore still hold an ended
episode shut.

An optional saved `cancel_command` runs only on a human Cancel request, after a
fresh check confirms active work. It uses the recorded execution host and cwd,
and never changes the watcher into a separate cancelled lifecycle. A successful
command is an attributed request; observation still determines completion.
Stop fences continuation and leaves the action available for still-live work.
Cancellation failures permit explicit retry. Transfer and offline restore
remove executable actions; ordinary restart preserves them.

Prompt guidance lets short jobs finish inline and recommends a watcher for
roughly more than ten minutes of waiting. This is not a runtime cutoff.

Experiment watchers may form immutable groups of at least two new observations.
A group wakes once when no member remains active and every nonretired member is
either complete or persistently unobservable at the capped tier. The latter is
diagnostic readiness, not scientific success. Stop/disposition items may retire
any staged compatible watcher after the agent has settled its work, external
observer or graph condition alike, and always travel in the `external` list.
Retiring a condition discards only a future graph delivery, so the agent that
armed one withdraws it the same way it withdraws an observer; a watcher it has
stopped needing otherwise holds the loop open and spends an invocation when it
fires. A stop still never claims RCP cancelled the process.

Initial validation, grouping, retirement, replacement, and insert commit
atomically. One invalid item arms none. An Experiment observer repeating an
ungrouped one already armed for that node, graph target, execution host,
directory, check command, and log path is one such invalid item: identity jitter
keeps the pair out of a shared delivery pass, so each spends a wake on one
completion. An unnotified completion counts as already armed, being a wake the
episode has not spent yet, and grouping exempts neither side: one group wakes
once, but two are two delivery units that coalesce only when they become ready
in a single poll. Retiring one member does not strand its siblings, because a
group's readiness ignores agent-retired members. Generic Work and child Work
arming is unchanged. Observing one
job through genuinely different commands cannot be told apart mechanically, so
the staged watcher state is what every surface that arms an Experiment observer
reconciles against first. An empty final watcher declaration is
legal only with a success, Proposal, or Blocker Patch exit. Missing or malformed
handoff enters same-session correction without spending another unit and may not
repeat operational work.

At Work, child Work, and Experiment-loop settlement, RCP also refreshes every
job launched by the turn. A still-running job absent from the declared job
observers is a correctable handoff defect listing the unobserved job ids. The same correction
round repairs it without another invocation; jobs already exited need no
observer, and a turn that launched nothing is unaffected. Child Work uses the
ordinary Work reader, validator, and arming path for its final `watch.json`.

A child watcher claim creates one continuation and spends one parent B unit
atomically. It requires a running parent, a route without a Stop fence, and a
succeeded current child task. A repeated delivery cannot create a second wake;
exhausted B leaves the completion pending. A succeeded child with an armed,
undelivered watcher is waiting, which blocks the root's guarded finish. Episode
Stop and the root's child `stop` verb retire the child's watchers within their
admission fence. They never cancel the observed jobs.

## Watcher maintenance authority

An authorized node Work chat may maintain only its focused Experiment resource;
authorized project Work may maintain live Experiment resources in that project
and exact graph target. Discuss may inspect staged state but cannot mutate it.
Origin chat, provider, path, or maintenance machine grants no authority.

Maintenance uses its own Work task/session, spends no Experiment invocation,
does not create an attempt, and never replaces the episode's native-session
binding. Stop, watcher claim, and competing maintenance have one atomic winner.

## Visual wrap-up

Completion, operational exhaustion, unrecoverable failure, and a human-authority
pause fence new operational work and enter one hidden report wrap-up. Explicit
Stop is the only ending that declines it. An ending whose turn never bound a
provider session has no session to resume and so terminalizes directly, with no
wrap-up record and no report error; that is an absence of a report, not a failed
one, and it never leaves the episode on a live wrap-up status.

Report generation resumes the exact episode session and stage with only the
durable ending, the official report-skill/output pointer, and one compact
immutable mode receipt. It never rebuilds or resends the graph or transcript.
The mode receipt compacts in a fixed order until its stored envelope fits the
receipt size bound, measured with the storage encoder, so size never fails
admission. A wrap-up the reconciler cannot admit because of a permanent defect
(a validation error, an inconsistent ledger, a conflicting fence) is recorded
once as a failed wrap-up with the defect as its report error, and the episode
settles to its ending's terminal status; a transient failure (a lock, an
unreachable host) is retried on the next poll. Once a wrap-up row exists,
reconciliation reuses it and never rebuilds the receipt. One warning is logged
per process for each episode and failure kind.
The hidden allocation permits at most three provider turns total, clears the
exact output before each attempt, and spends no operational unit.

If shutdown interrupts or pauses an in-flight hidden allocation, startup
requeues that same operation rather than creating another allocation. The
transaction clears its prior write-scope fingerprint and records a reserved
dispatch-reset fence newer than the old worker's attempt receipts. Only that
durable fence makes the requeued operation launchable; public receipt writers
cannot forge it, and the previous attempt remains inspectable history.

A valid `episode-report.html` is captured as bounded immutable HTML and served
in the opaque artifact sandbox. The report has no Patch, watcher, command,
Proposal, or graph channel and never determines the episode verdict. Final
report failure is a durable visible nonblocking error with no manual report
Retry; the episode still terminalizes. It is shown beside the ending it belongs
to, never as the episode's health, its recommended next step, or a reason to
withhold a control.

## Runs projection

The backend Experiment-control projection derives one health, one Runs section,
one **Recommended next step**, and the exact available controls from structured
episode, task, Stop, budget, watcher, report, and owning-node state. Raw task and
report state remain supporting data and do not compete as peer episode states:
the ending fence alone decides that an episode is over and which episode controls
it retires. Once the episode is terminal, a closed owning Experiment makes the
Runs object Completed even when that episode ended by human Stop; the stopped
ending remains inspectable history. The browser renders the published answers
and never reconstructs them from a fresher task list. Controls appear only when
currently valid, and no recommendation and no diagnostic names an unavailable
action. Report availability is independent of current-episode selection: the
backend publishes the newest available report for the same Experiment and exact
graph target, so a later stopped episode cannot hide an earlier durable report.
The stopped episode remains current history; the report link retains its actual
owning episode id. The backend also publishes `report_is_current`; a report from
an earlier episode is labelled **Previous episode report**, while the selected
episode's own report is labelled **Open report**.

Active observations read **Waiting on watchers**. When only completed results
remain, Runs reads **Completion pending delivery**. After all observations finish,
a receiving Auto-research parent that cannot admit new work or has spent its
shared Experiment allowance produces **Needs action** with the current reason,
rather than recommending waiting for an already-completed observation. These
parent facts are read from the same SQLite snapshot as the Experiment runtime,
not persisted as stale delivery errors.

The runtime, parent episode, visible task rows, usage meter, and latest available
report used for one Experiment-control answer come from one SQLite read snapshot.
Resume, Retry, and provider switch target only the exact current operation named
in that answer; a missing task row yields no client control. Recovery admission
atomically rejects an older attempt or any episode with an already active task.
After an accepted recovery, the browser refreshes the authoritative project
projection before releasing the busy controls, including after a provider switch.
A refresh failure is reported separately from failure to start recovery.

The experiment detail retains exact target, episode history, pinned budgets,
current next-episode limit, current guidance validity, watcher provenance and
groups, session continuity, diagnostics, and report. Ordinary conversations and
Paper coaching remain outside Runs.
