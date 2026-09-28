# Providers and containment

This specification owns provider capabilities, launch construction, exact
project write scopes, remote execution, Seed/Refresh ingestion, provider
readiness, skills, and durable launch receipts. Semantic graph authority is
separate and defined in [Authority and Proposals](authority-and-proposals.md).

## Fixed task capabilities

Run policy has explicit modules for Seed/Refresh, Discuss, Work,
Experiment-loop, Auto-research orchestration, graph merge, correction, and Paper
coaching. Shared launch, event, stage, and receipt plumbing never chooses policy
from a generic surface discriminator.

Capabilities are fixed in code:

- **Seed/Refresh** reads configured provider logs and project repositories and
  writes only its RCP scratch Patch.
- **Discuss** has writable conversation scratch, read-only project reasoning,
  public-web tools, and no active Patch contract.
- **Work** has noninteractive project operational tools, public-web tools, exact
  project repository write roots, and one optional semantic Patch.
- **Experiment-loop** uses Work-like operational access with its dedicated
  focused-Experiment graph and watcher contract.
- **Auto-research orchestrate** uses Work-like project repository access plus
  its dedicated staged command client and orchestrator graph profile.
- **graph merge** is graph-only; it writes its scratch candidate and receives no
  repository write roots.
- **generic graph correction** rewrites only retained scratch output; Work-like
  correction retains the same native session and the same exact Work write
  scope so it can repair reflection without repeating operational effects.
- **Paper coach** is read-only and has no graph, draft-write, or Apply channel.

The manifest and selected skills may choose execution details or add guidance;
they cannot widen or narrow these capabilities.

## Member terminals

`terminals/` owns member shell sessions separately from provider tasks. A session
runs as the local service account or remote execution account, in the same
registered checkout used by agents,
with the Work turn's trust boundary. Where supported, its mount namespace provides
accident resistance to a wrong-directory mistake, never isolation from the
service account or a security boundary against a deliberate member. Read access to a Git deploy key conveys
its write authority; exposing the key read-only does not keep it secret.

A small terminal backend registry owns an id, display name, and
`supports(os_name, is_remote)` predicate per backend, following the compute
backend pattern. Selection is per machine and independent of space kind:

- Linux with usable `systemd-run`, `systemctl`, `findmnt`, and a reachable
  user manager reports `mirrored`. Lingering is deliberately not required: the
  PTY lives inside the session that owns a session-scoped manager, which runs
  transient units and tears down with the link. A manager reporting `degraded`
  still answers and still launches.
- `--expand-environment=no` exists only from systemd 254. A probe reports the
  manager's version and a launch passes the option only where it exists; below
  it, the launch refuses any path or value containing `$` rather than running
  under an expansion it cannot disable. The shipped preflight also sets a value
  and reads it back, so a manager that rewrote the command line is caught
  whatever version it reports. A transient unit is built over D-Bus rather than
  parsed from a unit file and receives no `%` specifier expansion, so registered
  paths are passed through exactly as they are; doubling a literal percent
  instead makes the working directory unreachable.
- Every machine requires an executable `/bin/bash` before it is offered at all.
  The cooperative helper writes its readiness marker before replacing itself
  with the shell, so an unrunnable shell would otherwise admit a session that
  is already gone.
- Other operating systems, including macOS, report `cooperative` and use a
  plain PTY in the registered repository. Canonical-state protection is
  unavailable on that machine: there is no canonical-state fence.
- A machine with a non-empty `host` uses its probed remote OS, never the OS of
  the RCP process. A source-shipped Python probe checks the execution account's
  tools and user manager, and reports the account it actually answered as. An
  SSH destination that carries no user takes its account from the client's SSH
  configuration, so a machine answering as an account other than its registered
  `os_account` is refused rather than offered: the shell would hold the wrong
  home, credentials and write authority, and the mount profile was computed for
  the registered account. A machine with no registered account has nothing to
  compare and is not refused on this ground. The probe's answer is cached for
  the manager's lifetime, so the launch verifies the account again inside the
  connection that runs the shell, and refuses there too. The shared SSH failure vocabulary distinguishes
  unreachable, authentication failed, host key failed, and reachable but
  incapable machines, with the actual diagnostic.

The `containment` field reuses compute's `mirrored` / `cooperative` vocabulary;
those labels do not make the terminal mount profile a security boundary.
Linux with missing tools or an unusable user manager is unavailable, with the
prerequisite diagnostic. Cooperative is selected by OS, never after a mirrored
launch or probe fails. Terminal capability does not reuse compute readiness.
A non-Linux remote selects cooperative only after its OS is known.

Remote launches allocate a PTY through SSH and ship the remote launcher module's
source. Local and remote launchers share `terminals/profile.py` for the scrubbed
shell and mirrored profile rather than maintaining a second set of mount properties.
Remote canonicalization uses `protected_repository_paths` with `remote_stage`,
so declared paths and remote symlink targets receive the same refusal checks.
An explicit shell completion marker distinguishes a shell exiting 255 from an
SSH connection failure; exit 255 without completion reports the lost link and
ends the session. RCP never reconnects into a replacement shell.

Ending a mirrored remote session confirms that its unit stopped, through one
explicit remote stop over a fresh connection. A stop that cannot be confirmed
leaves the session record unfinished, so the next startup reconciles that unit
instead of skipping it. A session whose SSH has already exited is confirmed the
same way: the supervisor writes its completion marker before the cleanup that
can still fail, and reports that failure only through an exit status a dropped
link produces too, so neither says whether the unit went with the shell. Server
shutdown skips the round trip and leaves the same unfinished record rather than
waiting on the network.

The mirrored Linux launch uses its existing `systemd-run --user --pty` profile
with `ProtectHome=tmpfs`, `BindPaths` for the selected repository, and
`BindReadOnlyPaths` plus `ReadOnlyPaths` for existing Git configuration and
credentials. `ProtectSystem=strict` and a private temporary directory provide
accident resistance to writes in the wrong place, not isolation from the
service account. Before the interactive shell starts, the same launched profile
checks that the checkout is writable and that every protected path exists,
rejects writes, and reports a read-only effective mount through `findmnt`.
The PTY owner requires this check's readiness marker; an active unit alone does
not admit a session. Unsupported mount properties or failed verification refuse
launch with the real diagnostic. There is no cooperative retry or downgrade.

For mirrored sessions, canonical-state writes are refused through
`agents/write_scope.py`'s shared `protected_repository_paths` construction,
including declared and canonicalized `.research` paths for registered
repositories on the execution machine. These paths receive read-only mounts
even beneath the writable checkout. Absent protected directories receive read-only empty mounts so absence
cannot turn a deny into write access. An overlapping or canonical-state
repository root is refused. These filesystem-view restrictions provide accident
resistance against corruption; the retained service identity does not prevent
deliberate action by a member.

Both backends preserve the repository working directory, `env -i` environment
scrubbing, and shells without startup scripts or history persistence. Cooperative
sessions apply no mount properties or mount preflight and explicitly report the
missing canonical-state protection in the session payload and terminal view.

A live Work turn in the same checkout is projected as a warning with its task
identity and does not block opening a terminal. Git's index locking remains the
ordinary collision mechanism. Terminals create no agent task, Patch, or research
receipt.

## Task-engine ownership

`BackgroundAgentTasks` is the common launch/runtime engine. Auto-research,
Experiment recovery, watcher admission, and report owners intentionally share
named calls with it. These are navigational module boundaries, not plugins.
Add no `kind`, `patch_kind`, or request-subtype branch to the engine unless the
change removes an existing exception or the rule belongs to universal task-row
construction. A feature touching three or more engine entry points requires
moving one complete policy decision to its concrete owner; do not manufacture
a registry, facade, callback bus, or event bus to hide the coupling.

An orchestrator-triggered chat is specialized child Work only when its durable
child-route row exists. Missing route identity intentionally follows ordinary
Work for compatibility; changing that to a failure requires a product decision.
The [backend structural decision](../decisions/2026-08-20-backend-structural-refactor-closure.md)
records the accepted coupling and rejected extractions.

## Provider runtime selection

Each project agent profile selects a provider-owned runtime. An omitted value is
backward compatible: Codex uses `exec` and Claude uses `stream-json`. Provider
readiness exports the allowed names and the one an omitted value resolves to;
project setup and Project Settings render those answers, and the backend
validates the saved provider/runtime pair. No surface derives that default from
the order of the exported names. A profile always carries a resolved runtime, so
no selection surface stages or shows an empty one. A task request cannot
override the profile's runtime. The selected profile runtime applies to every
capability launched through that profile, so one `node_chat` choice covers both
Discuss and Work while their distinct capability contracts remain fixed in code.

