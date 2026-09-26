# API, Web, and desktop projections

This specification owns public project projections, current Web surfaces,
revision reconciliation, navigation and tab state, and desktop-shell lifecycle.
It does not grant graph authority; mutation routes delegate to the state
workspace and transition manager.

## Member terminal API

The project-scoped terminal routes are:

- `GET /api/projects/{project_id}/terminals/repositories`: repository alias,
  starting path, per-machine capability, and running Work identities.
- `GET /api/projects/{project_id}/terminals`: open sessions and live/idle state.
- `POST /api/projects/{project_id}/terminals/probe`: invalidate this project's
  machine probes and schedule fresh results.
- `POST /api/projects/{project_id}/terminals` with `repository_id`: open or return
  the single existing session for that repository and project.
- `DELETE /api/projects/{project_id}/terminals/{session_id}`: end that session.
- `WS /api/projects/{project_id}/terminals/{session_id}/ws`: binary PTY output,
  JSON `input` (`data`) and `resize` (`cols`, `rows`) messages, and a JSON `ended`
  notification.

Every HTTP route checks project membership. The WebSocket performs its own
identity, project membership, same-origin, and maintenance admission because
HTTP middleware does not cover upgrades. It rechecks before every input, on a
short interval before output, and periodically while connected; cookie
revocation and loss of membership close the connection. Output is rechecked on
an interval rather than per frame because the check is a synchronous store read
and a PTY can produce hundreds of frames a second. Unknown and nonmember projects remain indistinguishable.

Repository rows retain `eligible` and `unavailable_reason` and include
`machine_id`, `backend_id`, `backend_name`, `containment`, `os_name`,
`probe_state`, and a `reason` for every outcome. Available machines report `mirrored` or `cooperative`; unavailable
machines have null `containment`. The reason names the applicable launch
capability, missing canonical-state protection, or failed prerequisite. Remote
probe states distinguish `pending`, `reachable`, `incapable`, `unreachable`,
`authentication_failed`, and `host_key_failed`. A cold projection schedules one
probe per machine and returns pending immediately; repositories reuse the cached
result without an SSH round trip per row. The cache lives with the terminal
manager and is invalidated explicitly by Refresh or by changed machine metadata.
Space kind does not participate in eligibility. The projection and open guard use the same
per-machine capability resolution; a later mirrored launch failure remains a
hard failure with its real diagnostic, never a cooperative session.

Session payloads carry `containment` and `protection_notice`. A cooperative
session explicitly reports that canonical-state protection is unavailable on
this machine. The Terminals destination appears when any machine can host a
session, and whenever the project has an open one, because the destination is
the only way back to a running shell and the only way to end it. Remote pending
and failed probes also keep the destination visible so members can read the
reason and refresh it. Empty projects and projects with only unavailable local
machines and no open session hide it. Repository controls show unavailable rows
with their reasons. A lost SSH link produces an `ended` reason, removes the
session from the open list, and leaves the diagnostic visible without offering
to reconnect into a new shell. That diagnostic belongs to the open destination
and survives a refresh there, not a departure from it: the session projection
carries open sessions only, so a link that drops while the member is elsewhere
leaves the reason in the persisted record rather than on their screen.