Codex additionally offers `app-server`. RCP starts one fresh stdio app-server
process for each provider turn and uses the same shared local/SSH launcher,
process control, invocation gate, exact permission profile, event normalization,
usage accounting, and cleanup as `exec`. Provider threads remain persisted by
Codex, so a local app-server-created conversation can appear in Codex Desktop.
That visibility is provider-owned inspection; RCP does not order, take over, or
coordinate Desktop tasks.

Claude additionally offers `herdr-native` for local Discuss and Work turns when
the RCP server itself runs inside a Herdr pane. RCP creates a right sibling of
that explicit pane without moving focus, clears interactive shell aliases and
functions that could add permission-bypass flags, then starts a real Claude
interactive agent through Herdr. Its prompt is sent once through Herdr's agent
API. A Herdr idle or done badge is only presentation state: RCP requires the
matching user prompt, final assistant message, and terminal turn record in the
provider's native session transcript before it records an answer. The pane is
closed at the end of the RCP attempt, including Stop, so later terminal input
cannot inherit that attempt's Work authority. RCP persists the pane, named
agent, native session, and provider process group as task receipts; startup
reconciles an unfinished binding before interrupting the task. Ambiguous
identity fails closed. Herdr execution never falls back to a background runtime
after a prompt may have been delivered.

The Herdr choice requires a local Herdr socket and an already trusted Claude
working directory. Claude's first-use workspace trust prompt blocks native
startup; RCP reports that failure and closes its pane. The user must trust that
directory in Claude before retrying. Remote execution, Scratch Patch, Paper,
and Orchestrate do not have a Herdr native contract and fail explicitly when
this runtime is selected. Codex's installed interactive CLI cannot disable
ambient user configuration and rules with the flags used by its `exec` runtime,
so Codex has no selectable Herdr runtime. Its existing `exec` and `app-server`
paths remain available. The Herdr integration does not treat terminal text as
Patch authority; the task stage's `patch.json` and ordinary Apply path retain
that role.

App-server usage counts the change in `tokenUsage.total` from the same thread's
pre-turn resume snapshot (zero for a fresh thread) to the active turn's final
snapshot. `last` covers only one model response, not a whole agent turn. Repeated
snapshots replace the current total; they are never summed. Other threads and
other active turn ids cannot contribute usage. A failed terminal turn retains
its last observed usage. New reports use `codex.app-server.turn.v2`; existing v1
records remain historical observations and are not guessed or rewritten.

Native Codex subagents are available in both runtimes. App-server clears ambient
custom-role files and instructions while retaining native delegation and the
parent's provider-enforced permissions. Child notifications cannot supply the
parent's answer or end its turn. Codex usage totals cover the parent agent only;
neither runtime's parent summary includes descendant usage. RCP does not crawl
Codex's private transcript/database formats to reconstruct that missing total.

Every provider contract carries one shared fact: provider-native subagents must
finish inside the turn. Wait for their results before replying. Only helper and
scheduler jobs outlive a turn. RCP-managed workers keep their own lifecycle.
RCP does not track descendants or hold a completed turn for them.

Every local and remote Claude launch sets
`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`. Claude subagents run in the foreground.
Parallel Agent calls still work.

Codex exec `error` events are retry traces. `turn.failed` or a non-zero exit
ends a failed turn. Without `turn.failed`, the last retry error supplies the
failure text on non-zero exit. The live decoder, host fence, and recorded replay
treat retry notices as traces. Recovery still fails a journal with no terminal
event without finalizing it, because the host snapshots deliverables only at a
terminal event; the stage keeps its patch text.

The preferred runtime is chosen anew from the current project profile for every
RCP task invocation, including a continuation of an existing native session. A
native session is not permanently bound to the runtime that created it. RCP
records the runtime actually used on the task and, for Paper, on the writing
session.

Codex app-server may fall back silently to Codex exec on the same local or SSH
machine only while failure is known to precede delivery of the new prompt. RCP
checkpoints the actual runtime before the write that can deliver that prompt.
Once `turn/start` may have been accepted, failure is retained as an interrupted
or failed attempt and RCP never retries the prompt through exec. This rule is the
same for fresh and resumed conversations. Silent means the human's turn is not
failed, not that the cause is lost: the passed-over runtime and its failure are
recorded as a task diagnostic, and the runtime that did run is named on the task
and on the Paper writing session, which is where a substitution becomes visible.

Containment differs by runtime because the transports differ. `exec` refuses the
whole user config file and its execpolicy `.rules` files with `--ignore-user-config`
and `--ignore-rules`. `app-server` accepts neither flag, so RCP names each
capability-bearing config key instead, and cannot disable `.rules` at all.

The recorded actual runtime also decides live human steering support. Codex
app-server accepts `turn/steer` against the recorded thread and active turn id;
`expectedTurnId` is the provider's precondition. Claude stream-json keeps stdin
open and launches with `--replay-user-messages`; each additional user message
with an RCP-generated UUID is delivered to the running attempt, and Claude
decides its placement by timing: a message that arrives while a tool call is
running joins that turn and is attributed to its result, otherwise it runs as
the next turn in the same session. RCP promises delivery, not placement. Each
runtime declares its steering behavior and composer action label. Codex exec has no inbound channel,
including when it was selected by the pre-prompt fallback. The backend publishes the disabled reason
for an unsupported runtime instead of offering a send that cannot be delivered.

## Cooperative project write containment

Work-like provider launches are guarded against accidental writes into another
project. The users, team members, prompts, and project inputs in this model are
cooperative. RCP does not claim hostile same-account process isolation,
cross-project read secrecy, a general OS sandbox, network confinement, or
resource supervision.

RCP resolves one strict `ProjectWriteScope` before every Work or orchestrate
launch. It binds:

- durable `project_id`;
- execution machine and host/account identity;
- capability;
- exact task stage and workspace;
- exact admitted run-scope repository aliases and canonical roots on that
  execution machine;
- protected RCP-owned write paths; and
- a stable fingerprint of the canonicalized contract.

Work and Auto-research root prompts render these same resolved roots and
protected paths. Repository pointers do not supply a separate write allowlist.

Only RCP derives the scope from the manifest, project catalog, repository
pointers, task/episode lineage, and run scope. A browser, prompt, request body,
provider, or staged file cannot add a root. Scope construction requires a
complete inventory of every registered project manifest. Remote projects supply
their canonical workspace mirror, validated against the registered project and
state location, including before they are opened. Inventory resolves relative
local checkout paths against the registered manifest's project root. Local
projects use their opened canonical manifest or their unopened registration
manifest. If a required file is unavailable or invalid, the
Work-like scope and launch fail closed. The existing project workspace lifecycle
owns remote refresh; inventory construction adds no catalog-wide connectivity
probe. Canonical manifest reads hold the workspace snapshot lock so an in-flight
publication or rollback cannot expose a provisional scope to a launch.

The workspace must be within the exact task stage. Repository roots must be
registered to the same project, alias, execution machine, and host, must exist
and be writable by the execution account, and are deduplicated without replacing
them with a common parent. Local and remote resolution use the paths on the
actual execution machine.

That host comes from the project catalog and manifest. It is never read from the
repository pointer handed to the agent: a pointer's host states how that agent
reaches the repository, so it is empty for a repository on the execution machine
and says nothing about where the machine is. What the scope requires of a
pointer is its machine and its path, and the path is compared after both are
canonicalized on the execution machine.

The scope rejects another project's repository, a parent containing several
projects, the application data directory, SQLite, canonical `.research`, the
execution account's home directory, and broad temporary directories. Provider
authentication/session/cache storage may use the provider's own runtime
exceptions; those exceptions are not general project roots.

## Provider enforcement

A durable conversation worktree binding replaces exactly one registered alias's
root with its validated worktree root on the same execution machine and host.
Catalog ownership and overlap checks validate the registered checkout and
the planned sibling before creation, and the replacement before launch. The
binding also pins Git's canonical common metadata directory: it is admitted as
an exact metadata write root so Git can update the branch and index without
admitting shared checkout files. The scope prompt renders this same root. The shared checkout is excluded from ordinary Work scope;
Discuss receives the same worktree pointer as read context only. A
human-selected local integration turn alone admits both exact roots. Its target
is backend-resolved and persisted, never taken from a client-supplied path.

### Codex

Work and orchestrate use Codex's native noninteractive project permission
profile: the exact workspace plus admitted repository roots, never the dangerous
bypass flag. Fresh launches set the exact working directory; native resume uses
the provider's supported configuration path while preserving the same scope.
Public web search remains enabled. Canonical `.research` nested in a writable
root is refused as a write and kept readable, because RCP stages its `graph.json`
and `research.md` as required run context; Codex treats a denied path as
unreadable rather than unwritable.

### Claude

Work and orchestrate use Claude's supported unattended `dontAsk` mode with an
RCP-authored strict settings allow-list for the exact workspace and admitted
repository roots. They never use `bypassPermissions`. RCP suppresses user
settings and unrelated MCP configuration for this enforced launch. Public
WebSearch and WebFetch remain available under the provider contract.

Claude's OS sandbox is off. Its Linux backend always unshares the network
namespace and remounts a minimal `/dev`, and no setting relaxes either, so a
sandboxed Work turn cannot reach a scheduler, a GPU device, its own command
broker, or any non-HTTP service on its execution host. Turning it off is a
deliberate capability choice: Work on this provider is meant to run real
compute, and a containment that forbids that is not usable containment.

Write roots are therefore enforced by Claude's file permission rules. `Edit(path)`
is the only rule kind Claude matches for file writes, and it covers every
file-editing tool; a `Write(path)` rule is accepted and then ignored, so RCP
emits only the `Edit` form. These rules bound every file-editing tool and do not
bound `Bash`. A Work turn's shell can therefore write outside its admitted roots
on its execution machine. That is an accepted accidental-write gap for this
provider, not a claim of containment; Codex's native permission profile still
bounds both. Nothing here widens graph authority, which stays with `patch.json`.

### Version failure

Provider profiles own the minimum supported CLI contract. If the installed
supported version cannot enforce exact unattended roots, the launch fails with
a provider-compatibility diagnostic. A selected Codex app-server version or
startup that fails before prompt delivery may use the explicit exec fallback;
exec must still enforce the same capability and exact roots. RCP never restores
broad bypass access or treats prompt wording as containment.

## Continuation binding

Every launch receipt records the project, execution host, capability, canonical
writable roots, scope fingerprint, provider enforcement mode, and whether the
launch was fresh or resumed.

Before Resume, Retry, watcher wake, Work graph/watcher correction, child
continuation, or report-independent Work continuation, RCP recomputes the
current scope and compares project id, host, exact stage, target, and root
fingerprint with the durable binding. A cross-project session/stage, relocated
repository, incompatible run-scope change, or missing root fails before provider
launch. Legitimate relocation or scope change starts a fresh task/session; it
does not widen an existing native session.

A launch that carries no provider session is that fresh task/session, and it
establishes the stage binding rather than inheriting it. What decides this is
the session the launch actually hands the provider, not the label admission gave
it: an ordinary follow-up is admitted as fresh while still supplying its chat's
session id, and that session is what would otherwise gain roots it did not start
with. A chat stage is named from its chat id and is never cleared, so comparing
every launch against the scope a previous episode left there made a
conversation's run scope permanent: the human could not drop a repository from
an Experiment that had ever run. A sessionless launch is still refused while
another turn is live on that stage with a different scope, and a continuation is
compared against the stage's current binding, not against bindings a later fresh
launch superseded. A refused comparison names the repositories on both sides and
says a new episode is how run scope changes.

Conversation-local merge integration and the following ordinary turn are the
one explicit root-transition exception: their related-turn fingerprints may be
the exactly recomputed worktree-only or worktree-plus-shared contracts for that
same durable binding. An already-bound operation's Resume/Retry still requires
its original fingerprint. This exception cannot admit a different repository,
host, stage, or moved root.

The same resolver covers ordinary Work, Auto-research root, child Work, child
Experiment, watcher wake, and correction paths. There is no permissive fallback
for a continuation's project, host, stage, graph target, or write scope. The
pre-prompt provider-runtime fallback above changes none of those bindings and
resumes the same native session id.