The shell runs as the service account with the Work trust boundary. A mirrored
session's mount namespace provides accident resistance to mistakes; it does not
isolate a member from that account.
Per-machine capability and canonical-path refusal are owned by
[Providers and containment](providers-and-containment.md#member-terminals);
session expiry and metadata are owned by
[Projects, spaces, and operations](projects-spaces-and-operations.md#member-terminal-lifecycle).

## API composition and mutation boundary

One FastAPI backend serves the JSON API and, when built, the React/Vite
application. The optional Tauri shell starts or reuses that same backend. There
is no second team protocol or frontend-owned background-worker runtime.

`api/app.py` owns explicit composition, run dispatch, startup recovery, and
watcher runtime. Extract another control layer only for measured owner
collisions or a concrete testing problem, as recorded in the
[backend structural decision](../decisions/2026-08-20-backend-structural-refactor-closure.md).

Route handlers resolve identity and membership, validate request shape, stage
intent, and call the owning service. They never write `.research` files,
materialized output, branch metadata, or Patch history directly.

Every graph mutation response uses one strict transition projection containing
the graph target, head, graph, Experiment-control map, guidance validity,
transition/ruleset identity, primary question, graph counts, and any causal or
attention inputs from the same final state. Preview responses are explicitly
noncanonical and name their base head and ruleset. The browser renders these
published values instead of recalculating a second transition result.

Any derivation whose inputs are all backend state belongs to the projection:
for example, `EpisodeResponse.health`, `recommendation`, `live`, `can_*`, and
`ExperimentControlState.graph_reasons`. Only derivations with a UI-specific
input, such as the trust-view lens, stay client-side. `web/src/types.ts` is the
single response-shape restatement. Fully projected lifecycles use opaque types,
including `EpisodeStatus` and `AgentTaskStatus`, so client branching on the raw
status cannot compile.

Project snapshots and transition projections publish exact graph-attention
membership as pending Proposal ids, Decisions awaiting choice, and asserted
open Blocker ids. Pending Proposals additionally publish their ordered action
lines, including incident relations removed with a node. Counts are lengths of
that same projection. The browser maps those ids and action lines onto the graph
it is presenting; Inbox, Overview, and Runs never reapply the membership or
Proposal-operation predicates. A backend preview supplies both the candidate
graph and candidate membership, while a rule-inert local draft retains the
current backend membership until Sync. Cached snapshots are invalid when their
membership or the three corresponding counts disagree with their graph. The
browser validates the exact projection shape, exact Proposal-action membership,
and referenced graph member types; missing or malformed membership fails the
snapshot instead of becoming an empty attention view.

Each Experiment-control entry is also a complete read model. In addition to
budgets, reasons, episode, and operational history, it publishes health,
recommended action, Runs section, liveness, Start/Stop/report availability,
pending Stop, the exact Resume/Retry and provider-switch controls, and whether
the human has closed the Experiment node itself. The browser may translate those
closed answers into labels and layout, but a newer task poll or raw episode field
never overrides them. Runtime, episode parent,
visible tasks, budget usage, and report are read inside one SQLite snapshot, so
one response cannot splice lifecycle facts from different instants. Recovery
controls bind to the exact operation id named by the backend and disappear when
that task row is unavailable. A backend candidate graph must be synced before
Start because the run endpoint still authorizes the canonical graph; a
rule-inert local prose draft does not create that fence.

Concurrent project snapshot requests are fenced per project and graph target by start order,
including equal-revision responses. Once a newer cache, reload, watcher poll,
settings save, or Sync starts, an older response cannot overwrite its graph or
operational controls.

A completed project snapshot publishes whether canonical graph mutation is
available and the exact unavailable reason. Watcher responses similarly publish
whether **Check now** is currently available. These are backend decisions, not
client reconstructions from replay, status, or notification fields.

Every branch route proves the branch belongs to the requested project and
episode. A branch id alone never grants lookup. Task, watcher, episode, and
Experiment detail APIs preserve exact `main` versus `branch:<id>` target
identity.

Graph, snapshot, history, Sync/preview, and ordinary chat/task routes accept an
optional `branch_id` query naming an existing episode branch. Omitting it selects
main; project-wide task and watcher lists retain their project-wide default.
Snapshots publish `graph_target`, `graph_head`, and `graph_changes` (null on main).
`graph/changes?branch_id=...` publishes the same canonical base-to-head semantic
delta, changed and neighboring node ids, before/after values, and Patch/task
provenance. The backend derives that read model from one coherent branch replay.
A project tab reopened from the space page or another tab returns to the graph
target it was last left on, main or branch.

The durable project display cache remains main-only. A branch cached-snapshot
request returns an explicit cache miss, and the authoritative snapshot endpoint
opens the exact branch. Target-scoped polling observes its branch revision and
graph mutation availability, including merge-state changes at the same revision.
Branch reads validate refreshed state without repairing or publishing graph
outputs; an unavailable canonical refresh fails explicitly.
Neither a branch response nor a delayed main response may replace the other
target's state. Experiment controls and graph-wake evaluation use that same
target. An active branch merge publishes graph mutation as unavailable and
rejects manual Sync and new graph writers until it settles. Discuss remains
available with its ordinary read-only capability.

## Compute setup and job APIs

Project machine entries expose the manifest `compute` block and live
`compute_probes`, one `ComputeBackendProbe` or null per route. The latter is
read from storage even when the graph snapshot is cached. Settings updates
accept `machine_compute`, a partial alias-to-`MachineComputeConfig` map; null
removes a block, omission preserves it. Validation and TOML persistence belong
to the machine configuration owner. A changed block invalidates its stored
probes and schedules a fresh background check of that machine.
`POST /api/projects/{project_id}/machines/{machine_alias}/compute/check` uses
project write admission, re-probes every route that machine offers, and
returns both route slots.

`GET /api/projects/{project_id}/watchers` supplies the external job rows for both
scheduler and helper work. Every external row includes its required shell check,
log path and cwd, optional cancel command, check state/diagnostic, and cancellation
requester/time/diagnostic. The backend exports `can_cancel`; the browser does not
derive it from watcher status. There is no separate compute-job list request.

`POST /api/projects/{project_id}/watchers/{watcher_id}/cancel` requires project
write admission and an attributed human. A missing or foreign-project watcher
returns 404. An already-observed completion or accepted cancellation request
returns the row unchanged; no cancel command returns 409. A fresh precheck may
establish completion without attributing it to Cancel, or report why the action
could not run. Otherwise the route claims and executes the saved command once.
Its result is an action receipt, not a separate cancelled watcher state. Errors
are returned on the watcher and allow an explicit retry.

Settings stages per-machine `job_manager` and optional helper `jobs_root` beside
provider paths. **Use Slurm** opts into direct scheduler submission; RCP exposes
no resource-argument inputs. Only changed aliases are saved. Draft storage keeps
explicit machine edits, so an unrelated draft cannot restore an older full
compute configuration. Unsaved machine edits mask readiness. A save that
changes a machine's block probes its offered routes in the background; Runs
offers **Check again** through `POST .../machines/{machine_alias}/compute/check`.
Each stored probe supplies its own label, tone, and diagnostic.

Chat and Experiment use the existing watcher refreshes to show one external job
row. It displays the log path, observation state, check diagnostic, and Cancel
history. Human Cancel follows the backend's capability even for a stopped
watcher, independent of graph read-only mode; the API enforces project write
admission. The immediate action response updates its row without adding a
second job-list polling lifecycle.

## Atomic client project snapshots

The Web client stores a bounded project snapshot keyed by project id and exact
head. A successful mutation atomically replaces graph, control, guidance,
transition manifest, and derived inputs. The client never overlays a new graph
on an old control map and never implements transition rules.

Human edits that the backend manifest proves rule-inert may update a local draft
immediately. A possible trigger, absent manifest, or stale tag previews through
the backend. A preview conflict retains the invalid edit and last valid draft
separately. Sync revalidates the complete batch against live canonical main and
commits once or not at all.

Human Sync accepts built-in and active custom nodes through the existing
`custom_nodes` collection, plus `added_edges` and `removed_edge_ids`. Preview and
commit share the same backend owner and exact base revision. Edge replacements
remove the old edge before creating its replacement in the same transition;
layers are resolved by the backend. The membership-protected `graph-edit-options`
endpoint publishes built-in relation names, Evidence-assessment requirements
and node ID prefixes from backend rules without replaying project history. The
client reads custom relations from the displayed ontology; backend preview completes
new node defaults and resolves edge layers. A draft with edge
changes retains its original edge-edit revision across refresh/reload; it cannot
silently rebase connection edits onto a newer graph.
These controls remain human-only and add no WebMCP graph-writing tool.

Resolved/superseded Blockers remain canonical but are omitted from active
Research-flow and attention projections. Stale Experiment summaries and next
actions are labelled historical and never rendered as current guidance.

## Revision observation and drafts

Visible clients notice canonical main changes without browser reload or
repurposing the Seed/Refresh action. Every open project tab sends a cache-only
heartbeat on the bounded visible cadence; the active tab observes completed
cached revision updates more frequently, and visibility resume sweeps all tabs.

A heartbeat may schedule one bounded lock-free, single-flight remote-head probe
per project. A temporarily unavailable head does not replay or copy the graph.
An unchanged head also skips that work unless the cached canonical state is
offline: a successful probe then triggers authoritative reconciliation before
clearing the offline state. Movement starts the same background reconciliation;
an older result may not replace a newer cache.

Reconciliation preserves human drafts. A staged node whose canonical revision
did not move stays committable. One that moved becomes behind and is excluded
from Sync until the human edits it or reversibly swaps an incoming field into
the draft. Paper drafts use their own equivalent whole-document rule. Display
caches never become canonical input or graph authority.

## Project index and identity

The project index keeps project cards first and one distinct space-level
**Runs** ledger below. It aggregates the current Experiment-loop parent selected
by each Experiment's backend control with Auto-research parents across visible
projects. **Needs Action** and **In progress** each stay unfolded and mix both
modes in reverse chronological order, under the same truthful split the project
ledger uses; **Completed** folds by Experiment loop then Auto-research.
The backend owns membership, lifecycle placement, health, project identity, and
the exact Experiment route. The space ledger keeps completed parents for seven
days, without deleting episode records or changing project Runs or History.
Auto-research rows carry their exact episode identity into project Runs, so a
completed or non-leading row opens that parent rather than the default card.
That exact parent is read independently when it falls outside the project's
bounded episode list.

The index header contains the compact current-human identity control. An unnamed
personal owner sees **Sign in** as naming the durable local identity, not creating
an account. The panel shows editable display name and exact read-only copyable
user id. A team member uses the server login/session boundary and can manage
their own credential. Pending project invitations appear on the index.

The team identity panel includes **Devices**, listing the member's unexpired
sessions with connection and last-seen times. **Current device** has no Revoke
control; ending it remains Logout. The panel refreshes on opening and after a
successful revoke, and offers an explicit Refresh action.

**Connect a device** in that panel issues a pairing code through
`POST /api/team/devices/pairings` and shows it once, with its expiry, until the
member dismisses it or the code ends. A team may carry an **access address**, the
https origin members open on their own devices (typically the tailnet front in
front of the server). It is operator-set in the installed server configuration
(`access_url` in `/etc/rcp/team.toml`, or `RCP_TEAM_ACCESS_URL` for a
source-run server) and read-only to members: `GET /api/team/space` returns it
with the team name, `PATCH /api/team/space` changes only `name`, and doctor
reports it as `team_access_url`. When the address is set, the issued code carries
`connect_url = <access_url>/#pair=<code>` and the card draws it as a QR code
beside the code; a phone that scans it lands on the login screen with the code
filled in. Without an address the card says how to set one. While the code is
visible the panel polls
`GET /api/team/devices/pairings/{pairing_id}`, whose `status` is `waiting`,
`consumed`, `expired`, `revoked`, or `locked`, and refreshes Devices on
`consumed`. A code is bound to the session that issued it: when that session is
revoked, logged out, expired, or removed by credential rotation, the code reads
`revoked` and cannot be redeemed. A member holds one live code: issuing another
withdraws the previous unused one. Codes are
ten characters from an alphabet without I, O, 0, or 1, shown as `ABCD-EFGHJK`,
expire after ten minutes, are single use, and lock after five wrong secrets like
enrollment codes; the server stores only the hash of the secret.

The unauthenticated team login boundary offers device pairing first: a **Device
code** field and a required **Name this device** field, submitted to the public
`POST /api/team/devices/pair`, which creates an ordinary session carrying that
label and sets the same cookie as exchange. A second mode, **Sign in with a team
token instead**, keeps the credential slip. The pairing route never sees or
returns the member token, needs no team-shell protocol declaration, and shares
the public-body size bound with enrollment and exchange. Its failures map to
401 (invalid), 409 (used), 410 (expired), and 429 (locked).

`POST /api/team/session/exchange` accepts an optional human-authored `label`
string of at most 80 characters. Omission stores `Unnamed device`; migration 14
also assigns that literal to existing sessions. The label is stored and rendered
as untrusted display text, without normalization or inference from request
fingerprints. Supplying a label remains optional for every supported native
protocol version. There is no rename route or label-entry screen in this change.

`GET /api/team/sessions` returns only the acting member's unexpired sessions.
Each entry exports `session_id`, `label`, `created_at`, `last_seen_at`, `expires_at`,
`is_current`, and `can_revoke`. The backend computes both decisions and reports
the current authenticated session as not revocable. Public identifiers are
independent random UUIDs, never session tokens, hashes, or derivatives of either.
Listing does not refresh other sessions' idle expiry.
The source-built desktop holds one session per saved connection. It keeps the
exchanged session's secret (the cookie value alone; Apple's Keychain tool keeps
only 128 prompt characters, so the whole Set-Cookie line does not survive) in
the Keychain beside the member token, rebuilds the cookie from it, verifies it
against `/api/identity` at launch, at Reconnect, and before each native request,
and exchanges a new session only when the server answers 401. One desktop is
therefore one row in Devices across launches. Forgetting the connection on the
desktop discards the saved session locally; its server row idles out or is
revoked from another device.

`POST /api/team/sessions/{session_id}/revoke` deletes that member's named session
and returns `{"ok": true}`. Unknown, expired, and other members' identifiers all
return the same 404; the current session returns 409 directing the member to
Logout. Other sessions and the member credential remain usable. Both routes
inherit team authentication and mutation-origin enforcement, and return 404 in
a personal space, whose identity panel has no Devices section.

Projects hidden by membership never appear as locked cards. Losing access
closes its open tab and returns to the index.

## Confirmed team desktop target

The first team client is the source-built desktop app. Its local project
index groups the personal space and saved team connections without making the
local backend an authority for any team project. Each connection stores
nonsecret routing metadata, its expected `space_id`, compatibility information,
and bounded last-known project cards. The permanent member token stays in the
operating system credential store and is absent from URLs, page storage, saved
connection JSON, logs, and Tauri command output.

**Add team space** first establishes the SSH tunnel and verifies the nonsecret
space identity. A new member enters a bootstrap/invitation code and display name;
an existing member may enter their permanent token. The controlled secret field
and IPC request are cleared after the one enrollment/storage operation. A newly
issued permanent token is captured by the native shell and written directly to
the credential store. No secret becomes local-backend state or cached connection
metadata.

The native shell uses the system SSH configuration and agent to hold a loopback
tunnel to the team server. Before establishing a browser session it checks
health and the expected `space_id`, then selects the highest overlap between its
compiled inclusive team-shell protocol range and the server's advertised range.
It sends that selected integer on enrollment, permanent-token exchange, and the
bounded project-card read and requires the server to echo it exactly before it
installs the HTTP-only cookie. A missing range, no overlap, or a missing or
different echo refuses the connection. The error names the observed desktop and
server source commits and tells the member which side to update or rebuild from
current `origin/main`; Git commit ordering and application semantic versions are
not compatibility protocols. A changed `space_id` likewise blocks mutations
until the human explicitly reconnects. An unavailable or incompatible team
connection leaves personal work usable and shows its cached cards as
unavailable.

The current desktop range is `[3, 4]` and server range is `[1, 4]`. The desktop
selects `4` with a current server, keeps protocol-3 connections, and refuses
servers below protocol 3 before enrollment or transfer. Updated servers still
accept older protocol-1/2/3 clients.
Protocol 1 keeps team
project cards non-deletable. Protocol 2 adds team deletion: cards may advertise
`can_delete=true` together with the exact `delete_confirmation`, and a team DELETE
is refused with the protocol-mismatch response unless the caller selected 2 or newer.
Protocol 3 preserves that contract and adds native transfer relay support for
optional reviewed `source_commit` fields and `rcp-transfer-v2` Git archives;
legacy omitted-commit requests and v1 archives remain accepted. Protocol 4 adds
the optional `record_schema_version=2` source-configuration field so episode
archives travel with operational history. Archive-free transfers retain the
previous configuration and record bytes. Older clients or targets that cannot
decode the extension refuse preparation before source release. A breaking
change adds a new immutable per-version contract before either end advertises
it. Narrowing a range is explicit retirement, not an automatic current-plus-
previous or time-based rule. The native handshake ends after
health/source/space identity, enrollment or token exchange, returned member
identity, bounded project cards, and HTTP-only browser-cookie installation. It
does not include server operations, provisioning policy, provider work, or the
ordinary server-served Web/API surface. Native transfer relay wire compatibility
is versioned here because the desktop, not the server-served Web app, sends it;
this is not an operator-capability or per-feature discovery registry.

Compatibility is negotiated live and is never durable connection authority.
Registry version 3 removes the shipped `minimum_shell_version` field through an
automatic version-2 migration while preserving connection identity, SSH target,
local origin, expected space, cached cards, operator route, and the independent
Keychain credential reference. Unknown registry versions or fields still fail
closed, except inside cached project cards. Cards are display data: the desktop
keeps each card's id, name, and attention count as the server sent them, ignores
other card fields, and drops cards to fit the registry size limit. Server text
never fails a connection. Sign-in responses likewise accept added fields; only
identities and protocol are checked.

Each space serves its own project index, so leaving a project returns to the
index of the space that project is in, by the same control and shortcut in
both. Leaving the space is a separate explicit action: the team index names the
active space and carries the one **Exit team space** control, which reloads the
local backend. The local index is still the only screen that shows more than
one space at a time; the identity record names the saved team spaces without
becoming a second way into them.

For a saved connection, the macOS shell launches `/usr/bin/ssh` directly with
argument-vector execution, batch authentication, no remote command or terminal,
exit-on-forward-failure, bounded connect/readiness timers, keepalives, disabled
control sharing/backgrounding, and one explicit
`127.0.0.1:<ephemeral>:127.0.0.1:<configured-server-port>` forward. It therefore
uses the member's existing SSH config and agent for host, key, proxy, and host
verification without accepting an interactive password prompt inside RCP. A
desktop-owned dual-stack loopback TLS listener presents the desktop identity at
the saved HTTPS origin and forwards plain bytes only to that private SSH
listener. One healthy connection is reused only while origin, SSH target, and
remote port still match; an ended, changed, or failed connection observes a
short backoff before replacement.

The team backend's mutation-origin check recognizes that one exact boundary: a
request received over the private HTTP side of the tunnel may carry the matching
generated `https://rcp-<connection-id>.rcp.localhost:<port>` origin. It does not
accept any other HTTP-to-HTTPS origin substitution. This keeps browser mutation
protection aligned with the desktop TLS terminator instead of rejecting the
desktop's own invitation and team-control requests.

Tunnel admission owns saved-row lookup and closes before removal, Quit, or
desktop update drains children. A failed lifecycle operation explicitly reopens
admission only when the app returns to service. A cleanup failure keeps the
unconfirmed child record for retry while its supervisor remains live and for
diagnostics otherwise, instead of forgetting ownership. The personal origin may
connect any saved row, while a team origin may reconnect only its own exact row.
A team page whose request never reaches its backend (the SSH tunnel ended, for
example across sleep) uses that right itself: one recovery at a time calls the
native Reconnect with a capped backoff until it succeeds, then reverifies,
never replaces, the accepted backend identity and reloads the active project or
project index, so the page recovers in place and a changed backend still stops it. None of these operations signal or restart the
remote RCP service.

Every saved space receives a stable, distinct loopback origin. Different ports
on the same `127.0.0.1` host are not isolation because cookies ignore ports; such
tunnels would collide on the shared `__Host-` session-cookie name. The shell
uses
`https://rcp-<connection-id-without-hyphens>.rcp.localhost:<local-port>`.
Navigation admits only exact origins derived from its validated saved-connection
registry. The desktop stores one versioned authenticated-encrypted
certificate/private-key file and keeps only its 32-byte sealing key in the
operating-system credential store. Source builds access that key through
Apple's signed Keychain tool with an ACL pinned to that tool, not an ad-hoc app
cdhash; the value never enters argv, URLs, page state, logs, or native command
output. The desktop pins the certificate in the live WKWebView navigation
delegate and never installs system-wide trust. A malformed, unauthenticated,
unknown-version, or partial identity/key pair fails startup rather than being
silently replaced. The current version-4 identity record stores its expiration,
uses a 365-day explicit non-CA leaf for `*.rcp.localhost` with TLS server-auth
and key-usage extensions, and rotates atomically during the final seven days.
Valid earlier identity records are reissued through the authenticated identity
owner, while the exact previously shipped `rcp-<id>.localhost` registry origin
migrates without changing the saved team connection or its member credential.
The macOS bundle makes the narrow ATS exception required for manual server-trust
evaluation only for `rcp.localhost` and its direct subdomains. This does not
permit HTTP application navigation: the proxy speaks TLS, navigation still
requires one exact saved HTTPS origin, and the native handler accepts only the
pinned leaf after hostname, validity, and server-use evaluation.
Each team's TLS listener closes any connection whose SNI is not that team's
alias before opening its upstream, so a shared wildcard leaf never routes one
team's host-bound cookie to another team's server.
The tool ACL solves source-rebuild stability; because a same-UID process can
invoke the same general-purpose Apple tool, it is not same-account read
isolation. That limitation is accepted under the current cooperative provider
model for source builds and for the unsigned prebuilt app alike: an unsigned
app has no stable signing identity to bind access to, and neither kind of build
is more exposed than the other. App-bound credential access is later work.
Team tokens use the versioned service
`app.researchcontrolpanel.rcp.team-member-token.source-v1` and a distinct
connection account. The immediately preceding D4 checkpoint never created a
saved team registry or a token in its unversioned pre-live namespace, so this
source-mode namespace break has no credential to migrate.
The Tauri capability covers the bounded hostname family, but the saved-origin
navigation check and certificate pin remain independent fences. The production
boundary and its real-WKWebView evidence are recorded in the
[local HTTPS decision](../decisions/2026-08-30-desktop-local-https-origins.md).

The ordinary browser can use the team server UI when transport already exists,
but it cannot own multi-space routing, credential storage, SSH tunnels, or
server-command execution, so it does not advertise the native **Add team space**
action. A saved connection that cannot establish a session stays visible with
its bounded cached cards, the native failure diagnostic, and a reconnect action;
it never becomes an apparently empty or local space. Source mode is the
supported client for this slice; a packaged Linux client is not required.

Project creation and transfer use one visible project wizard. Its three named
intents are **Use an existing checkout personally**, **Create a shared team
project**, and **Move an existing personal project to a team**. An entry point
may preselect an intent, and both the personal project card menu and Project
Settings deep-link to the move intent, but the user does not encounter separate
personal, provisioning, and transfer wizards. Each backend exports only its own
product eligibility, preselection, required fields, and any pinned source
identity. The desktop-native bridge
separately exports relay capability and its authenticated saved team targets.
The wizard offers move only by intersecting explicit permission from the
personal backend, explicit admission from the selected team backend, and that
native capability answer. A browser has no native capability answer and cannot
offer cross-space move. The Web does not infer product authority from
`space_kind`, paths, saved-connection presence alone, or native-global
detection.

The modes retain their separate authority owners behind that shared surface.
Personal setup calls the ordinary path-based preflight/finalizer. Team creation
creates a backend-owned durable provisioning request from GitHub repository
sources and derived central paths. Personal-to-team transfer creates linked
requests in the two authenticated backends and is available only in the
source-built desktop because its native shell owns the archive relay. A direct
team request to `/api/projects`, `/api/project-setup/preflight`,
`/api/project-setup/ssh-paths`, or `/api/project-setup/create` is refused before
request-body interpretation,
filesystem inspection, or catalog mutation. The separately validated
provisioning finalizer is the only team-project entrance into the existing
setup/registration owners.

The backend health projection preserves its existing identity and runtime
fields. `version` remains the full package `__version__` verbatim, and
`running_commit` keeps its existing meaning as the commit recorded for the
running installed process. It additionally publishes `build` as the integer
package build number or null for a source checkout, `commit` as the package
build's 7-to-40-character hexadecimal commit or null, and
`schema_ledger_head` as the newest applied storage-migration number read from
the data directory's ledger.

The health projection also carries one `project_creation` control with all three
intent identities, per-intent eligibility and preselection, primary action
label, required fields, pinned source identity when one exists, and an explicit
unavailable reason. The durable provisioning response similarly publishes the
status and check labels, exact next action, `can_run_setup`, `can_review`,
`can_cancel`, canonical repository URLs, intended and resolved paths, readiness
counts, structured operator action, safe CLI argv, and final-review binding. The
Web seals the complete provisioning and check-status vocabularies and consumes
those answers instead of rebuilding lifecycle policy from strings.

A provider-check projection also carries the nonsecret proof read back from the
server: resolved executable path, provider version, durable runtime id, observed
execution account, and check time. Those fields are present only for a ready
check; credentials and provider-home paths are never response fields. The Web
renders or relays this backend evidence and does not reproduce provider version,
model, runtime, authentication, or OS-account decisions.

The UI renders the backend's status, diagnostic, exact next action, resolved
paths, and final review. It cannot claim success from a desktop subprocess exit
code. A local-only codebase is not uploaded through the wizard: the new-team
intent tells the human to push it to a GitHub repository with a real commit
through their ordinary Git workflow, then records that repository source. RCP
does not collect GitHub user authentication.

A saved member connection and an operator route are distinct capabilities even
when they use the same SSH host. The source-built desktop stores the latter as
nonsecret native metadata: either an explicit direct `rcp@host` target or one
named operator target using `sudo -n -u rcp -H`. **Run setup now** appears only
after a native read-only probe proves that exact route can invoke the fixed `rcp
server project provision <request-id> --machine-readable` command. The shell
passes a validated request id as an argument and never executes arbitrary
command text returned by a server. It bounds the structured events, checks that
they come from the expected fixed command, and screens them for credentials. The
server owns their step order and text. Success comes only from an authenticated
durable request readback from the expected team space. If SSH or `sudo` needs interaction, the
app shows or opens the same fixed command in Terminal; it never collects a
private key or privilege password. The browser shows a copyable operator command
instead.

CLI structured progress is presentation input only. The CLI reports each state
change to the lock-owning backend through its private local control channel, and
the Web UI refreshes the durable request. Only the final explicit human review
may create or re-home the project. For personal-to-team transfer, one desktop
review action calls both already-authenticated backends in a fixed order: target
admission first, then source release. Each backend records its own human actor;
the native relay and remote CLI cannot provide either confirmation. A partial
first confirmation is durable state that the same request resumes, not evidence
that the project moved.

The native coordinator restores the exact saved team tunnel and member session
before every cold-resume read or transfer operation; Web code never reconstructs
that credentialed state. A relay command's nonzero exit or incomplete proof and
cleanup result remains a durable retryable failure and is shown as an error. It
may expose the explicit protected manual relay, but it never silently selects
that path or labels the native call successful.

Every machine-readable operator-action event carries the same structured
responsibility, typed machine or external-service target, ordered safe commands
or GitHub actions, nonsecret values, success check, and resume command that the
interactive CLI prints. The wizard renders those fields directly and never
parses CLI prose. No machine step or recovery instruction exists only in the
wizard.

## Project tabs

The project shell keeps a session-scoped dock beside the index control. Opening
a project appends and activates one tab; reopening activates without duplicating
or reordering. Inactive tabs shrink within the capped dock while the active one
retains more width. Tabs cannot be reordered.

Each tab retains bounded in-session view, panel, scroll, selection, draft, and
exact Runs-route state. Activating a tab is cache-only and never blocks on remote
I/O. Closing a tab changes no canonical state, task, draft, conversation, or
project data. Closing the active tab selects the right neighbor, otherwise the
left, and the last close returns to the index.

Open tabs survive hiding/reopening the same desktop window but reset on full
page reload or app quit. An inactive tab is not kept mounted merely because it
is open.

An explicit Runs route is authoritative over cached selection, including a route
with an absent or malformed branch identifier. Invalid branch identity resolves
to no selected Experiment rather than restoring a cached main-target selection.

## Browser-agent WebMCP surface

When the browser host supplies `document.modelContext.registerTool`, RCP
registers a page-scoped WebMCP surface over its existing application owners. A
ready project index exposes project listing and exact project navigation. A
loaded project replaces those tools with project overview and node inspection,
artifact/report listing and visual opening, conversation listing, inspection,
and Send, and bounded Experiment inspection, Start, and graceful Stop. Login,
project setup, loading, and invalid project states expose no tools; the project
surface waits for the same verified backend identity, actor, and team-session
state as the index, so a reconnect screen retires it.

The inventory follows current backend and browser state. Experiment Start and
Stop are registered only while at least one exact action can succeed or while
that action's accepted call is returning. Changing state updates stable tool
proxies without aborting an in-flight call; leaving the surface unregisters its
tools. Project navigation returns before the index registration is retired, so
the host does not mistake successful navigation for a stale tool failure.

Every call accepts exact ids returned by an RCP read tool and revalidates them
against the current page snapshot before acting. Read results are bounded JSON,
not generated summaries, and omit storage locators. Node inspection shortens
oversized saved text, lists, object entry counts, and key names to fit its budget
and names every shortened path, so exact content is never confused with
truncated content. Conversation listing
exposes the saved chat ids the page has loaded together with the backend total.
When a conversation's turns have aged out of the bounded task window the page
holds, inspection and Send read the exact task behind its latest transcript
message, so a conversation can continue only on its original graph target.
An ordinary branch conversation can use Discuss and Work from that branch's
workspace; a main workspace cannot resume its branch-bound session.
Artifact and report listing and opening use the recent task and episode windows
the page holds and report both window sizes; an exact `task_id`, task viewer id,
or `episode_id` outside those windows is fetched from the existing task or
episodes route rather than reported missing. Artifact opening uses the existing backend
viewer inside the page after confirming current availability.
Conversation Send starts one asynchronous ordinary Discuss or Work turn through
the same provider profile, native-session, skill, task-admission, and local or
SSH execution path as the visible composer; it returns the durable task id rather
than waiting for provider completion. Attachments and compute selection remain
visible-composer controls. Experiment Start and Stop likewise reuse the existing
backend projections and action owners, including staged-Sync, readiness, budget,
single-start, exact-episode, and graceful-Stop fences.

WebMCP is not a second API or authority plane. Calls run in the current
authenticated browser session and receive no capability that the corresponding
RCP surface lacks. There is no WebMCP tool for Proposal judgment, Decision choice,
graph editing or Sync, artifact retention or revision disposition, settings,
membership, project creation/deletion, or Auto-research authorization. Provider
answers, artifacts, and tool output still cannot become canonical graph truth;
only the ordinary typed Patch and human-authority paths can do so.

## Application surfaces

### Overview

Overview shows current project state and latest plain-language revision summary.
History names the canonical list **Project revisions**, attributes new records
from their stored snapshots, labels legacy records **Unattributed**, and derives
truthful operation fallbacks without inventing causality.

### Inbox

Inbox contains pending protected-belief Proposals, Decisions in `ready` or
`revisit`, and asserted open Blockers. A Proposal keeps inline judgment because
it is not a node. A Decision row opens the existing node-detail ballot. That
ballot marks the prior choice on the matching option, and shows it separately
when no option matches: an agent may reword a Decision's options but never
writes `selected_option`, so a reopened ballot would otherwise not say what is
being revisited. Accepted or contested open Blockers remain graph state but
leave human attention.
Historical Ambiguities never render or count.

### Research

Research presents question-centered paths and a bounded DAG. Research flow uses
one column per node type, ordered ResearchQuestion, Hypothesis, Decision, Blocker,
Experiment, then Evidence. All question depths share the ResearchQuestion column;
relations affect ordering within a column, never type placement. Columns start at
the same top row. Manual pins remain explicit position overrides.

The node detail is a persistent, resizable, viewport-clamped inspection window.
Its stable vertical one-hop relation map shows incoming neighbors, focus, and
outgoing neighbors without a nested scroll area. At most two comparison windows
remain open. Full-screen relation inspection does not navigate or add authoring
authority. Entering Agents closes node detail.

### Runs

Runs is the episode ledger. Its primary object is the durable Experiment-loop or
Auto-research episode parent, never an invocation, graph node, or Blocker. It has
three sections in order: **Needs Action**, **In progress**, then **Completed**.
A section count must be truthful, so Needs Action holds only runs that have
stopped advancing and stay stopped until a human acts; a run still moving on its
own belongs to In progress however slowly it moves, and completed and stopped
history goes below. Auto-research placement reads the generic episode
projection. Experiment-loop placement, health, and next step read the existing
`ExperimentControlState` for the owning Experiment; generic episode lifecycle
fields never override that specialized backend answer.

Needs Action and In progress are each one unfolded reverse-chronological card
list containing both episode modes. Completed groups episodes by mode in
foldable lists, ordered **Experiment loop** then **Auto-research**. Seed/Refresh and ordinary task history
remain in project History; Blocker judgment remains in Inbox.

Experiment and Auto-research parents each expose one backend-decided health and
one separately labelled **Recommended next step**. Health, recommendation, and
`blocked_reason` come from one exhaustive table in the episode projection,
evaluated in precedence order: an episode with an ending is never `active`; a
`wrapping_up` status or a pending or running wrap-up reads `wrapping_up`; an
exhausted or human-pause ending reads `needs_action` with
`blocked_reason=reauthorize`; a failed control task whose failure kind is a
revoked login reads `needs_action` with `blocked_reason=sign_in` beside its
recovery control; an Auto-research recovery that stopped because its reattempt
failed the same way again reads `needs_action` with
`blocked_reason=repeated_failure` beside a recovery control that offers a
changed provider, model, or reasoning. The recovery summary carries the
`failure_kind` that stopped it, so the projection separates a revoked login from
every other stopped recovery without re-reading the diagnostic. `blocked_reason` names the one human action that clears a
block and is `null` otherwise; the card renders it as one lead sentence before
the recommendation. `continues_episode_id`, `continued_by_episode_id`, and
`can_continue` publish the continuation chain, and `chain` lists every member
oldest first with its ceiling, turns used, ending, and report summary, so the
card never rebuilds a chain from the bounded episode list; the card shows a
chain as one run with each member's ceiling, ending, and report in sequence,
offers **Add N turns** only where `can_continue`, and the timeline spans the
chain with a `continued` boundary. The branch summary names the chain root as `episode_id` and the
newest member as `current_episode_id`; `merge_requires_end` is gone. A wrap-up state of `not_started` on a settled episode means
the ending had no report to generate and reads like a skipped report. A
wrap-up whose report account is signed out reads `wrapping_up` with
`blocked_reason=sign_in`.

Provider login state is published at `GET /api/providers/logins` (every
machine account, with the project machines that use it, a secret-free summary
of a stored credential, provider-owned labels and supported sign-in methods,
and any running sign-in) and inside each
project's readiness snapshot as `provider_logins` (the accounts that project
uses). While any account is `signed_out`, the project Runs view and the space
landing render one `ProviderLoginNotice` per account naming the provider,
machine, time, bounded diagnostic, and a **Verify sign-in** control, and point
at Settings for the sign-in; the Experiment board's `reauthenticate_provider`
copy points at it. Project Settings carries a **Provider logins** card
(`ProviderLogins`) for both space kinds with one row per account: state, who
changed it and when, **Sign in with device code** when `device_code` is supported
(the code and link render while `GET .../sign-in/{login_id}` is polled), a token
field and **Sign in** when `token_entry` is supported (the token is sent once
and never read back; saving it is the sign-in, because the server verifies it
with one real request before the account counts as signed in), **Verify
sign-in**, and **Sign out**. **Verify sign-in** is withheld while a pasted token
is unsent, and from an account that has saved no credential and offers no
sign-in method but `token_entry`, because there it can only fail. Unknown
interactions do not inherit another provider's form. The backend supplies the provider label,
token instructions, and safe credential metadata; React never selects login
behavior from a provider name. Generic provider routes reject unsupported
actions and unknown request fields. Status GET reads status only: verification
completion resumes eligible parked work through the shared account lifecycle
and existing recovery owners even when the member leaves Settings or closes
the page. Durable reconciliation repairs interruption before resumption without
duplicate launches. Every action is available to any signed-in member
and records that member. Task
status, phase, workers, and diagnostics remain supporting history rather than
competing primary states.
For a terminal Experiment episode, the owning node's human-authored closed status
is authoritative: the run is Completed and fresh-start control is absent until
the node is edited back to a nonterminal status. A control is absent unless
currently valid, and no recommendation names an unavailable action. A
recommendation follows the named cause of the latest failure, not only its
shape: a revoked provider login asks the human to sign in again rather than
offering a Retry that cannot succeed. A live episode whose latest turn failed
states that failure on the card face, where an ended episode states its ending
diagnostic; neither leaves the reason folded away in task details while the card
recommends acting on it. The card reads the backend's recommendation, never the
failure kind itself, which the response seals. Report
availability is separately backend-decided from the newest report-bearing
episode for that Experiment and exact graph target; a newer no-report episode
does not hide the durable report or change which episode owns it. The backend
publishes `report_is_current` alongside its owning episode id. Runs renders
**Previous episode report** when false and **Open report** when true, so an older
retrospective is not presented as the current episode's report.

Episode cards lead with the owning Experiment name or Auto-research identity;
their start time is secondary metadata and is never prefixed with a redundant
`Episode` label. A completed type group names the mode once rather than repeating
it on every card. Collapsed cards contain no muted recommendation or report
commentary. Each Experiment's backend control selects its one current
`episode_id`, so repeated work produces one card for that Experiment node. Older
episodes remain reachable through project History instead of appearing as
sibling Runs cards.

Each episode card and space run row shows a compact initials avatar and the
recorded human authorizer's name, labelled **Started by**. This is historical
episode attribution, including the inherited authorizer on an Auto-research
child; it does not claim live presence or enumerate contributors. Missing legacy
attribution never borrows the current viewer's identity.

Every unarchived episode offers **Archive**; an archived episode offers
**Unarchive**. The [episode archive](conversations-episodes-and-watchers.md#episode-archive)
is shared across the project. Archived episodes are absent from default Runs
cards, section counts, and nested child-Experiment links. **Show archived** adds
a separate **Archived** section without changing the active section counts.
An archived older Experiment episode remains available there with its own
identity, History entrance, and Unarchive control even after a newer episode
owns the Experiment's operational controls. Archives remain discoverable beyond
the recent-episode list limit and the space ledger's seven-day completed window.
Archive metadata on cached controls is refreshed from current storage before
being published; cached graph state cannot reverse an archive choice.

The episode index is an explicit typed projection whose current `episode` is
non-null. Main-target entries consume the completed project snapshot's
Experiment-control map; branch entries consume the exact branch read model.
Episode task rows publish durable actor `role` and lineage `depth`, and episode
cards consume those fields without interpreting persisted task requests.
The page keeps each project's episode list, so returning to a project tab shows
that list at once while it refreshes. A poll never overlaps a list request
already in flight for the same project; it waits for that request instead.
Project Runs refreshes this index while visible, so an Experiment dispatched on
an Auto-research graph branch appears as its own episode card even before anyone
opens its exact route. The project-scoped
`/api/projects/{project_id}/experiment-episodes` path restricts projection work
to that visible project. The same child appears once as a linked, subordinate
child actor on the owning Auto-research card's timeline. That actor is
navigational provenance, not a second lifecycle or budget: its label and status
consume the indexed node and control, while the child card retains its own
episode budget, transcript, and valid controls.

### Episode timeline

`GET /api/projects/{project_id}/episodes/{episode_id}/timeline` is a read-only
actor projection shared by Auto-research and Experiment run detail. It returns
`episode_id`, `mode`, `generated_at`, `truncated`, continuation-chain `members`,
and typed `actors`, `spans`, `handoffs`, `messages`, `signals`, and `marks`.
Actors carry stable identity, kind, label, row key, lifetime, outcome, recorded
starting span, and navigation links. Spans carry turn/attempt/report kind,
times, status, attempt and invocation numbers, nullable cause/error/headline,
and task and episode ids. Headlines are bounded first sentences from stored
answers; reports have no headline. The browser groups actors by `row_key` and
derives summary counts, relations, and per-turn wake details from this
single response, without a parallel event-list model.

Hand-offs join recorded admission commands to their starting span and worker or
Experiment actor. Messages retain sender and recipient, sent and delivered
spans and times, and one disposition: `wake`, `harvested`, `cleared`,
`failed_attempt`, `undelivered`, or `unknown`. Delivery records allocation,
never proof of reading. Signals contain inline notice or watcher payloads,
source actor and row, landing span/time and `woke`, `harvested`, or
`acknowledged` landing mode, plus recorded arming provenance. Graph watcher
sources name the node row, not an inferred episode. Lifecycle marks preserve
nullable issuing spans; missing provenance is never guessed.

Joins resolve across the full continuation chain before bounding the response.
The newest 400 spans, hand-offs, messages, signals, and marks are retained;
actors remain when a returned span or item references them. `truncated` means
summary counts cover shown items. Referenced actors or spans may be outside the
returned set; the chart places missing endpoints at the window edge. In
`experiment_loop` mode the roster contains the human, Experiment agent, and
shell watchers grouped by their row keys; retries and reports remain spans on
the agent row. Auto-research's graph watchers stay on its timeline; child shell
watchers stay on their Experiment timeline.

`GET /api/projects/{project_id}/episodes/{episode_id}/timeline/text/{text_ref}`
loads immutable full text on demand for `handoff:<command_id>` or
`message:<message_id>`. It returns `text_ref`, `kind` (`assignment`, `goal`, or
`message`), `owner_episode_id`, `body`, and `sha256`, checks existing project
membership and the requested continuation chain, and returns 404 for records
outside that chain. The roster response carries only bounded text previews.

The roster replaces the old Turns and Mail lists and keeps the message composer
beneath it. It links turn and attempt spans to the existing task inspector,
excludes reports from that navigation, and resolves child Experiment navigation
by episode id. Watcher controls remain with their existing owners. Layout,
selection, and gesture behavior follow the
[interface specification](interface-and-visual-design.md#auto-research-and-result-views).

An active child card names its current Experiment turn and links that row to the
ordinary task inspector. Until the turn finishes, the card labels the durable
objective separately from retained stale guidance. When the backend finds the
matching active Auto-research graph condition, the Experiment index publishes
`parent_watching`; the card explains that the owning episode watches the child
while the child's own **Watchers** fold contains only detached work handed off
by that Experiment.

Starting an Experiment navigates to its Runs detail rather than opening floating
chat. The detail separates historical episode budgets from **Next episode
limit**, shows watcher/session/host continuity, and omits semantic attempt
history from the node drawer. Stop, recovery, wrap-up, and report presentation
follow the episode specification.

An explicit main-target Experiment route binds only when both its `episode_id`
and graph target still match the loaded backend control. If the control advanced,
the route shows a History handoff without exposing the newer episode's transcript
or controls.

An Auto-research detail shows compact graph-branch identity, base/head, merge
state, and a persistent **Merge to main** control. A deliberate click checks
current server eligibility and either starts the merge or displays the blocker
beside the control, following the
[branch merge projection](auto-research-and-branch-merge.md#runs-projection).
**Open graph** selects the branch workspace explicitly. An exact branch
Experiment route may show its historical transcript through Runs without exposing an ordinary
composer for that episode-owned session. Ordinary chats started in the branch
workspace have their own sessions and authority. A main workspace cannot reuse
a branch-bound conversation or native session.

The space project index reuses these same backend lifecycle projections in a
summary ledger. It does not derive a second status machine from task or episode
fields. Its seven-day completed window is presentation-only; active and
actionable parents remain visible regardless of age, and project-scoped Runs and
History retain their existing complete records.

### Agents

Agents (route view `chats`) groups project and node conversations. Every human and assistant turn
keeps its immutable Discuss/Work label; progress stays inline under the triggering
message. There is no global task banner. The composer and history remain usable
while unrelated background tasks run.

The composer shows **Work in a worktree** before the first Work turn. The backend
projects eligibility and the reason a zero/multiple-repository or wrong-machine
scope cannot bind. A bound chat shows the real branch and path, an **Integrate**
menu with backend-resolved branch names and refusal reasons, and an explicit
**Remove worktree** confirmation with ahead and remote-branch evidence. These
controls dispatch the ordinary task API with a worktree choice or integration
choice; RCP supplies the integration instruction and target. Unsent drafts remain
intact when an integration turn is dispatched. A removed binding remains visible
and cannot silently become a shared-checkout chat.

`GET /api/projects/{project_id}/tasks` returns the newest tasks up to the list
limit, plus the latest turn of every chat whose latest turn is still running or
waiting on a person (queued, running, pausing, paused, failed, or interrupted),
up to `AGENT_TASK_LIST_OPEN_CHAT_LIMIT`. A chat that needs a human therefore
stays visible however many newer tasks exist; a failure followed by a later turn
in the same chat does not count. Such a latest turn also stays listed for
`AGENT_TASK_LIST_FINISHED_CHAT_SECONDS` after it finishes, so a client that saw
it running sees the terminal record and marks the result unread.

### Paper, Settings, and History

Paper owns human Markdown Write/Preview and read-only coaching. Settings owns
repositories, execution profiles, compute connections, packages, caches, project
membership, and prospective episode limits, not ontology authoring. Project
snapshots expose non-secret compute metadata; readiness exposes a backend-owned
execution-machine/connection matrix with distinct unreachable, authentication,
and host-key states. Normal readiness reads reuse the last result; only an
explicit refresh runs network probes, and a connection or execution-binding
change invalidates the cached matrix. Settings writes never accept private keys
or passwords.
History and task detail own
complete provider attempts, stages, events, diagnostics, package versions,
answers, graph outcomes, and recovery chains.

In a team space, Settings also reads one authenticated `/api/server-status`
projection. It carries backend-owned labels and presentation tones for the
running/current/managed/upstream release relationship, update readiness, the
latest backup attempt and latest independently retained protected-archive
receipt, protected and uncaptured project counts, completed-restore age,
installed machine-tool readiness, and private provider-check availability. The
browser formats timestamps, byte counts, and commit abbreviations only; it does
not reconstruct operational state from raw status vocabularies. An unsafe
concrete doctor, backup-receipt, or restore read fails visibly instead of
becoming an empty or healthy panel.

That route is GET-only and available only to an authenticated team member. It
does not configure or run backup, update, restore, Git credential preparation,
project provisioning, provider login/check, or member removal. It also does not
enumerate the console operations that do: an operator holds machine authority
already and reads `rcp server --help` on the machine, so restating that
catalogue in a member-visible panel adds a second place for it to drift. A
command still appears in the Web surface where one specific request needs it,
carrying that request's own identifier. D6's separately proved desktop operator
bridge remains the only native launcher and accepts only its fixed
project-provision command.

## Causal and relation presentation

Causal layout is a read-only derived projection from the same graph revision.
Feedback strongly connected components rank together; layout never generates a
graph action or breaks a cycle by changing truth.

Evidence node detail presents observation, interpretation, role, validity,
origin, provenance, and artifacts. The Hypothesis relation/detail surface owns
each claim-relative direction, relevance, weight, scope, and qualifications.
Historical global strength is clearly legacy and never shown as current edge
weight.

Graph-writing agents add or revise glossary terms through `upsert_glossary`
Patches. Canonical definitions render inline; there is no standalone Glossary
view or human glossary editor.

## Desktop shell

The desktop window is a client of backend-owned durable work. Closing or hiding
the window never cancels a task. Reopening attaches to the healthy owner and
current app state.

A source-mode frontend rebuild preserves content-hashed assets from the prior
build so an already-open window can keep lazy-loading its coherent bundle until
the researcher reopens it. Packaging and server startup use a clean build. If a
chunk is nevertheless unavailable, the client performs one bounded document
reload; a repeated failure renders an explicit reload action instead of a blank
window or reload loop.

App Quit gracefully asks only the backend process this shell owns to pause
recoverable work and shut down. It never kills a reused backend or unrelated
process. If graceful timeout is exhausted, the shell reports the forced path
truthfully. Singleton replacement and frontend build ownership stay in the
launcher, not manual PID cleanup.

Preview links open the shell's secondary bounded window rather than navigating
the main project WebView. Desktop repository links and result/report artifacts
therefore cannot strand the main project window. Native downloads resolve
through shell-controlled destinations.

In personal project setup, every local repository path has a native folder
action in the desktop shell. Selecting a folder fills its absolute path;
cancelling preserves the current value. An SSH repository keeps its manual
absolute-path field and also offers a backend-owned bounded browser in both Web
and desktop. The browser uses only SSH credentials already configured on the
machine running RCP, opens at the authenticated remote user's home, and lists
one directory level per request without recursive discovery. It labels direct
children that contain `.git` or `.research`. An authentication or host-key
failure names the exact RCP machine where ordinary SSH state must be repaired;
RCP never accepts or stores a password, private key, or credential path. Team
project provisioning continues to use server-managed checkout paths instead of
this personal path browser. Every SSH destination is centrally rejected before
OpenSSH when it is empty, option-shaped, or contains unsupported characters.
Editing the repository location, host, or path aborts and invalidates an
in-flight browse request, so a late response cannot replace the new target.
Strict host-key browser calls use a direct OpenSSH transport with connection
sharing disabled, so an existing multiplexed master cannot bypass the check.

The desktop may add shell-only dictation, update, reconnection, and packaging
behavior only where a native test owns it. Browser verification
does not stand in for native window lifecycle.

A local Codex thread created through RCP's app-server runtime is stored by Codex
and may therefore appear in the Codex Desktop task list. RCP uses that as an
inspection surface only. Sidebar ordering, loading, takeover, and concurrency
remain Codex Desktop behavior rather than RCP product state.

### Update notice

`GET /api/update-notice` returns the cached release check: space, status
(`update_available`, `current`, `pinned`, `unchecked`, `failed`, `off`,
`unknown`), current and latest versions, check times, companion readiness, a
locally built download URL, and the update command. The one update surface,
shown on the project index, setup screens, and every project view, renders it:
a team space shows `sudo rcp server update`; a source checkout shows
`scripts/update-from-source vX.Y.Z` (with `--desktop` from a source app); a
prebuilt app shows a Download button only once the companion is confirmed.
The native shell reports its build kind, version, and checkout through
`desktop_build_identity`, because a desktop may reuse a backend of the other
kind. A visible page polls the endpoint (30 s while `unchecked`, then 10 min,
and on becoming visible); dismissal is per release. A protocol mismatch names
the confirmed download, the releases page when the check is unavailable, or the
update script for a source build.

## Frontend trust boundary

Provider naming is a backend answer. Readiness exports each provider's runtime
choices and its default, and a task and a Paper writing session each export the
label for the runtime they ran on, so no surface maps a durable runtime id or
picks a default itself.

The browser may stage human drafts and render backend projections; it is not the
owner of authority, tasks, graph rules, provider authentication, watcher
delivery, or canonical state. Provider implementations own authentication
mechanics for the execution account; the shared account lifecycle owns durable
state and recovery. Client-generated ids,
cached target selection, URL fragments, artifact messages, and provider output
cannot select a different project, conversation, branch, authorizer, or graph
target.

## Provider sign-in resume response

Verified sign-in, token save, and successful device sign-in retain
`resumed`, now `{ "checked": N }`. This is a coarse count of episodes inspected
by the ordinary periodic reconciliation pass, plus queued tasks and completed
watcher groups checked for the verified account. It is not a launch count:
already-settled episodes and inputs still waiting on other conditions may be
included. The web reports items rechecked for resumption.