Recovery retains the original assignment and completed native-session progress.
The attempt's graph inputs, output schema and locations, validator, and command
metadata apply to this attempt. Graph rules are repeated, not replaced: they
replace earlier text only when their version digest differs from the one the
session already holds (see
[graph rules in task contracts](#graph-rules-in-task-contracts)). This refresh
does not widen the captured task authority or authorize repeating completed
external effects; historical diagnostics remain failure reports, not policy.
After a completed Work-like Patch correction, RCP revalidates the retained candidate
against current state even if its bytes did not change. A stale rejection does not
require cosmetic edits; current schema and authority validation still govern Apply.

## Graph rules in task contracts

Every contract that reads or writes the research graph includes one rendered
graph-rules block, and no contract restates field or relation meaning in its own
prose. The block renders from code: node field descriptions, base relation
descriptions and endpoints from `RELATION_SPEC`, which relations carry an
Evidence assessment, id prefixes, and value vocabularies. A read-only contract
(Discuss, chat) receives the definitions and the method for searching
`graph.json`. A graph-writing contract also receives the hand-written method
that spans several nodes: the Experiment input-versus-result causal check and a
short list of cross-cutting write habits. Ontology extension rules are added
where the project has extensions.

Authority is not part of the block. Each contract places its own authority
block beside it: the ordinary agent contract, the orchestrator profile, or the
Experiment-loop allowlist. A skill may teach method but does not restate the
block's definitions.

The block carries a version digest over its rendered text. Continuations,
wakes, corrections, and added turns repeat the block, so a long session keeps
it, and state that it replaces earlier graph rules only if the digest differs.
A chat's master-context key includes the digest, so changed rules reach an
existing chat on its next turn. A human-started graph repair renders the current
contract rather than relying on the one its session began with.

## One graph output channel

An agent writes `patch.json` only in its exact RCP-owned stage. That file is the
sole graph-change channel. Work repository edits carry operational authority,
not graph authority, and canonical `.research` stays outside agent write roots.
RCP never extracts a Patch from stdout, an answer, provider directive, artifact,
URL, or repository file.

The labelled final assistant message is the answer. Provider traces, reasoning,
tool output, and the Patch verdict remain separate. A rejected Patch does not
discard an already-produced answer.

Every patch-producing Seed, Refresh, or Work stage carries an RCP-staged Python
command client with a validator verb. It exchanges bounded request and response
files through the writable workspace while RCP polls locally or through the
existing SSH run stage,
prepares the candidate against live current state in process, and records each
check. Client exit codes distinguish valid, semantically invalid, and validator
unavailable, so a transport failure can never become a correction loop.
Validation stages operations in their written order against earlier valid
operations while retaining whole-patch node and edge lookup for legal forward
references; it never reorders operations. A validator self-check is not a
reservation: Apply re-prepares RCP-owned bookkeeping and reruns the same semantic
validator against current state while holding the canonical append lock, so graph
movement between response and Apply is not by itself a rejection.

Ordinary Work and Experiment-loop, including correction turns, stage the
turn-bound broker and pass its invocation gate to the provider launch. Broker
authority is explicit and does not require an episode id. The broker binds the
live provider process tree on the execution host and signs each request; a
prior turn's process cannot acquire the next turn's authority. Validate-only
credentials still refuse keyed commands. These Work owners serve the generic
`launch` helper only on the selected helper route, with task events and durable
diagnostic receipts. A Slurm route uses agent-authored scheduler submission
commands. Both hand off the shell watcher described in
[compute jobs](compute-jobs.md).
This gives no additional graph output channel or command authority to other
task surfaces.

## Durable task lifecycle

Agent work belongs to the backend, not a browser view. Before execution, RCP
persists the task, task attempt, authorizer, capability, target, exact stage,
provider identity, and write-scope binding. Immediately before prompt delivery
it persists the actual provider runtime. Provider events retain labelled
answers, native session ids, usage, diagnostics, Patch results, and launch
receipts. A provider that succeeds while silently dropping part of the launch
records one backend-authored note on its exit receipt, and the task projection
exports that note to every surface listing or opening the task: the run reads as
untroubled otherwise. The note is composed from what RCP requested. Provider
diagnostic output is never shown to a human as the explanation.

A provider's final result is both its answer and its accounting boundary, and a
labelled answer is withheld from the wire, so its usage is forwarded on its own
frame. A turn that succeeds is counted exactly like one that fails, and a queued
follow-up's second result is counted once more.

Remote launch waits for the provider process group, including when its session
wrapper forks. A successful SSH exit or partial assistant message cannot complete
a Codex turn: its protocol must report completion, and the remote process group
must be confirmed stopped before a correction or recovery can reuse the stage.
Each remote pass has a unique pidfile and a durable start/stop receipt. An
unresolved pass fences stage reuse across task failure and server restart; a
read-only check may release that fence only after confirming process absence.
A host that reports no pidfile inside a stage that still stands has confirmed
that absence: the wrapper writes its pidfile before it execs anything and RCP
never removes one, so nothing was started. That is the only inference allowed,
and it is what keeps a launch that died before reaching the host from fencing
its conversation for good. It is drawn only once the launch has ended: the
post-exit confirmation and the pre-flight fence read absence that way, while a
stop racing a launch still in flight does not, because a pidfile that has not
appeared yet may only be late. A vanished stage, a stage path that now leads
somewhere else, or a directory at that path RCP would not adopt as a stage
(not the account's own, or not private) is not absence, because whatever
removed or replaced the stage could have taken a running pass's pidfile with
it. Unreachable hosts,
and pidfiles that exist but cannot be read, keep recovery blocked and preserve
the stage and receipts for reconciliation.

Pause, Resume, Retry, and correction form explicit parent/child attempt chains.
They retain task mode, graph target, capability, stage, and external-effect
diagnostics. Provider, model, and reasoning are one niche a human may change on
a recovery, because what makes a recovery worth starting is often that the
current one cannot finish the turn. A rebound recovery starts a clean native
session, since the prior continuation belongs to the binding it left, so the
rebinding reaches exactly the actors that have a clean-session path: an
Auto-research worker continues only through the exact session its dispatch bound
it to, and its recovery is refused rather than admitted as a turn that cannot
launch. The execution machine moves only where nothing is anchored to it. An
episode's watchers, stage, and children live on the machine its turn runs on, so
a recovery inside an episode keeps that machine on every Retry path, while a
standalone turn owns nothing there and may move to any reachable one. A failed run retains its scratch and Patch text for bounded
same-session repair and normal retention; RCP does not delete evidence merely
because validation or transport failed. Age-based cleanup first excludes exact
stages owned by active tasks, committed native chat sessions, live episodes,
pending or running report wrap-ups, and unexpired temporary result views. One
storage projection supplies the same ownership and required-stage decisions to
cleanup and update checkpointing; terminal debris follows normal retention.

Seed and Refresh repair through a generic correction ladder: rescan the retained
stage for the Patch, then hand validation errors back to the same live session
for at most two scratch-only rounds. A reused stage still holds the previous
attempt's `patch.json`, so RCP fingerprints that file before each correction
launch and refuses an unchanged one, handing the unchanged-file diagnostic
forward rather than revalidating the same bytes. A graph-level rejection is never
retried. Work instead repairs through same-access `work_patch_correction`, which
retains the original native session and write scope and changes only the
instruction.

Unrelated tasks may run concurrently. Turns in the same conversation and native
stage do not overlap. Canonical append remains serialized by the graph target's
state workspace.

### Live human steering

A human may steer the ordinary Discuss or Work turn they are watching only
through RCP's live provider process for that exact task attempt. The route
rechecks the addressed attempt and its live runtime; it cannot select a newer
attempt, start a turn, wake a sleeping agent, or target an episode worker.
Agent mail and lifecycle notices do not use this channel.

Delivery has three receipts: **delivered** means the provider acknowledged the
input; **refused** names why delivery was rejected; **unknown** means the write
began or may have begun but no acknowledgment established its outcome. Codex
acknowledges through the matching `turn/steer` response and rejects a stale or
completed turn. Completion immediately fences new Codex input, but RCP drains
matching responses before marking outstanding receipts unknown at stream shutdown.
Claude becomes ready when `command_lifecycle state=started` names the initial
RCP command UUID. `state=queued` for a pending follow-up UUID acknowledges
acceptance immediately; replayed user echoes are consumed but never establish
readiness or delivery. Its durable `delivered` receipt is labelled **Delivered**
with a reason saying Claude decides where the message lands — inside the running
turn when a tool call is in progress, otherwise as the next turn — and that it
keeps the captured capability and write scope either way. Receipt wording is
chosen from the task's recorded runtime when receipts are written.

Both placements are handled by one rule. Lifecycle lines admit a command to the
outstanding set and `completed` removes it; a result then removes the commands
it attributes. Injected: the follow-up's `queued`, `started`, and `completed`
all arrive inside the first turn, the result attributes both UUIDs, and the set
is empty, so the invocation stops with the message consumed. Queued: the first
result attributes only the initial UUID, the follow-up stays outstanding, and the
process runs on to the second result. Attribution is what settles the stop;
lifecycle alone cannot, because `completed` for a command lands after that
command's own result in the queued case.

RCP tracks accepted, unfinished command UUIDs that it generated itself:
`queued` and `started` add them, `completed` removes them. Unknown command UUIDs
cannot keep the process open. Each Claude `result` removes its
`user_message_uuids` (or singular `user_message_uuid`) from that set. When an
accepted follow-up remains, RCP yields that result's answer and usage and lets
the same process run the next turn. Otherwise it completes and stops the
process, refusing any unacknowledged follow-ups. A result without usable command
UUIDs fails closed to the same stop behavior. `queued_turn_count` is not used.
Without a follow-up, the first result still ends the invocation, with one
exception: a successful result with `origin.kind` equal to `task-notification`
and no message id sent by RCP stays a trace. It does not end the turn. Both the
local decoder and the host fence apply this notice rule.

The provider turns share one native session, capability, write scope, and task
stage. Their answers are joined with a blank line into one assistant chat
message; each result retains its own usage accounting. Work reads `patch.json`
only once, after the invocation ends, and scratch is cleared only on entry to
the RCP turn. No second task, chat record for an assistant, or answer file is
created for a queued turn.

A transport drop or process exit after a write began leaves an unacknowledged
steer unknown, except for Claude's explicit result fence above. Waiting for a
receipt is bounded by `PROVIDER_STEER_ACK_TIMEOUT_SECONDS` in `limits.py`; timeout
stores unknown and cancels only the receipt waiter, not the running turn. Late
responses do not rewrite that stored outcome or trigger a resend. The durable
message reservation immediately precedes the external write; those two effects
cannot commit atomically. If RCP restarts before the acknowledgment is recorded,
the reservation remains unknown: delivery acknowledgment was not recorded, and
the write may have begun. A live refusal proved before writing remains refused.
RCP never automatically retries or resends a steer, and never queues a refused
steer as the next turn. SSH uses the same existing stdin pipe and receipt rules.

The message and receipt belong to the
[human chat record](conversations-episodes-and-watchers.md#conversation-scratch-and-human-input).
Steering changes no mode, scope, graph target, budget, or permission. It creates
no persistent provider daemon and wires no hard interrupt. Each provider process
still ends when its accepted commands finish; Pause, Resume, Retry, graceful Stop,
and restart recovery keep their existing attempt and durable-state contracts. A restart
does not recover or resend an in-flight steer through a replacement process.

## Local and SSH execution

The provider runs on the machine that owns the selected repository pointers.
Local and SSH launches use the same capability and write-scope contract. Remote
command construction carries remote canonical roots, never local substitutes or
a broad remote working directory.

The remote run stage owns exact path validation, process/event wrappers,
scratch transfer, and recovery. A task resumed remotely must prove the saved
host and stage. SSH or provider transport failure is reported as unavailable,
not converted into semantic correction.

RCP shares an SSH connection per unit of work, not per host. Work that owns
something durable keeps its own connection, named by what it owns: the work in
one run stage by that stage's root, a lock holder by the lock it holds. A link
that drops therefore ends the work on that connection and nothing else. Short
control traffic owns nothing durable and shares one connection, which is what
keeps it cheap. Stopping a remote process after a failure stays on the shared
connection on purpose: it must not ride the connection whose death it is
cleaning up after, and the shared one is the only path OpenSSH reopens by
itself. Connections left behind by finished work are cleared by asking whether
they still answer, never by whose they look like, because the local socket
directory is keyed by user account and a second RCP instance keeps its live
connections in the same place.

This separates work that would otherwise fail together for no reason of its
own. It does not make a host's connections independent of the network between
them: an outage still ends every connection to that host, now as separate
failures rather than one.

### Compute connections are resources, not execution profiles

A project may configure named local or SSH compute connections as non-secret
resource metadata. A compute connection is not a `MachineConfig`, never supplies
`run_on`, and never changes where a provider launches. Local compute means the
machine on which the current agent is already running; an SSH compute target is
reached from that same machine. Attaching or detaching one does not relaunch,
move, or replace the provider, and it does not expand repository or write scope.

The backend probes every configured connection from every machine currently
selected by an agent execution profile. Readiness is therefore keyed by
`(agent execution machine, compute connection)`, not stored as one global fact.
SSH probes use the ordinary OpenSSH credentials already configured for the
execution account, batch mode, a bounded connection timeout, and strict host-key
checking. Strict host-key probes use a direct OpenSSH transport with connection
sharing disabled, so an existing multiplexed master cannot bypass the check.
Results distinguish reachable, unreachable, authentication failure, and host-key
failure. An authentication or host-key action names the exact agent machine on
which the operator must repair ordinary SSH state. RCP has no key or password field
and never imports, stores, stages, or transmits those credentials.
Only explicit readiness refresh runs these SSH probes. Normal readiness polling
returns the last authoritative matrix without network work and without waiting
behind an explicit refresh of a slow target, and any connection or
execution-binding change invalidates that matrix. Provider readiness and compute
status invalidate independently: resolving one provider path leaves an in-flight
compute probe free to apply, and a compute change leaves recorded provider
readiness in place. Probe diagnostics cross one redacting, single-line boundary
before projection, and the backend exports the status label and tone consumed by
every UI surface. A changed connection never inherits the old target's status;
if the post-save refresh fails, Settings keeps the saved metadata, leaves status
empty, and reports that the refresh failed.

Projects configure at most 32 compute connections and a turn selects at most 32
ids. These shared schema limits apply before manifest persistence, probing, chat
record storage, or prompt assembly. Unsaved compute form metadata remains only in
the live Settings component; local settings drafts deliberately omit it and
discard the briefly shipped v3 field during migration.

The human attaches configured computes through the conversation composer. The
task request and canonical chat record persist the selected ids so reload and
recovery render the last truthful active set. Only selected profiles are eligible
for agent context. Admission resolves those ids once into a bounded, immutable,
server-owned non-secret profile snapshot stored with the task; client-supplied
resolved metadata is ignored. Fresh and resumed prompts, Retry, recovery, and
generic or Experiment watcher wakes use that snapshot rather than re-reading a
later manifest. Watcher continuations persist both the selected ids and resolved
snapshot; older rows default to an empty selection. The first master/task context
describes the names, local or SSH access route, and optional non-secret access
hint. Later ordinary additions and updates send the same bounded profile metadata
in a concise delta so a resumed native session can use a newly attached or
retargeted resource; removals send only the display name. Compute metadata never
grants authority and never includes credential contents or paths.

### Team execution accounts and credentials

The team backend remains the one owner of every provider call, whether the
provider runs on the RCP server or over SSH. A local team run executes as the
Linux `rcp` service account and uses whatever provider-native authentication is
already present for that account. A remote team run uses the exact SSH
host/account selected by the project profile and whatever provider-native
authentication is already present there. The remote account need not be named
`rcp`; it must be explicitly configured and reachable from the server's service
account.

RCP signs each machine account in and out of a provider from the product and
keeps every credential on exactly one refresh path, per the
[provider logins decision](../decisions/2026-09-14-provider-logins-are-kept-alive.md).
It never switches accounts or creates alternate provider homes. RCP's server
CLI checks executable, version, the account's durable login state, configured
runtime, explicit model catalog entry, reasoning effort, and the provider-owned
minimum version for that profile through the same launch abstraction used by
tasks. The provider's own status command is a presence check, not a liveness
check, and is never proof of a login.

Each `ProviderProfile` selects its authentication implementation alongside its
runtime. The implementation owns supported sign-in interactions, credential
requirements and validation, environment preparation, protocol parsing, safe
credential metadata, and interpretation of provider evidence. Shared RCP code
uses these capabilities and normalized outcomes without selecting authentication
behavior by provider name. The credential store owns private atomic persistence
and collision-free account paths; it does not choose launch semantics.
Remote account keys use a digest of the exact execution host instead of the old
lossy character replacement. Tokens stored under the old remote account paths
must be pasted again; RCP does not guess which account owned an ambiguous old
path. Local token paths remain unchanged.

**Codex** owns native device sign-in over the app-server protocol
(`codex app-server`, `account/login/start` with the ChatGPT device-code type).
The one-time code and verification URL are that reply's own fields, the outcome
is the `success` flag on the `account/login/completed` notification, and a
member's cancellation is `account/login/cancel`; RCP reads no console prose, so
reworded provider output cannot stall a sign-in. Codex also owns native logout
and verification commands. A sign-in that ends without its protocol's completion
publishes the reason on the account, which never keeps describing an attempt
that is over.
**Claude** owns setup-token validation, the estimated lifetime metadata,
`CLAUDE_CODE_OAUTH_TOKEN` injection, removal of conflicting inherited credential
sources, and remote token placement and removal. Tokens travel on transport
stdin or through private environment preparation, never in argv, responses,
events, receipts, logs, or backups. The `providers` directory remains excluded
from protected backups. A provider that requires a managed credential refuses
admission when it is missing, including an account with no durable login row.

The shared account lifecycle owner coordinates sign-in, verification, and
sign-out per execution account. Concurrent device sign-ins atomically join one
operation. It acquires the account gate before reading or mutating credentials
and holds it through verification and durable login-state publication. Token
replacement and native device sign-in publish a signed-out fence before changing
credentials, so interruption cannot leave an unverified credential eligible. Successful
verification invalidates readiness and releases eligible parked work through the
existing recovery owners. Completion belongs to this service, not an HTTP poll;
its durable recovery work can be reconciled after interruption without duplicate
dispatch. Member authorization remains at the API boundary; durable changes
record the acting member.

The provider-neutral routes are `POST /api/providers/{provider}/logins/sign-in`,
`GET /api/providers/{provider}/logins/sign-in/{login_id}`,
`POST /api/providers/{provider}/logins/token`, `.../verify`, and `.../sign-out`.
Unsupported interactions are explicitly refused. Status GET only reads operation
status. Sign-out publishes `signed_out` with a new generation, `source="sign_out"`,
and the acting member, fencing admission exactly as a failed login does.

### Login state and failure

RCP keeps one durable login state per `(provider, host)` machine account,
`signed_in` or `signed_out`, with a generation number. A provider process whose
own diagnostic matches the provider profile's revoked-login signatures (for
Codex: `token_revoked`, `refresh_token_invalidated`, `refresh_token_reused`,
"refresh token was revoked", "refresh token was already used", "your session has
ended"; Claude recognizes its own remote missing-credential fence and declares
no native revoked-login signatures until one is observed) is classified
`provider_auth` on every path: a turn, a wake, a worker, an automatic recovery,
the hidden report attempt, and the readiness probes. The classification marks
the account `signed_out` with the generation the launch captured; a late
failure carrying an older generation never re-marks an account repaired since.

While an account is `signed_out` or lacks a required managed credential, every
paid admission for it (an Auto-research
turn, wake, child Work, child Experiment, or report attempt; an Experiment-loop
turn or Retry) is refused before a task is created or budget debited. Human and
API paths receive the refusal text. One shared task-admission fence checks
eligibility before durable task creation or budget debit; queued tasks remain queued when
the account cannot launch. Reconcilers leave the durable input pending
(notices, mail, watcher completions, the report allocation). An Auto-research
recovery for a `provider_auth` failure is created `blocked` and is never claimed
until the account is verified. Readiness reads the durable state, so the Retry
preflight, the project readiness snapshot, and the server readiness coordinator
report a signed-out account truthfully.

**Verify** (`POST /api/providers/{provider}/logins/verify`) runs one minimal
authenticated request as the execution account under the credential gate, using
the profile's `login_probe_command`. Success marks `signed_in`, bumps the
generation, invalidates readiness, and resumes the parked work once: blocked
recoveries are released and claimed, pending lifecycle, mail, and watcher
inputs are delivered, pending wrap-ups restart, and one Experiment-loop turn
that failed with `provider_auth` is retried through its exact path. Authentication
failure records `signed_out` and a safe diagnostic; transport,
unsupported configuration, and ordinary provider failures do not falsely revoke
the login. Any signed-in
member may verify; the acting member is recorded. Recovery release, Experiment
Retry, queued launches, and watcher delivery target the verified account. The
ordinary episode reconciliation pass also runs once, with its existing login
gates keeping other signed-out accounts parked. A catalog failure cannot approve
an explicitly saved model, and an unexpected implementation error fails the command rather than
being relabelled as a missing install. The later provider call uses the same
authentication and version rule. A failed check names the provider and
machine/account and points at Settings, Provider logins, where any member signs
the account in; it never prints a shell login command. Provider credentials
never enter a project manifest, provisioning request, prompt, backup, or
member's desktop credential store.

For execution on the server itself, provider discovery first uses the service
process `PATH`, then the executing account's conventional
`~/.local/bin/<provider>` location. This covers provider-native per-user installs
without borrowing another Linux user's shell configuration. A successful check
still records and later invokes the resolved absolute executable path.

The check always resolves an existing configuration boundary:
`rcp server provider check --request <request-id>` checks the intended profiles
of one provisioning request, while `--project <project-id>` checks the stored
profiles of one existing project. Exactly one selector is required. The command
does not accept an arbitrary host, account, executable, provider home, or runtime
that could bypass the request/manifest contract.

The service owns resolution and probing through its private control socket; the
`rcp` CLI never opens SQLite beside the running process. Planning is read-only
and binds one SHA-256 boundary over the durable request revision or stored
project profiles. Each check revalidates that boundary before a subprocess and
publishes a safe refusal if it changed. A successful request check stores only
the resolved absolute executable path, bounded version, durable runtime id,
observed OS account, and check time. Rechecking that request uses the stored
executable instead of rediscovering `PATH`. The provisioning projection exposes
those nonsecret proof fields for final review; no provider home or credential is
added. `server doctor` separately reports whether the running private control
protocol offers provider readiness.

The central Git checkout and its repository-scoped deploy key are independent of
the provider login. A Git key grants repository transport; a provider login
grants provider execution; an RCP member token grants product authority. None is
accepted in place of another.

Every team checkout's local Git config pins `core.sshCommand` to its own deploy
key, so any process in that repository, whether terminal, Discuss, Work, or
episode, fetches and pushes with it. Provisioning writes it and checkout
verification backfills it. This grants transport only: a launch's write roots
still decide where it may commit, though any launch, Discuss included, can push
refs that already exist or delete a remote branch. Every terminal and provider launch also gets
`GIT_CONFIG_SYSTEM` naming a generated file with the member's default identity,
their display name and `<member-id>@members.rcp.invalid`. It sits at Git's
lowest precedence, so any repository or global `git config` overrides it; on a
team server those layers belong to the shared service account and apply to
every member. RCP stores no per-member Git setting. Pushes authenticate as the
deploy key, so project membership is repository write access and removal is its
revocation ([decision](../decisions/2026-09-24-team-launches-carry-git-transport.md)).

Remote execution adds one more transport boundary: the server's `rcp` account
must already be able to authenticate with ordinary OpenSSH to the exact account
in the selected machine profile. A remote project manifest records that account
as `machines[].os_account`; omission is refused rather than guessed. A
server-local team profile executes as `rcp`, including for older manifests that
predate the explicit field. RCP checks and uses that configured route; it
does not import a member's SSH key, collect one through Web/desktop state, or try
a different login. This SSH transport authentication does not select the remote
provider identity—the remote operating-system account and its native provider
state do.

There is no team fallback to a member laptop, personal checkout, local member
provider login, or different SSH account. Unreachable SSH, missing provider
authentication, or incompatible provider readiness fails visibly on the chosen
machine. Runtime-specific behavior remains behind the provider-call abstraction,
so Codex exec, Codex app-server, and Claude use their own provider contracts
without changing this local/SSH identity rule.

Remote canonical-state locking and publication are specified in
[Graph, history, and transitions](graph-history-and-transitions.md#canonical-publication).

### A remote turn outliving its connection

Four owners register durable remote-turn finalization: ordinary human Work,
Discuss, the Experiment loop, and the Auto-research child Work turn. Each retains
its own launch snapshot under its own contract role, and the routing table
selects the owner from that retained contract, never from the task's chat kind --
one chat kind names all four. A task with no retained contract, or with more than
one, is visibly left waiting rather than settled by a neighbour that shares its
launch plumbing. Remaining provider task owners keep their existing launch
behavior until they expose their own typed, idempotent post-provider finalizer.
Shared staging and local-only turns register no remote finalization context: a
local provider dies with the process that launched it, so there is no finished
pass left to fetch.

What an owner settles is its own. Work applies its Patch, arms its watchers and
answers its chat. Discuss answers its chat and republishes the session binding
that lets the next message continue the same provider conversation. The
Auto-research child settles under the parent episode's authority, admitting no
second child to go and fetch its result. The Experiment loop reaches its joint
Patch/watch admission and binds the episode to the session a later wake resumes;
it settles against the episode its launch read, whose baseline, control snapshot
and committed wake session are written down before the provider starts, so a
reconnect cannot commit a pass belonging to a different invocation.

Automatic graph, watcher, and Experiment watcher-maintenance corrections within
ordinary Work use the same supervision. Before any correction, Work retains the
primary answer in an immutable database checkpoint. Replaying a correction
applies its deliverables while preserving that original reply and starting no
further correction calls. A recorded pass that is itself a failed correction
still carries that retained reply ahead of its own error, because the live path
had already delivered it before the correction began. No recorded finalization
may correct a deliverable:
the provider that could answer a correction stopped when its connection did, so
a deliverable a live turn would have sent back is rejected instead, and a
recorded pass offered a correction round fails rather than launching one. Manual
graph-repair tasks retain their separate existing launch behavior.

Provider execution state and controller connection state are separate things.
Losing SSH says nothing about the provider, which on a remote host keeps working
and finishes into a stage RCP can read later. So a lost link is not a failure of
the turn, and recovering one is not a new turn: the pass belongs to the operation
that opened it and is finalized on that same operation, under the authority,
graph target, episode and accounting identity it already had.

A supervised pass is journalled on its execution host. Its source travels as a
staged run input and the launch names that path, because a command large enough
to carry the source cannot reach an SSH multiplexing master: the client fills the
control socket with the command and then fails passing the process's own file
descriptors, so the launch dies before the host runs anything. A supervised
launch without that staged path is refused rather than sent. The supervisor
forwards output while recording it, and writes its acceptance of the prompt
before a byte of it reaches the provider. That host-written acceptance, never
the presence of a receipt in RCP's own database, is what says work may have
begun: a controller that died in that window has no receipt of its own, and its
silence is not the host's answer.

The supervisor publishes no verdict. It decides only where the turn ends, which a
persistent server makes unavoidable, and hands over its bytes. What the turn was
worth is read from those bytes by the same decoder that reads a live one, so the
two cannot drift apart. The supervisor also snapshots the turn's deliverables
beside its journal, Patch and watcher handoff alike, each under its own digest.
A stage is mutable and a recorded pass is not, so every owner restores those
snapshots before reading any deliverable: what settles is what the host proved,
not whatever the directory happens to hold when RCP reconnects. Experiment watcher
maintenance writes one file per resource, so that set is discovered rather than
named: the host snapshots all of it, and recovery makes the stage hold exactly
the set the pass wrote, removing one that appeared afterwards. The provider
chose that set's size, so it is bounded as a whole and not only file by file,
and a pass that overflows either bound is an incomplete turn whose outcome
claims none of the set rather than a smaller one. A journal that
predates deliverable snapshots is silent about a handoff rather than claiming
there was none, and recovery leaves those files alone rather than deleting them.

A host that cannot be reached is never a verdict about watcher maintenance. An
outage while reading, validating or persisting those outputs leaves the task
waiting for its stage, rather than completing it with the maintenance silently
undone or recording a permanent refusal the turn never earned.

Reconciliation is owed only a pass nobody read. A supervised start with no
recorded stop is what both the waiting-task query and the reconciler itself look
for, so once a live stream has consumed a turn and written that stop down, no
reconciler will revisit it. Settlement that fails after that point therefore
reports the outage rather than parking the task on a remote result it already
holds, which nothing would ever come back for. A completed provider spoke for
itself, so such a failure is not a lost link and no retry repeats the turn.

Settlement reports an unreachable stage the same way it reports a deliverable
the agent botched, so the read that failed is what says which happened. Every
owner reads its own deliverables through its own code and marks its own
outages, including on paths a recorded pass may never take: the mark is read
only when a recorded finalization fails, so marking too widely costs nothing
while marking too narrowly loses a finished turn. A failure carrying that mark
leaves the task waiting; one that does not is the turn's real verdict and
stands, whether or not the host is still answering by the time it is recorded.

A continuation pinned to an exact native provider session is held to it when it
is recovered exactly as it is live. Every supervised launch writes down the
session it pinned before it reaches the host, including a correction, whose
session belongs to the pass it corrects and so cannot be named by the launch
snapshot written before that pass existed. This holds for every supervised
correction, including the Experiment watcher-maintenance one that reaches its
host through the raw provider stream rather than the shared Work one. The launch
retains the session it pinned beside the rest of its snapshot, a correction
retains its own, and a journal that answered on a different one
is refused before its Patch reaches the stage, before that session is adopted
and before any watcher is armed -- the same refusal, and the same operational
receipt, that stops such a turn live before any result is accepted. A launch
that pinned no session pins none on recovery.

A restart preserves a task holding such a pass instead of interrupting it, and
leaves it waiting for a remote result. Reconciliation then asks the host one
question with five answers: unreachable and still running both wait, without
limit; a stopped pass whose journal reached the turn's end finalizes that task; a
stopped pass whose journal did not, or that never took the prompt, fails it
visibly for a human to retry; an already settled pass is left alone. Waiting is
never cut short by a timeout, and nothing replaces a provider that may still be
working. Reaching the host once proves nothing about reaching it again: an owner
reopens its retained stage over the same link and reads its deliverables from it,
and those reads report a vanished host exactly as they report a deliverable the
agent botched. No verdict is drawn about a turn whose stage cannot be seen, so a
host that goes quiet anywhere between reading the journal and finishing
settlement leaves the task waiting rather than settling an intact result as
failed. A stage that was genuinely removed is an answer, and the failure it
causes stands. Reopening a retained stage cannot report both the same way:
silence from the host is retried, while the host answering that the stage is
gone, replaced or no longer ours fails that turn for a human.

Pause of a waiting task is immediate and requires a reachable host and verified
process identity. If the provider already stopped, or finishes before the Stop
arrives, its completed journal stays available for finalization. RCP refuses the
Pause instead of discarding that output; an unreadable journal also stays
unresolved. There is no delayed kill intent. Active reconciliation counts as
runtime work for maintenance draining and joins the bounded shutdown wait.

## Seed and Refresh ingestion

Seed and Refresh alone ingest provider conversation logs. RCP supplies the
execution-host agent with configured provider log roots, project
`last_refresh_at`, the complete current graph and research rendering, exact
repository pointers, selected packages, and an optional human request.

The agent reads logs in place. RCP performs only bounded existence/readability
preflight and reports exact failures without blocking launch. RCP does not parse,
index, normalize, slice, hash, cache, transfer, or project provider conversation
content and maintains no per-log cursor or coverage truth. There is no agent-written
coverage report or coverage-warning banner.

That is the implemented ordinary-run path, not a promise to abandon source
history during a pending personal-to-team transfer. The confirmed transfer
target exports every complete provider conversation selected through the
existing native conversation index into the read-only project app-data root
`<RCP_DATA_DIR>/project-sources/<project-id>/provider-history/<provider>/`.
Configured provider profiles supply the native roots, while the index remains
the one owner of project-path matching and local/SSH source retrieval. Matching
is automatic and best-effort from recorded working paths; skipped sources are a
non-blocking diagnostic, not a transfer decision. The target agent reads those
imported provider-native sources alongside live roots from its configured
execution account. Local execution reads the project-owned source directly;
remote execution stages only that validated project-owned inventory as immutable
task input and leaves the remote account's live native roots in place. Resume
reuses the same staged fingerprint, and a missing or changed stage fails visibly
through clean retry rather than omitting history. Missing or corrupt durable
imported bytes block Seed/Refresh; the non-blocking best-effort rule applies only
to source-side selection before transfer. RCP-owned project chats
transfer only as human-visible history and remain excluded from Seed/Refresh
input under the native-chat-context rule. Imported sources never enter canonical
`.research`, a rebuildable cache, or the native provider home and never grant
Resume, Retry, credentials, or execution authority. The index copies the
selected original native transcript files byte-for-byte; RCP does not flatten
them into its lossy conversation-record model.

The watermark advances only after a Seed/Refresh Patch commits. Failed,
paused, interrupted, or rejected work leaves it unchanged. It is an
overlap-tolerant timestamp, not exactly-once ingestion.

Seed/Refresh correction stays scratch-only and offline over the retained staged
inputs. Large source-corpus fan-out is provider-owned and read-only; the root is
the sole Patch writer.

## Provider readiness and native skills

Readiness is an app-process service. Startup coalesces provider executable,
version, authentication, model-catalog, and configured machine probes; results
are cached for their configured lifetime. Explicit Refresh bypasses the cache.
A profile probes whatever its CLI can enumerate and declares only the rest.
Codex reports its models and their per-model reasoning efforts from its own
catalog. Claude Code cannot enumerate models, so its aliases stay declared and
dated to the CLI they were read from, while the reasoning efforts it accepts are
probed from the CLI itself and are provider-wide. A probe that cannot be read
falls back to the declared list rather than leaving a surface with no models.
Navigation never owns provider warmup and ordinary application use remains
available while it runs.

A provider login is one rotating credential owned by one execution account, and
no provider CLI locks it while refreshing. RCP therefore admits one provider
startup at a time per provider and execution account. Turns, readiness probes,
and skill inventory probes share that one gate. Each credential-touching path
acquires it before preparing the environment and capturing the login generation
from the same credential state. A turn rechecks eligibility there before spawn;
a late failure from an older generation cannot invalidate a repaired account.
The provider implementation interprets evidence from turns, verification, model
catalog, Work readiness, and skill probes; shared code durably applies the same
authentication-failure policy on every path. Each runs the provider
executable and each can rotate the same token; a probe holds for its whole run,
while a turn holds until the provider writes a line of its own and a minimum
stagger has passed. A broker readiness line is not the provider speaking. A hold
expires on a generous bound, which prefers a rare unserialized start over one
stalled startup closing the credential to everything else.

RCP starts no provider process it does not need. The credential-touching
readiness answer (login status, model catalog, Work probe) is stored durably per
`(provider, host, executable)` with the version it was read from; a later
readiness read runs only `--version`, with its environment prepared under the
account gate, and reuses the stored answer while the version is unchanged. An
explicit Refresh, a version change, a verify, a sign-in, or a sign-out probes
again. The skill inventory is reused the same way while the executable, its
version, and the probe command match the stored inventory on implicit reads.
The explicit readiness Refresh also probes every target's skill inventory
without reusing the stored one, so an edited provider-native skill becomes
visible while nothing about the executable changed. A provider process,
probe, or turn is never signalled before the gate's minimum hold has elapsed
since it started, so a login refresh begun at start can finish its write; a
probe timeout is clamped to that hold, and a Pause of a young process waits it
out before the signal.

A local login is also held against other RCP processes through an advisory lock
under the account's own RCP directory, because two data directories share one
login while the single-instance lock only excludes a second process on the same
data directory. The operating system drops that lock when its holder exits, so a
crashed process never strands a login. A remote login has no such file: the
credential sits on the far machine, where only a lock taken there would mean
anything, so remote launches are serialized within one RCP process only.
If the local account lock cannot be created, opened, or acquired because of a
filesystem error, the startup or probe fails with the lock error. Only lock
contention retries; a failed acquisition releases its in-process lock so a later
attempt can succeed after the filesystem problem is corrected.

This staggers startups, it does not make rotation safe. A provider that
refreshes again mid-turn is outside the boundary, and RCP never performs or
stores the refresh itself. Reaching one account through two spellings of its SSH
destination still yields two gates.

After authentication succeeds, the Claude profile also supplies a zero-cost
Work-like startup probe using its enforced Work settings, stream-json input,
and closed empty stdin. It proves the installed CLI accepts those settings
before any model call; it does not prove containment. The
cached readiness result records Work-like availability and its concrete reason,
kept apart from the general readiness reason, which also carries benign notes
such as a discovered path. Settings renders it only on a profile the projection
marks as able to launch a Work-like capability, which a profile's default
capability cannot establish: a chat profile defaults to Discuss and still
launches Work. The paper coach is never subject to it. A Work or orchestrate
launch checks this
precondition alongside the profile's version requirement before starting its
provider turn. A CLI that refuses those settings fails with the provider's actual
diagnostic; connection loss or an unreachable host is reported as such, not
diagnosed as a refused setting. Discuss does not require this precondition or
attach the enforced write settings. Refresh and normal readiness invalidation also invalidate the probe.

A decoded provider error includes meaningful captured stderr in the first error
event, with a bounded drain after process termination and existing shell TTY
noise filtering. When the result has no text-bearing field, its subtype is the
fallback diagnostic. This preserves the real startup failure for task consumers
that stop reading at the first error.

Every provider process is also journalled by the service: one log line when
it starts and one when it ends, each carrying the provider, capability,
runtime, execution host, resolved executable, child pid, and the operation id,
with the exit code, duration, and RCP's own reading of a non-zero exit on the
end line. A failed task adds one line naming its classification. These lines
carry identifiers and RCP wording only; provider stdout and stderr never reach
the journal, because a provider CLI can print token-shaped values in its own
errors. The task row remains the complete record.

A settled failure is also named, because recovery differs by cause. SSH's own
exit codes for a remote run mean the link died rather than the work, and RCP
reattempts such a turn a bounded number of times with growing waits before
leaving it to a human; the reattempt is the same recovery a human Retry
performs, so it resumes the native session rather than repeating the turn. Those
exit codes decide this only for a turn that said nothing: ssh returns 255 for a
provider that exits 255 as readily as for a link it lost, so a provider that
reached its own terminal event or reported its own error is never blamed on the
link, whatever the code. A link that drops before the provider starts is named
the same way. Opening the remote stage, every stage read or write that prepares
the turn (such as clearing the previous turn's mailbox), the readiness probe
under whichever of its probes ssh died, the check that the previous remote pass
has stopped, and the input transfer each fail the turn with no process to leave
a code, so each
carries its own typed word for an unreachable host to classification, on the
host the turn was bound to even before a stage existed; the error text is never
read. Only an ssh or rsync that ran to a verdict and exited 255 carries it: one
RCP could not start, or stopped waiting for on a live link, is a failure the
same reattempt would meet again.
An unreachable readiness answer is not cached, so the reattempt asks the host
again instead of failing from memory. A reattempt stands down when
anything else has already taken the turn over, so a wait that outlives the
failure it was scheduled for cannot repeat finished work. That claim is made
inside the admission that inserts the reattempt's child: an ordinary task's
resume, retry, or handoff is refused there when the task already has one, so a
human Retry admitted and settled during the wait leaves the timer nothing to
repeat. Experiment and Auto-research recoveries keep their own atomic claims.
Shutdown waits for a reattempt that has already begun admitting before it
fences new workers, so the child it admits is paused with the rest instead of
being left queued for a startup that would only interrupt it. A wait whose reattempt is refused keeps the waits
that remain, because a host that is still returning is the case the longer waits
exist for. The promise of a reattempt is durable while the wait holding it is
not, so startup re-arms the waits a stopped process could not keep, at the wait
the sequence had reached rather than at its first; a turn something else has
already continued is not re-armed.

An Experiment-loop turn whose link dropped before it composed its prompt sent
the provider nothing: its lineage holds no prompt contract, only bookkeeping
such as a context candidate or finalization context. That is not a legacy root
to refuse. Its recovery, automatic or human, runs the same invocation again as
the turn it recovers, a watcher wake as a wake, and records the context that run
sends; the child carries an `experiment_uncomposed_rerun` receipt, and later
recoveries keep the newest candidate in the lineage. A lineage that composed a
prompt but kept no candidate is legacy and still refuses recovery.

A Work Resume or Retry continues the prompt its lineage first sent. Every
launch, including a chat-protocol or Auto-research child Work turn, records the
prompt it sends as a durable task contract. The `agent_prompt` launch receipt is
a bounded diagnostic (`AGENT_TASK_RECEIPT_MAX_BYTES`) that may be omitted or
pruned, so recovery never depends on it alone.

New automatic launches wait until the machine has stayed awake long enough to
finish one (`AUTOMATIC_LAUNCH_AWAKE_SECONDS`). A laptop sleeping with its lid
closed wakes for a few seconds at a time, and a launch started in one of those
wakes loses its link partway through. Watcher delivery leaves a completed group
for the next poll; a transport reattempt re-arms its wait without spending the
attempt; an episode report stays wrapping up for the next reconciliation; and
Auto-research mail and lifecycle wakes leave their inputs pending for the next
pass. Re-dispatching a wake an earlier pass already admitted is not held, and
falls back on the lost-link reattempt. Sleep is read from two monotonic clocks, one that counts time
asleep and one that does not, named per platform in `rcp.machine_sleep`: on
macOS `CLOCK_MONOTONIC` counts sleep and `CLOCK_UPTIME_RAW` skips it, on Linux
`CLOCK_BOOTTIME` counts it and `CLOCK_MONOTONIC` skips it. A platform with no
named pair, or a pair that stops behaving as named, holds nothing. Turns a
human starts are never held.

A provider whose CLI reports that its own login is no longer valid is named
separately, because no unattended attempt can fix it: every one fails
identically until a person signs in again. That name informs, and never
withdraws the way back. It stops the automatic transport reattempt, which would
only spend three waits proving the point, and it makes the projection ask for
the sign-in. It withdraws no control and withholds no scheduled recovery: a
failure kind never changes, so anything taken away on one could never be given
back, and signing in again is exactly what makes the next attempt work. A
profile that has had no real revoked login observed claims none, since a wrong
match would name a failure Retry would have fixed.

A saved provider session the provider no longer has is named separately from one
that reached its limit, because the remedy differs: a session that is simply
gone cannot be resumed at all, so recovery starts the turn clean instead of
resuming into the same failure. A session-bound episode is the same case: its
binding names a session the provider has dropped, so recovery hands the episode
to a clean session on the record rather than refusing and stranding it. Every
other failure keeps its existing behaviour.

A reattempt that failed the same way as the attempt before it ends the ladder
whatever the failure was named, because the remaining waits would only reproduce
a settled answer. RCP does not read provider prose for whether a reached limit
belongs to the session or to the account: it offers the human the one thing that
makes the next attempt different, a changed provider, model, or reasoning, and
whether that attempt then succeeds is the provider's answer rather than a state
RCP models. A stopped ladder, whether it stopped on a repeat or ran out of
waits, is a verdict on the failure that produced it, so the human's own Retry
retires it before that turn exists: the turn can settle the instant it is
spawned, and its settlement is what writes the next verdict, so the next failure
is judged on its own and gets a full ladder. The automatic path keeps counting
its attempts as before. A Retry that is then refused leaves no verdict and no
attempt, which reads as the failed turn it still points at. A
revoked login is the exception it already was, cleared by signing in rather than
by retrying. Reattempts, their refusals, and their exhaustion are receipts on the
failed turn.

Provider-native skill inventory is app-scoped and separate from official RCP
packages. Startup refreshes each provider/machine target after readiness. A
successful refresh atomically replaces the last successful result; failure
retains it as visibly stale with a current diagnostic. Project open and launch
do not refresh it.

A native skill selection is structured per-turn metadata bound to provider,
machine, successful version, inventory hash, and name. It never changes launch
flags, authority, graph scope, or repository scope. A stale selection that the
provider rejects fails visibly without fallback.

## Official skills and workflows

Project Settings selects official packages. Every official skill is enabled by
default unless the human saves an explicit selection, including an explicit
empty selection. Official workflows remain opt-in.

Only selected packages are staged to the execution machine as immutable,
content-addressed directories. The agent receives compact id, version,
description, dependency, and exact pointer metadata; package bodies are never
embedded into launch prose. Slash completion inserts only the visible token and
a per-turn invocation pointer. Packages supply methods and examples under the
current task contract; they do not replace its authority, output channels, or
filesystem boundary. The same method may serve an ordinary worker, a bounded
Experiment, or the orchestrator without importing another role's permissions.

Graph-writing contracts include shared authoring methods and a local causal
check, using only inputs the task permits. A planned empirical prerequisite
names its precursor Experiment and intended handoff; it does not create Evidence
before an observation exists. For example, plan a calibration before recording
its measured Evidence and the Decision that Evidence informs. A smoke or
validation Experiment is never blocked on the infrastructure it exists to
verify: that setup is written into its own design, the smoke carries
`blocked_by` only for a constraint its run cannot remove, and a downstream main
Experiment keeps the `blocked_by` edge to the Blocker the smoke's Evidence will
address. Decision options are written only after every distinct choice has been
investigated with equal care, at one level of detail, with any leaning recorded
in `rationale` rather than in option order, length, or wording. Optional
`graph-audit`, `experiment-causality`, and `evidence-triage` packages add deeper
methods and examples. Programmatic quality advice belongs to the existing live
Patch validator, not a separate mandatory scanner package or model call.
Nonblocking flags return in a valid result's `messages` with exit code zero;
blocking errors take priority while the Patch is invalid. Quality advice does
not require another provider turn and cannot change acceptance or graph authority.

## Network behavior

Every user-facing Seed/Refresh, Discuss, Work, Experiment, Auto-research, merge,
and Paper surface retains its provider-native public-web behavior as defined by
its contract. Exact project write roots do not add a new network restriction.
Generic scratch-only Patch correction remains offline where its retained
contract requires that.
