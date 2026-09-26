# Server and machine operations

This specification owns the installed team server: its confirmed deployment
target, machine authority boundary, version and update lifecycle, central
checkouts and repository credentials, durable project provisioning,
personal-to-team transfer, and backup and restore.

Durable space and project identity, enrollment, membership, and project homes
are in [Projects, spaces, and operations](projects-spaces-and-operations.md).
The operator's terminal procedure is [`docs/server.md`](../server.md), which is
a guide and never overrides this file.

## Confirmed first team-server target

The first supported team deployment is deliberately narrow: one lab, one Linux
server, one team space, and source-built desktop clients. The server runs a verified promoted wheel with a hashed dependency lock and
prebuilt Web bundle under a non-reloading system service. The independent
supervisor selects releases and recovers interrupted deployment before startup. A dedicated Linux `rcp` account owns its
private home, data directory, runtime files, and server-local team checkouts.
An explicitly configured remote execution account owns a team-controlled
checkout on its SSH machine. Ordinary members do not share those identities and
their personal checkouts remain theirs.

The `rcp` account has fixed home `/home/rcp`, a real `/bin/bash` shell, and no
usable password. Its Ubuntu shadow entry uses an unusable non-locking value such
as `*NP*`, not a leading `!` account lock that OpenSSH may reject before public
key authentication. This supports native provider login through
`sudo -u rcp -H` and the explicitly allowed direct-key SSH route without turning
the service account into a human identity. Installation does not enable
password SSH or edit global `sshd_config`. Direct `rcp@server` access exists only
if the operator deliberately installs a public key; the preferred alternative
is a named operator account with the narrow sudo command. `rcp` has no general
sudo or supplemental privileged group membership.

Supported servers are Ubuntu 22.04 LTS and Ubuntu 24.04 LTS on x86-64 with
systemd. CI builds Web assets with Node.js 24; installed servers need no Node.js
or npm. Application Python 3.12 is managed through `uv`; Git, OpenSSH, system-wide `uv`, and the upstream `age`
CLI in the range `>=1.0.0,<2.0.0` are prerequisites. Installation validates
those system tools but does not install general OS software or modify apt
repositories. After creating the service account, it uses system-wide `uv` as
`rcp` to install and revalidate that account's managed Python 3.12 before any
release installation. The operator does not provision files inside a
not-yet-existing account. The operator guide supplies tested prerequisite
commands for both Ubuntu releases.
Install runs `loginctl enable-linger <account>` after converging the service
account and verifies `loginctl show-user <account> --property=Linger`; command
failure or a value other than `Linger=yes` fails installation. Doctor reports a
problem when the service account is not lingering, so an installation from
before this rule converges by rerunning install.
Other Linux distributions and architectures remain unverified.

Ordinary service-owned content is grouped below `/home/rcp/rcp-server/`: the
isolated per-build releases, application data, server-local central project
checkouts and project keys, and service-owned checkpoint payloads. Root owns
`/etc/rcp/supervisor/`: its separate runtime, selected-release receipt, private
operation and adoption journals, restore preparation receipts, and bounded logs.
Provider-native state stays in each provider's normal per-account home path
(currently `/home/rcp/.codex` and `/home/rcp/.claude`), and SSH state stays in
`/home/rcp/.ssh`; RCP does not relocate provider credentials. The one credential
RCP itself keeps is the Claude setup token, under the application data
directory at `providers/claude/<account>/setup-token` (0700 directory, 0600
file, excluded from protected backups). RCP records each machine account's login
state from real provider results, refuses new provider work while an account is
signed out, and signs an account in, verifies it with one real request, and
signs it out from the product, as any member, per the
[provider logins decision](../decisions/2026-09-14-provider-logins-are-kept-alive.md).
The root-entered `server provider update <codex|claude>` command is a bounded
operator wrapper around the provider's native update under `rcp`; it does not
take ownership of provider releases or credentials and never reads the login. The installed
service and root-to-service subprocess environment put `/home/rcp/.local/bin`
first so a provider's account-local installation wins over a stale system-wide
copy. Provider discovery persists that stable command path rather than resolving
a provider-managed symlink to one versioned target. RCP runs the Codex installer
in its supported noninteractive mode: the installer never launches Codex or asks
the operator to decide what to do with an older package-manager installation.
RCP verifies the selected executable and existing login as its separate final
step.

Only root/system integration lives elsewhere: `/etc/rcp/server.toml`, the
root-only `/etc/rcp/backup-recovery.agekey`, its root-owned nonsecret `.pub`
recipient sidecar, the root-owned current-release pointer,
`/run/rcp/control.sock`, the stable CLI wrapper, systemd units, and journald.
Backup destination remains explicitly configurable and may live outside this
layout.

The installed config carries one immutable random nonsecret `installation_id`.
New installations need no RCP source deploy key. Legacy archive labels
`rcp-source:<installation-id>` remain recognized for explicit authority review;
new backups do not emit them.
This machine-installation identity is distinct from the durable team `space_id`
and from every human member.

The server binds only loopback. A desktop member reaches it through an SSH
tunnel, then uses RCP membership and a browser session for product authority.
The SSH account that transports a desktop connection is not thereby an RCP
member or a server operator. Direct public HTTPS, a Linux desktop package,
containers, hosted RCP, high availability, and multi-server failover are outside
this slice.

Operator documentation shows both supported console routes. A deliberate public
key may grant direct `rcp@server` access, or root may install a
`visudo`-validated narrow rule for one named operator to run only the documented
service-account command family through `sudo -n -u rcp -H`. RCP neither infers
that named account nor silently edits sudo policy. The latter route is preferred
because its machine access can be audited and revoked independently.

These identities and credentials must never be collapsed:

- the RCP member identifies and authorizes Z, Alice, or another human;
- the Linux `rcp` account owns the service and server-local team files, while an
  explicit remote execution account owns its remote team files;
- an OpenSSH credential authenticates only its configured desktop-to-server or
  server-to-remote machine route;
- a repository-scoped Git deploy key authenticates one central repository
  checkout; and
- the provider login belongs to the operating-system account that actually runs
  that provider, locally or through SSH.

### Release check and update notices

`rcp serve` owns one release-check poller in its lifespan (`release_check.py`).
Shortly after startup and every 6 hours it reads GitHub's latest published
stable `vX.Y.Z` release with bounded, GitHub-only transport; whenever that
release is newer it also confirms the `desktop-vX.Y.Z` companion (published,
same commit, zip and checksum uploaded). Routes read only the cache. A team
space compares the installed release from the selected receipt, reports
`pinned` for a pinned server, and never lets a failed check change the doctor's
install-integrity `source_state`; `rcp server doctor` makes one live lookup of
its own. `RCP_UPDATE_CHECK=off` disables every call. Requests carry no project
data, credentials, or install identifier. A source `rcp serve` holds a shared
lock on `<checkout>/.rcp-serve.lock`, which `scripts/update-from-source` takes
exclusively before it checks out a release and rebuilds, restoring the start
revision and its build if a step fails.

## Machine authority and the operator surface

RCP defines no administrator member role. Installation, backup, restore, release
update, machine credential provisioning, and removing another human belong to
whoever has operating-system authority on the server. Provider authentication
stays entirely provider-native under the execution account; RCP only checks its
readiness. A member token cannot perform the machine operations.

The confirmed machine surface is a narrow `rcp server ...` CLI. It includes
installation, `doctor`, provider readiness checking, project provisioning,
backup configuration and capture, restore, member removal, release update, and supervisor update.
The same command implementation emits either interactive terminal guidance or
structured progress for the desktop shell. RCP does not add CLI mirrors of
ordinary graph, task, chat, or project-member actions.

### Compute backend probe

`rcp server compute probe --project <project_id> <machine_alias> --route <scheduler|helper>` uses the
installed-service control socket, entered as the service account, to run
`probe_compute_backend` against the registered project manifest and store the
`ComputeBackendProbe`, returned inside `ServerControlComputeProbeResult` with
service, project, machine, and route identity. It prints the route, status label,
backend id, containment, diagnostic, and any required action. It exits 0 only
when the requested route is ready, and 1 otherwise.
The probe executes inside the running service. Generic helper readiness checks
local cgroup separation against the server itself. The scheduler route checks
the configured job manager. Slurm checks tool availability and queue access
through the execution account's bounded login shell, without submitting a job or changing
scheduler configuration. Slurm validates permission and resources when the agent
submits its actual command. The diagnostic names missing prerequisites and asks
an administrator to repair them. This is the only compute CLI verb.

### Package identity and offline storage migration

Two top-level commands expose the release and storage contract without starting
a server. `rcp --version` requires no subcommand and prints one line containing
the full package version, build number, and build commit. A source checkout has
no build identity and reports `build none commit none`; a release version such
as `0.3.2+build.412.gfe06636` reports `build 412 commit fe06636`. The full
version remains the package's verbatim `__version__`; its base version is the
part before the first `+`. With `--machine-readable`, the command emits one JSON
event in the existing machine-operation event shape carrying `version`,
`base_version`, `build`, and `commit`. Because the event's nonsecret field type
does not admit null, a missing build or commit is the string `none`; the
equivalent fields in `/api/health` are JSON null.

`rcp migrate [--data-dir PATH] [--machine-readable]` and `rcp migrate --check`
resolve their data directory exactly as `rcp serve` does. Both acquire that
directory's exclusive instance lock before inspecting or changing the database.
If a running server or another process owns the directory, the command fails
nonzero with a plain message and leaves the database unchanged. It never skips
the lock, migrates under a running server, or falls back to a copy.

`rcp migrate --check` is read-only. It does not create a missing database, apply
a migration to the target, or change existing database or WAL bytes. It opens
the live database in SQLite read-only mode so every committed WAL transaction is
included; SQLite may create or touch its normal sidecars while reading. The
command reports the applied ledger head, registry head, and ordered pending
migration names, and distinguishes these exit-zero results:

- **fresh**: no database file exists; the next ordinary open will construct the
  current schema;
- **current**: the ledger head equals the registry head, there are no pending
  migrations, and read-only validation passes; and
- **pending**: the ledger is behind and every pending migration is a known
  registry entry. Recognized frozen pre-ledger server boundaries are classified
  as this known-pending state rather than being modified during inspection.

Exit `2` means the state is unknown and unsafe to migrate: the ledger names an
unknown migration, its head is ahead of this RCP's registry, read-only validation
fails, an otherwise nonempty unrecognized database has no ledger table, or the
file is not valid SQLite. These results are distinct from the nonzero
instance-lock refusal.

`rcp migrate` first performs that read-only classification and refuses an
unknown database with exit `2` and the same plain message, without changing it.
For a fresh, current, or known-pending state it opens the store normally, applies
the ordered ledger, runs the storage validator, reports the resulting ledger
head, and exits `0`. It never serves the application. With
`--machine-readable`, either migration form emits the same events as its human
output in the existing JSON event shape, and the last record carries the exit
outcome.

There is deliberately no uninstall operation. Install converges instead of
stacking, so a failed install is corrected and rerun, and every refusal names
its cause. Teardown is therefore an ordinary operating-system sequence, complete
because `ServerLayout` keeps the whole footprint inside four locations plus the
account:

```bash
sudo systemctl disable --now rcp.service rcp-backup.timer
sudo rm -f /etc/systemd/system/rcp.service \
  /etc/systemd/system/rcp-backup.service /etc/systemd/system/rcp-backup.timer
sudo systemctl daemon-reload
sudo rm -rf /etc/rcp /usr/local/bin/rcp /usr/local/bin/rcp-supervisor
sudo userdel -r rcp
```

`/run/rcp` is a systemd `RuntimeDirectory` and disappears when the service
stops. Skip the backup units when no backup timer was configured. Removing
`/etc/rcp` also destroys the server-managed recovery identity at
`/etc/rcp/backup-recovery.agekey`, the only key that decrypts archives made with
it. When backups use that default identity, copy the file to protected storage
off the host before this step, or accept that every retained archive becomes
permanently undecryptable; no later install recreates it. The last command
takes `/home/rcp` with it, which is where the team space, project checkouts, and
deploy keys live; deploy keys stay registered with GitHub until they are revoked
there.

Interactive TTY output is a continuous, plain-language wizard. The CLI validates
the complete operation plan before doing work, but normal output does not dump
that internal plan or append a running/succeeded block for every step. It keeps
one colored current-step line, replaces that line as work advances, captures
bounded subprocess output, and expands only the final result or a stop that
needs attention. Redirected terminal output remains readable bounded status
lines; `--machine-readable` remains the complete append-only JSON event record.

A human stop names the typed machine or external-service target, responsible
authority, nonsecret values, ordered safe actions, plain success signal, and
exact continue command. It is titled for the human's own task rather than for
the machine check it interrupted, so a pause may replace its planned title and
purpose; everything else that identifies the step stays pinned to the plan. A
displayed command may also name the shell it belongs to, which is not the
machine the operation acts on: a local machine target carries the service
account while the operator works from their own login and the command elevates
itself. That context is optional, because the separately versioned supervisor
emits its own steps and a pause stored before it existed must still decode; a
command without it displays as it always did. A renderer that knows how the
operator reached that shell, as the desktop knows its saved operator route,
shows the way in beside the command rather than folding it into the same
string. In an interactive terminal, Enter runs the declared
command actions and exact re-entry command inside the same wizard; `q`, EOF, or
a closed terminal pauses safely and leaves that continue command usable later.
The one-time team enrollment code gets a second explicit save confirmation
before activation continues. Machine-readable mode never prompts or executes
an action. Secret values never enter either renderer.

A failure is also a usable breakpoint, not a raw subprocess dump. It retains the
old serving state, names the bounded cause and safe state fields, gives explicit
recovery guidance, gives an exact `--machine-readable` diagnostic rerun when the
operation is convergent, and prints the normal continue command. Candidate
rehearsal failure additionally names the exact retained result and capture,
prints a bounded inspection command, and names only the exact paths eligible for
cleanup before retry. The operator never reconstructs a command from prose.

After authenticating the private socket peer and response request, instance and
protocol identity, the supervisor preserves a valid refusal's bounded code and
redacted message in its operation record and CLI events. A refusal does not need
success-only result fields. Malformed or unauthenticated responses cannot supply
operator text. Fenced probe readiness failures retain the last bounded, redacted
error and the private probe log reference. A recovery failure reports the original
deployment cause alongside the recovery cause.

Privilege is fixed per command rather than inferred from what happens to work on
one machine. `install`, `backup configure`, `restore`, and `update` enter through
a narrow root coordinator because they change accounts, `/etc`, systemd, or
stopped-service state; the coordinator drops to `rcp` for application installation
and data work. Privileged retained console owners run from a separate root-owned
operator environment pinned to the selected build; root never executes the
service-owned application environment. `doctor`, `provider check`, `project provision`,
`project transfer-import`, `backup run`, and `member remove` execute as `rcp`,
either through direct service-account SSH or a narrow operator sudo rule. A
wrong calling identity fails before durable work, and root's home or credentials
never become provider/Git/build state.

Fresh installation begins with the exact two wheels from one promoted release,
using the paired-wheel `uv tool run` command in the operator guide. That trusted
bootstrap converges the fixed account, prerequisite checks, private paths,
backup identity, and root-owned supervisor integration before delegation. It
never builds or fetches an RCP source checkout. The supervisor fetches only the
followed stable release or configured explicit stable tag, verifies the complete
five-asset bundle, and installs the application as `rcp` using its hashed lock.
Application release preparation sets umask `077` itself and restores the caller's
mask on success or failure; it does not depend on entry through the installed
shell wrapper. Prepared-runtime ownership and mode checks still fail closed.
Interrupted preparations retain their exact directories and diagnostics. A
sealed installed build may be reused only with the same origin-bound identity.
The supervisor and privileged operator console use separate root-owned runtimes
and root-owned managed Python, independent of the service account's Python.

For a fresh data directory, install leaves the unit stopped and disabled, then
offers the exact `sudo -u rcp -H /usr/local/bin/rcp space init --team --name ...`
action. In the normal interactive flow, Enter runs it, the operator saves the
one-time code, and a second Enter re-enters install so the same wizard enables,
starts, and reads back the service. If the terminal is closed or the operator
chooses `q`, the exact `sudo /usr/local/bin/rcp server install --team-name ...`
continue command remains printed and independently usable. The wrapper resolves
the installed `RCP_DATA_DIR`. Re-running install against an already initialized
owned team space converges the service to running.
Before showing that one-time code, team initialization restricts `rcp.sqlite3`
to owner-only mode; recovery of an interrupted unclaimed initialization repeats
that restriction, and resumed installation refuses a wider database mode.

When the service is running, a server command that needs durable RCP state uses a
private machine-local control socket owned by `rcp`; it never opens SQLite beside
the lock-owning process. Installation and restore may open the data directory
only while they prove the service is stopped and acquire the normal ownership
lock. No member HTTP route exposes this machine authority.

The versioned control probe advertises its exact operation set. `server doctor`
reports provider checking as available only when the running service advertises
both provider-plan and provider-check operations; a healthy socket that omits
them is an installation problem. `server provider check` resolves only one
durable request or existing team project through that service, shows the full
plan before probing, and returns the same bounded success, failure, or operator
action in interactive and machine-readable modes. `server provider update` is
entered as root, runs only the selected provider's supported updater as `rcp`,
and then proves the updated executable, version, and native authentication. It
prints the exact provider-login recovery command when the update succeeds but
authentication does not; it never receives a token or login code itself.

`member remove` previews the target's active work, project memberships, tokens,
sessions, and pending invitations before confirmation. It refuses to remove the
last active member who has completed enrollment: a pending invitation or a
preprovisioned name is not yet a person who can invite the lab's next member.
It also refuses while the target is the only active member of any project and
names those projects; an existing project member must add another enrolled
member through the ordinary product flow first. Machine authority never assigns
project membership merely to make removal pass.
On confirmation one transaction marks removal in progress, revokes tokens and
sessions, revokes unconsumed space invitations they authored and pending project
invitations they authored or received, and removes active project memberships.
Invitation revocation is recorded distinctly from an invitee decline.
Identity/admission checks reject the member immediately.
The immutable user row and name remain as a tombstone for historical
attribution. Existing graceful task/episode owners then stop live authorized
work; an in-flight provider turn may settle but Apply rechecks membership. Only
after no live work remains does the operation mark the member removed. Startup
and CLI re-entry resume a crash-interrupted removal from its durable fence rather
than restoring access or forgetting to stop work. This guard avoids stranding
the space without inventing an administrator rank.

The same last-member rule applies to self-service credential revocation: RCP
refuses to revoke the sole live permanent token of the last active enrolled
member, and also refuses when that member is the only member of any project who
can still authenticate. Atomic token rotation remains available because it
returns a replacement before invalidating the old token. This slice does not let a machine operator
mint or impersonate a member credential; with the required two-member lab,
ordinary loss recovery is re-invitation by the other enrolled member.

## Release selection, deployment, and automatic recovery

The separately versioned `supervisor/` distribution imports no RCP modules and
has no runtime dependencies. Its low-level `fetch`, `verify`, and unprivileged
`install` commands prepare bundles. Installed `rcp server install`, `update`,
`restore`, and `supervisor update` delegate to it using the existing versioned
operator event envelope. `--plan` is side-effect-free. The private CLI socket
and all non-deployment machine operations retain their concrete application
owners.

Installed config schema 3 has `[release] followed = "stable"` and an optional
explicit `pin = "vX.Y.Z"`. The optional team address is a separate document,
`/etc/rcp/team.toml` (`access_url = "https://…"`, same root:rcp 0640 rules),
so the strict schema-3 file never grows a field a pinned older release would
reject; it names the one https origin members' own devices open, is
operator-set and read-only to members through the team API, and doctor reports
it as `team_access_url`, naming the file as a problem when it is unreadable or
invalid. Stable is the newest non-prerelease GitHub Release;
prereleases, missing assets, unsupported selectors, altered hashes, and
inconsistent wheel/manifest identities refuse without choosing another source.
The release metadata binds the full commit to the wheel's short commit suffix.
A root-owned selected receipt binds tag, complete wheel version, build, full
commit, manifest SHA-256, release directory, and bundled supervisor version.
The root-owned current pointer must agree with it before application launch.

`server update` displays an exact `vX.Y.Z:manifest-sha256` target for operator
confirmation. Preparation uses a new isolated service-owned release directory;
no failed preparation overwrites an existing directory. A newer required
supervisor version must be installed first through `server supervisor update`.
That command validates a separate root-owned runtime and atomically switches its
pointer under the same operation lock, without rolling back application data.

### Application boundary and local checkpoint

A normal deployment takes a protected backup before closing admission. An
incomplete or unreadable backup does not refuse the update: rollback uses the
stopped whole-root snapshot, and the result reports the backup's causes as a
`backup_warning` field. Root authenticates the maintenance RPC to the actual service
PID, account, instance, and data-directory identity. The application closes new
mutations, provider launches, watchers, machine operations, and runtime recovery
owners, drains entered work (running agent turns get up to two hours to
finish; the update refuses cleanly after that), then returns a SQLite capture bound to that
quiescent boundary. The candidate's thin `inventory` command projects the roots
from backup's captured registration receipt using `_project_restore_location`,
shared with preparation; it does not reread SQLite or parse manifests separately.
Before service stop, supervisor `check-space` reports an advisory estimate of
allocated bytes and inodes against free space on each destination filesystem,
with one margin. Copy and sync errors, rather than a size or entry ceiling,
determine whether capture succeeds. Copying has no fixed elapsed-time deadline;
cancellation still terminates and reaps owned children.
Root stops the service and proves its main PID is gone. The supervisor then
copies the complete data root and registered local canonical `.research` roots.
Nested roots collapse into their containing root. Candidate preparation declares
its replacement roots, and the supervisor checks that the stopped snapshot
covers them before activation. Preparation uses the candidate's compatible
application code and captured SQLite data, so the previous installed release's
scratch rules cannot block the update. Its typed proof payload is validation
input, never rollback authority.

Whole-root capture includes credentials, jobs, cursors, unknown files and empty
directories. No entry inventory, hashes, filename, type, permission or symlink
policy filters the stopped copy. Provider homes, source checkouts and remote canonical roots remain outside replacement scope. An update
runs in two stages: before the release commits it touches only local state, which
rollback restores; the live check compares a remote project's local display cache
when current and otherwise leaves it unopened, since validation already replayed
its captured history on copies. A remote project is opened only after the release
is chosen, where no rollback applies. Kept artifacts
and result views outside replacement roots retain their typed checks.
An intact startup-effect fence prevents probation from changing external state.

Offline validation exercises real API projections, main and branch replay,
merge receipts, retained task/stage paths, imported histories, and startup
recovery inventory. `migrate --check` alone is insufficient. Candidate validation
produces an exact application-owned proof. After rollback, the previous binary
runs its own fenced startup check without parsing a newer proof schema. The
supervisor handles proof digests and opaque filesystem snapshots.
A candidate changes the graph projection through model-derived defaults and
explicit migrations. It verifies the retained baseline graph against its recorded
digest, then removes the retired
`coverage` report and fills absent deterministic defaults by walking the real
graph model, its discriminated variants, and nested records. Constant defaults,
built-in empty container factories, and model factories composed of these defaults are
safe; arbitrary factories are never executed to guess at determinism. Existing
values, unknown keys and stored edge layers remain untouched. A field with its own
serializer, such as stored Proposal and Patch operations, keeps only what its author
set, so the walk leaves it exactly as stored. All remaining graph
content and startup recovery reads must still match; the candidate proof records
the current graph digest used by live verification. `upgrade_graph_projection`
also upgrades the project display cache on load, because live verification reads
that cache and it must equal a fresh replay. A cache whose revision trails the
proof, as a failed refresh leaves it, is rebuilt from canonical history instead.
The retained baseline graph shares the display snapshot's size bound. One
recursive test covers every reachable model with explicit serialized examples,
including populated optional, list and map fields, and independently omits every
defaulted field outside serializer-owned fields to check restoration; a fresh
serialization whose stored operations omit defaults must come back unchanged, and
the installed-upgrade seed carries a pending Proposal. It checks idempotence and preservation of
explicit values and stored edge layers. New fields or types without an example
fail the invariant; unproven default factories (including UUIDs and timestamps)
fail with the field names and require a human-authored explicit migration.

The old-data upgrade CI gate checks every published, non-draft, non-prerelease
`v*` GitHub release, with separate current-cache and stale-cache cases for each
tag. CI and test collection share `gh release list` discovery, increasing its
request limit until the catalog is exhausted. Missing tags or failed discovery
fail the gate rather than skip sources. Frozen schema-era fixtures and the exact
candidate-base check remain. No supported source floor has been declared; that
decision remains open.

The installed upgrade gate uses the same release catalog in a job
matrix on pristine GitHub-hosted Ubuntu runners. It downloads each source's
promoted application and supervisor wheels, verifies the bundle and commit,
and installs them with the production machine/bootstrap owners. It initializes
a team through the installed CLI, enrolls a member and records work over HTTP,
and uses the historical application's project owners to seed populated main
and empty branch canonical histories, retained tasks and attachments. Provider/Git provisioning
receipts are synthetic; no paid agent or external repository is needed.
Real offline tools create agent scratch: a uv environment and locally built
package installed with hardlinks, a committed Git repository, FIFOs, a socket
node, unreadable entries, dangling links, empty directories and sparse content.
The installed service account also leaves group-writable bytecode in its managed
Python, terminal scratch, provider credentials, jobs and cursors.

The gate invokes the installed `rcp server supervisor update` and `rcp server
update` wrappers. A test-only, root-owned supervisor startup hook substitutes the
unpublished candidate's verified local bundle for network release selection and
moves probation to port 18421; a systemd drop-in uses the same port. All ownership,
installation, maintenance RPC, stopping, snapshotting, validation, live checking,
selection and service startup paths remain production code. After candidate
verification the hook injects a failure and compares the restored stopped roots
before old code starts: paths, types, bytes, modes, ownership, modification times,
xattrs, link targets and hardlink groups. It then requires old-code HTTP service,
usable scratch and a complete encrypted backup, including an empty `patches/`
directory. Retrying the same candidate must commit and preserve the team data.
Only observation and the deliberate fault are injected into coordination.

Candidate wheels are built once with the production stamp, lock export and
manifest helpers; successful main builds publish those same tested bytes.
The existing `old-data upgrade` required-check name aggregates both migration
and installed checks; catalog or asset failures fail that aggregate gate. This check does not exercise
GitHub download inside the privileged process, external provider authentication,
remote canonical roots, arbitrary historical data, or actual machine reboots;
the separate reboot qualification remains. Local macOS checks cannot qualify
this root/systemd journey. The installed jobs pin Ubuntu 24.04 and install the
operator guide's checksum-pinned uv into `/usr/local/bin` with root ownership.
The harness validates the executable and its ancestors, drops runner Python and
uv environment settings, and keeps both ordinary and probation HTTP on the
disposable port. Repeated post-update backups check archive and receipt retention
and capture-stage cleanup. The old source/cache tests retain current and stale
projection cases; their duplicate standalone snapshot round-trip is removed.

The checkpoint is an update-local artifact, distinct from the encrypted backup.
The root-privileged worker invokes GNU `cp -a --preserve=xattr --reflink=auto
--sparse=always`, grouping roots on each filesystem in one invocation to preserve
hardlinks within the copied set. Fresh payload workspaces live on those
filesystems outside every captured root; the central operation workspace holds
their catalog. Copying preserves ownership, modes, links and supported filesystem
metadata, including ACLs and xattrs. FIFO and socket nodes are retained as nodes;
process connections are not filesystem state. An external hardlink becomes
independent saved content. A small BSD copy fallback serves macOS development;
Linux CI qualifies production GNU behavior.

Readiness is durable only after copying and `sync -f` succeed. Rollback records
intent per root, renames the live tree to its operation quarantine, renames the
saved payload into place and fsyncs both parents. Originally absent roots return
to absence. Recovery resumes each rename from its journal and paths after a
crash. The snapshot is consumed; a completed root is never replayed or rescanned
over later accepted work. There is no second full rollback copy. Existing active
operations finish with the old supervisor before its update. Historical completed
journals remain readable for retention, but legacy subset checkpoints cannot
serve as whole-root rollback sources.

Installed mutation commands serialize preparation and pruning with a separate
preparation lock; startup recovery retains the existing operation lock and can
run while systemd starts during an update. Retention runs under the operation
and backup/deployment locks after successful update, including an already-current
update, supervisor update, or restore; `server prune` invokes it on demand.

`limits.py` keeps zero finished checkpoints, the two newest completed application
release trees plus the live release, 20 operation journals, and two completed
root environments per supervisor/operator storage plus selected or executing
environments. Cleanup removes checkpoint catalogs and their per-filesystem
payloads/quarantines before forgetting journals, including UUID workspaces left
before journal publication. Failed numeric build directories are reclaimed.
Release receipts live only as long as the retained release trees; selecting a
pruned build fetches and verifies its promoted bundle anew. Root managed Python
runtimes remain only when retained environments reference them; their interrupted
download staging is reclaimed. The one-time adoption workspace remains protected.

Subprocess diagnostics keep at most 20 output/error/probe logs after failure,
with the existing 8 MiB output bound enforced on retained files; successful
cleanup removes them. Downloads, fetch staging and locks, interrupted atomic
metadata writes, the root uv cache, and application maintenance backup captures
are reclaimed after success. New application installation uses a per-release
temporary directory with persistent uv caching disabled, so release retention
owns temporary files.
It reuses the service account's managed Python 3.12; shared runtimes and provider
caches are not deleted because retained agent environments may reference them.
Installation logs are bounded by the same output limit and remain inside retained
environments. Journald owns service
and nightly backup logs under the host's configured journal retention.

Pruning refuses when selected/current identity disagrees or an operation is
unfinished. Unknown artifacts remain untouched and are reported; retention
never follows a symlink into unrelated data. These are artifact-count bounds,
not a byte quota on scientific history or an instruction to delete agent scratch.

### Selection and startup guard

The supervisor persists each operation phase before its consequential effect.
It runs the selected candidate as a bounded service-account subprocess with
HTTP and background admission closed, verifies its exact identity and private
live-state proof, and stops that probation process. A durable `candidate_chosen`
record is the point after which old data may never be restored automatically.
Only then does it publish the selected receipt and start the ordinary service.
A failure after checkpoint readiness and before that choice restores the stopped
roots before selecting and starting old code. Snapshot creation is journaled
separately from preparation. The previous release then runs its own fenced
startup probe. Failed candidate trees stay quarantined and are reported for
inspection.

`rcp.service` invokes root `rcp-supervisor recover --startup` in `ExecStartPre`.
Recovery uses local installed code, checkpoints and journals; it performs no
release fetch and needs no GitHub connection. It completes an interrupted
rollback before permitting ordinary startup. Startup recovery never recursively
starts or stops its own systemd unit. When an active coordinator holds the lock
while waiting for systemd, the guard permits only an already durable chosen
release whose selected receipt and pointer agree. Lock contention alone grants
no startup authority. Unknown, inconsistent, multiple active, or corrupt
journals fail closed.

Recovery at or after `candidate_chosen` or `previous_chosen` preserves all
potentially accepted work. It verifies the chosen release's current startup
without applying the old captured proof to newly accepted state. Fresh-host
restore rollback keeps uninitialized data stopped; ordinary startup must prove
an initialized team before admission. The application's `create_app` reads no
deployment journal and makes no release, checkpoint or rollback decision.

`server doctor` is read-only. It reports selected/current/running identities,
private control availability, the root-owned observational status projection,
and each machine account's durable provider login state (`provider_logins`,
read from the application database without opening it for writing); that
projection cannot authorize startup or replace the private journals.

Team Settings reads release and backup status without opening the supervisor's
private restore journals. The current public projection has no completed-restore
timestamp, so Settings reports restore history as unavailable with no completion
time or drill age. Missing history does not imply that no restore occurred and
does not prevent the rest of server status from loading.

### Source installation adoption and qualification

The first paired-wheel bootstrap on a source installation stages new integration
without replacing the active config, wrapper, unit, or source pointer. A separate
root-owned adoption journal retains those original files and full source commit.
A startup guard is installed before stopping the old service. Current code
copies SQLite bytes into a disposable database and discovers registered local
roots without opening or modifying live SQLite. One grouped stopped snapshot
then captures raw data and those roots together, preserving hardlinks between
them. Typed preparation runs afterwards; its replacement roots must be covered
by that snapshot. The original raw snapshot stays rollback authority. A complete
protected capture is required before activation. This also handles the
predecessor's known partial-backup inventory defect without using that omission
as permission to activate unprotected data.

The candidate uses the ordinary fenced application contract. Before its durable
choice, adoption failure restores the grouped raw snapshot and original
integration before old source code may run. After choice, recovery preserves the selected
candidate's data. The legacy path exists only for this explicit adoption; normal
server updates consume promoted artifacts built from human-merged main.

Required CI continues to test direct upgrades from every immutable server-era
persistence boundary and the exact candidate base. The disposable qualification
workflow uses an external QEMU controller on GitHub-hosted Ubuntu 22.04/24.04,
requires actual changed Linux boot IDs, and interrupts update and restore at
journal and individual root publication boundaries, including repeated rollback
and recovery without network access. Unavailable virtualization produces an
explicit unqualified failure. Local process interruption tests do not prove
recovery across a real reboot. The production cutover requires that
qualification and human promotion first.

## Central checkouts and repository credentials

Each team project has one server-managed checkout set: exactly one
team-controlled central checkout for every declared repository on that
repository's configured execution machine. A server-local checkout is owned by
`rcp`; an SSH checkout is owned by the explicit remote execution account and is
provisioned from the server through that account. Member checkouts are
independent working copies, not alternate RCP homes, and RCP neither discovers
nor imports them implicitly. A new team project or personal-to-team transfer
prepares the complete central checkout set before registration.

The server-local central root is the fixed installed layout. For an SSH account,
the durable setup request records either one reviewed nonsecret absolute central
root or a null default-root intent. The API never guesses the remote home. The
shipped exact-account helper resolves that home and turns the default intent into
`<remote-home>/.local/share/rcp/projects`; the machine receipt then persists the
resolved central root and exact `<project-id>/repositories/<alias>` descendants
for final review. A lab may deliberately choose another absolute account-owned
root, such as mounted research storage, but the machine operator's CLI
revalidates ownership, modes, symlink-free ancestry, and the exact descendants
before cloning. The project manifest records only the resolved repository paths,
not authority to pick a different root later.

This first slice is GitHub.com-only. Before persisting a provisioning request or
performing filesystem or network work, one `GitHubRepositoryRef` parser accepts
only the two documented HTTPS and SCP-style SSH forms. Its deliberately narrow
ASCII subset accepts an owner of 1–39 alphanumeric-or-hyphen characters that
begins and ends alphanumeric, and a repository of 1–100 characters from
`A-Z`, `a-z`, `0-9`, `.`, `_`, and `-` other than `.` or `..`. It strips one
exact optional `.git` suffix and stores a lowercase `owner/repository` identity.
It rejects credentials or userinfo, query/fragment text, percent-encoded or
traversal segments, local paths,
`file://`, `ssh://`, arbitrary hosts, ports, and extra path components. Clone
URLs and GitHub deploy-key settings URLs are generated from the canonical
identity; request input is never passed through to Git. GitHub Enterprise and
other Git hosts require a later operator-configured trusted-origin design.

The default Git credential is a repository-scoped SSH deploy key whose required
capability is write. [GitHub's deploy-key form defaults to read-only and one key
cannot be reused for several repositories](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys),
so setup must create one key per GitHub repository, explicitly instruct the
operator to enable write access, and verify an actual request-scoped push before
claiming readiness. Each private key stays in the protected credential directory
of the account that owns that checkout, local or remote. Server-local keys stay
under `/home/rcp/rcp-server/credentials`; an SSH checkout's key is generated and
used only as its exact configured remote account under the verified absolute
`<remote-home>/.local/share/rcp/credentials/` root. RCP resolves that account's
home through a fixed shipped helper and verifies uid, ownership, and modes; it
does not assume `/home/<name>`, trust shell `$HOME`, allow a manifest override,
or copy private key bytes between machines. Every key is absent from SQLite,
project manifests, provider prompts, diagnostics, and backups. RCP never asks a
member to surrender a personal GitHub token to the team service.

The deploy key itself is the central checkout's GitHub identity; no GitHub user
is logged in on the RCP server. RCP generates the key pair on the local or remote
execution account, retains the private half there, and publishes only the public
key, fingerprint, deterministic label, and exact repository instructions. A
human with repository-administration authority adds that public key under the
repository's GitHub deploy keys with **Allow write access**. Re-running the same
provisioning command then uses the protected private key for `ls-remote`,
clone/fetch, and the request-scoped write proof. A private repository cannot be
read before that grant; a public repository may be read anonymously but is not
ready until the same write grant passes. Fully automatic grant installation
would require GitHub OAuth, a GitHub App, or a user token and remains outside
this slice.

Each project deploy key receives the deterministic nonsecret label
`rcp:<space-id>:<project-id>:<repository-alias>` and its public fingerprint is
retained in the provisioning receipt. This is recovery metadata, not a secret:
it lets a replacement server tell the operator exactly which old GitHub grant
to revoke while private key bytes remain outside SQLite and backup.

The write proof points a temporary request-scoped ref at an existing commit,
reads it back, and removes it. An empty repository therefore stays **operator
action needed** until the operator creates and pushes its first real commit; RCP
does not manufacture a hidden initialization commit.

Cancellation removes only request-owned local/remote private-key material after
an explicit disposition. If its public key was already added to GitHub, the
request names the label/fingerprint and stays **operator action needed** until
the operator confirms revocation or explicitly preserves the prepared request
for reuse. Losing the private half is not falsely reported as deleting the
GitHub grant.

The ordinary member-facing **Delete project** action applies to either a personal
or team project after membership checks. A read-only filesystem preflight runs
before one SQLite transaction repeats the task, episode, and watcher fence and
removes the registration plus its project-owned rows. App-owned stages,
snapshots, caches, and imported provider histories are removed only after that
commit. A later file-cleanup failure is logged with its concrete path and does
not make the completed catalog deletion fail.

The backend publishes the exact confirmation text. For a team project it says:
**The server-managed checkout and repository deploy key remain; credentials are
not revoked.** The Web renders that answer verbatim. Deletion never edits the
central checkout or canonical `.research/` history and never removes the deploy
key. This is catalog deletion, not machine deprovisioning or credential
revocation.

## Durable project provisioning

A human selects **Create a shared team project** in the unified project wizard,
whether viewed in a browser or source-built desktop. **Move an existing personal
project to a team** uses that same wizard but requires the desktop because it
coordinates the authenticated personal and team backends and owns the native
archive relay. The authoritative backend creates a durable provisioning request
before any machine work. Its backend-decided status is one of **waiting for
server setup**, **setup in progress**, **operator action needed**, **ready for
review**, **completed**, or **cancelled**. The browser renders those answers and
the exact next action; it does not infer progress from files or Git output.

The request names the target space; project name; canonical
`GitHubRepositoryRef` values and repository/machine aliases; state repository;
project and default-run truth scopes; default Auto-research invocation ceiling;
explicit central roots or default-root intent; and the human who authorized
preparation. An explicit root has a derived intended checkout path immediately;
an SSH default-root intent keeps that path null until the exact account home is
resolved. Invalid source or project-configuration text is rejected before the
request, filesystem access, or network access. For a new project it also mints
one random proposed `project_id`; an incoming transfer uses its existing project
id.
That id reserves the final central path namespace but creates no canonical
identity or writable home. `rcp server project provision <request-id>` performs
and resumes the server steps: path and permission checks, deploy-key
creation/readiness, clone or fetch, provider and execution readiness, and a
request-scoped Git write check. The request id is correlation, not machine
authority; the command still requires the server's OS privilege boundary.

The current direct team-project member API can create, list, and read these
durable requests without performing any machine step. Every authenticated team
member may inspect the preparation state. Only the member whose named identity
authorized a direct new-project request may cancel it, and member cancellation
is intentionally limited to **waiting for server setup**, when the recorded
disposition is **nothing to remove**. Once server preparation starts, the member
API refuses cancellation until the machine-owned workflow can record the exact
key/checkout cleanup or reuse disposition. Repeating an already completed
member cancellation returns the same durable result.

The command is resumable and exhaustive. If a deploy key is not yet installed,
it prints the exact GitHub repository settings destination, label, public key,
**Allow write access** requirement, and the same command to rerun. If the source
repository has no commit, it explains that the member must push their local code
through their normal GitHub workflow and names the repository plus the recheck
command; it never reaches into the member checkout. Missing SSH or provider
authentication similarly names the execution account and provider-native or
OpenSSH action, then resumes the same request after the operator performs it.

A direct `create_team_project` request is not an adoption or destructive fresh
setup path. If its cloned state repository already contains a canonical project
identity or Patch history, preparation becomes **operator action needed** before
any overwrite or archive: a personal identity directs the human to **Move to
team space**, and any other retained-history conflict requires a deliberately
cleaned or different repository outside this request. Final review rechecks that
no identity/history appeared after preparation. Incoming transfer has a
different bound rule below: matching retained history may be reused only after
the archive proves the same project, source home, aliases, and canonical heads.

The desktop offers **Run setup now** only when its native shell can prove a saved
operator SSH route can invoke that exact CLI. The saved route is explicit
nonsecret machine metadata, separate from the member connection: direct mode
requires `rcp@server`, while named-operator mode always inserts
`sudo -n -u rcp -H`. Otherwise the UI shows a copyable command for an operator.
The shell uses the system SSH configuration and agent; it never imports a
private key or asks for a `sudo` password. A named operator is preferred because
it is independently revocable and auditable. The desktop validates and bounds
machine-readable progress, then authenticates back to the team service and reads
the durable request; subprocess exit alone never advances or proves the UI
state. If interaction is required, the app opens the fixed command in Terminal
rather than collecting the secret itself. A browser without the desktop shell
can create and review a request but cannot run its machine steps.

Machine preparation alone never creates, transfers, or re-homes a canonical
project. When the request reaches **ready for review**, the UI shows the resolved
central paths, repository and provider readiness, and any work that must settle.
For a new project, only the final explicit target-space human confirmation
appends exactly the proposed project id; final creation does not mint a second
id. For personal-to-team transfer, one desktop review action records two
independent confirmations through the already-authenticated spaces: a team
member first admits the prepared incoming project, then the personal owner
releases the source project. Each backend records its own actor and binds its
receipt to the linked request; no cross-space user-id equality is assumed. A
crash after only the target confirmation leaves the source writable and the
same request resumable. The machine import command must revalidate both human
receipts and cannot supply either one itself.

For direct new-team creation, `POST
/api/project-provisioning/requests/{request-id}/complete` accepts the exact
published final-review digest from a current named team member. The original
preparation authorizer must also remain enrolled. The route rechecks the bound
configuration, all six execution profiles, every resolved checkout path, Git
and provider proofs, and retained canonical inputs without rerunning
preparation.
It renders the reviewed machine aliases, operating-system accounts, repository
paths, truth scopes, provider runtimes, and fixed permission contracts into the
manifest, then appends one system-owned `created` identity with the already
reserved id. The reviewer becomes the first project member and is retained as
the seating actor.

The recoverable product boundaries are manifest publication, exact identity
Patch, catalog registration, first-member seating, and request completion.
A retry may accept only the exact one-Patch identity prefix created for this
request; any other identity or Patch history returns to review with the
transfer/clean-repository action. Repeating confirmation after any boundary or
after completion returns the same project and request. A stale digest, changed
manifest, moved or unsafe path, incomplete provider proof, departed authorizer,
or conflicting catalog identity fails loudly without adopting or archiving
research.

Linking also binds a checksummed nonsecret source-configuration summary: source
RCP/schema and supported archive-codec versions, repository sources and
repository/machine aliases, state repository, truth-scope provenance, and the
source-manifest digest. The target chooses a common supported version before
machine preparation and rebuilds its reviewed configuration from that structure,
not from source absolute paths or provider homes. Source release rechecks the
same summary and target preparation revision before fencing; incompatible code
or a changed source manifest returns to preparation while the source is still
writable rather than creating a transfer the target cannot decode.

Serialized cross-space receipts are not treated as self-authenticating. When
the requests are linked, the source and target each generate an independent
random 256-bit one-time proof, keep their own raw value protected, and exchange
only SHA-256 commitments through the two authenticated request APIs. Final
review binds both commitments. The source reveals its raw release proof only
inside the post-fence sealed archive; the target verifies the commitment before
import. The target reveals its raw activation proof only after activation
commits. A fixed native retrieval route requires the saved permanent team-member
token, the exact target confirmer, and the completed linked request; a
cookie-only Web session cannot read it. The native relay returns the proof
directly to the pinned source backend, which verifies the commitment before
retiring its catalog row or recovery copy, then returns only a public cleanup
acknowledgment so the target can erase its raw proof. Retry before that
acknowledgment returns only the same request-bound value to the same member. A
raw proof is request-scoped transition evidence, not a
member/provider/Git/SSH credential, and never enters Web state, command
arguments, logs, or imported project history.

These proofs make a serialized receipt, request id, archive path, or successful
CLI exit insufficient within RCP's supported protocol. They are not a hostile
machine-security boundary: root or the `rcp` account can read or alter the
storage it owns, as S95 already states. Human and machine authority remain
separate product paths without claiming cryptographic defense from the machine
administrator.

## Personal-to-team transfer archive

After both human confirmations and source-configuration revalidation, the source
transfer owner closes paused standalone attempts as interrupted, with a
request-bound event and receipt. It preserves their original output, session
evidence, finish timestamp, and source scratch. This administrative closure does
not broaden ordinary worker transitions or restart recovery. It never stops
queued/running/pausing tasks or episode-owned attempts. Any remaining live task,
episode, watcher, report, child, or delivery refuses the whole settlement
transaction; those owners must settle through their normal lifecycle. The final
desktop confirmation discloses this paused-attempt closure. Read-only history
export does not mutate task state.

After source work settles, transfer produces one versioned, checksummed project
archive. It contains the durable project identity, accepted main and graph-branch
canonical history and exact heads; typed canonical RCP chat transcripts; the
current Paper draft and canonical introduction; opaque `.research/facts/`
files; all finished human-visible operational history; and the exact bytes of
referenced kept artifacts and legacy kept result views. Immutable branch
metadata, Patches, and merge receipts travel; main and branch materialized
outputs do not. Finished database history includes terminal task attempts and
their events/receipts/usage, the current Paper draft, and stopped
episode/watcher/report history. Every finished Auto-research child, message,
lifecycle notice, recovery, receipt, Apply result, and inert command record
needed to render the stopped episode also travels; a pending child, delivery,
recovery, report, or watcher must settle or be terminalized before export and
never crosses as runnable state. Native-session/stage bindings, pending wake
fields, wrap-up output paths, space membership/authentication, project
invitations, provider-skill inventories, disposable result views,
reconciliation watermarks, and source machine-operation leases do not travel. A
schema-inventory test requires every later project-linked table to be
classified explicitly. Temporary human-input attachment bytes remain excluded.
It also contains one complete read-only
historical source for every provider-native conversation matched to the
project's declared repositories. The existing conversation index makes that
selection automatically and best-effort from recorded working paths and
declared repository paths, using configured provider roots and its existing
local/SSH retrieval. Selection and copying run under each saved source profile's
exact local or SSH execution account; they do not substitute another provider
home or member laptop. Clear matches travel in full; rewritten, unmatched, or
unreadable conversations are skipped with a non-blocking summary and no
completeness claim. There is no human transcript-selection step. RCP-owned
project chats travel separately as project history and are not selected again
as provider-native sources.

The export is a typed projection, not a raw copy of the personal data directory
or SQLite rows. It removes reusable stages, execution host/root bindings, live
continuations, temporary attachment bytes, scratch/cache pointers, credentials,
and machine configuration. Canonical RCP chat JSONL is parsed and rewritten:
stable chat/message ids, text, provider/model labels, graph receipts, and
display-only attachment metadata remain, while native session ids,
execution-machine/cwd fields, and unmapped source operation bindings do not.
The current Paper draft retains base/ancestor conflict content and the canonical
introduction remains a separate file. Completed Paper-coach task answers remain
terminal history, but `writing_sessions` and `chat_session_contexts` do not
transfer because they are executable native-session/prompt checkpoints rather
than durable human content.
Every imported terminal task has a durable history-only marker. Backend task
projection and control admission force Pause, Resume, Retry, and graph repair
unavailable, remove the task from the human-action queue, and expose no
native-session id as an executable continuation, without changing the task's
honest terminal status or answer. Source rows retain their historical native
session evidence; imported task rows and canonical chats do not. Native-chat
origin proof and chat responses therefore expose no source continuation. A later
target task is a new ordinary task under target configuration; imported failure
is not relabeled as success or as an abandoned target recovery.

Safe artifact metadata remains part of that terminal history even when its
disposable stage bytes do not. A referenced kept artifact remains openable
and downloadable through its repository owner, but cannot Keep again or revise
through the detached native session. An unkept artifact whose stage is excluded
from transfer or restore is projected explicitly unavailable. Every task-artifact
response publishes `available`, `unavailable_reason`, `can_open`, `can_download`,
`can_keep`, and `can_revise`; the unavailable case makes every `can_*` false and
has no stage URL. Content, download, Keep, and artifact-context admission recheck
those durable facts. The Web renders the backend answers, never infers
availability from `history_only`, `kept_filename`, or a remembered stage path,
and never constructs or probes a route for an unavailable action.

The source `manifest.toml` travels only as checksummed configuration provenance;
it is never published as the target's live manifest. Historical repository and
machine aliases, state-repository identity, and truth-scope provenance remain
stable because accepted Patches and `SourceRef`s refer to them. The reviewed
target request rebuilds the live manifest with the team central paths,
host/accounts, provider binaries, and profile execution choices. Native provider
source roots follow the target account's provider conventions; they are not
source execution state and are never copied from the source manifest. Source
absolute paths and provider homes cannot become target configuration. Before
import, main and every retained branch must replay against that rebuilt
manifest. Retained `.research` already cloned from Git is accepted only when its
identity and canonical inputs are byte-identical to a coherent prefix of the
bound archive and contain no later archive-external commit; a different
identity, missing/renamed historical alias, later head, unknown durable entry,
or byte conflict stops without overwrite.

The target-configuration validator implements that boundary before import. It
binds the ready provisioning review, source configuration, link receipt, and
archive identities; renders configuration only from target readiness proofs;
checks retained Git inputs as an exact archive prefix; and semantically replays
the complete main and branch history in an isolated workspace. Its receipt
binds the exact final review, archive manifest, rebuilt target manifest,
retained-prefix fingerprint, and replay heads for the later atomic importer. A
transferred branch accepts only the authorizer from the canonical project home
at its exact immutable main base; matching the current home is insufficient for
an older base, and that historical authority does not grant current write
authority after the home-transfer Patch.

Imported task histories are readable only and cannot Resume or Retry. Imported
provider histories receive no execution binding and are never installed under
the target account's native provider home. Seed/Refresh receives
the imported project-owned sources alongside current provider roots and the
preserved overlap-tolerant `last_refresh_at`. A local provider reads the durable
project source directly. For an SSH provider, RCP copies only the validated
project-owned imported-source inventory into the existing immutable task-input
stage and binds the prompt/read scope to that staged path; the remote native
provider roots remain in place and are never copied. Resume verifies and reuses
the same staged fingerprint, while a missing or changed stage takes the existing
visible clean-retry path. Best-effort applies to selection before the archive is
sealed; afterward a missing or hash-mismatched imported file is durable
project-source corruption and blocks Seed/Refresh rather than being silently
omitted.

The transfer wizard offers **Include local unpushed commits**, off by default.
Without it, target provisioning uses the GitHub checkout and review explicitly
warns that unpublished source commits stay behind. With it, source preparation
records the exact HEAD of every declared repository and binds those commits to
the source configuration and both human confirmations. Export rechecks those
HEADs and includes one self-contained Git bundle per repository; no push to
GitHub occurs. Only the saved commit and its reachable history travel, not other
local branches, uncommitted changes, ignored files, or external output/data
directories. Native credentials, Git configuration, and hooks are not copied.

Opt-in uses archive schema/codec `2` / `rcp-transfer-v2`; default transfers retain
the byte-compatible v1 format and omit the new commit fields entirely. A target
that cannot accept the commit-bearing configuration refuses before source
release. A changed HEAD or changed choice requires fresh review, never silent
substitution. Existing v1 request commitments and saved archives remain valid.

Before publishing research history, the target importer validates each bound
bundle in isolation, imports its objects without remote access, and checks out
the exact saved commit in **detached HEAD** state when the revision changes.
An already-matching checkout is verified without changing its branch attachment;
untracked/ignored files are preserved because no checkout is needed. This also
allows retries after RCP has published kept artifacts. Tracked changes still
refuse. The target's origin and existing branch refs stay intact; create a branch
before making new Git commits from detached HEAD.
Dirty destinations, repository layouts unsupported by the guarded Git helper,
and tracked `.research/` or `.recovery/` refuse without overwriting them. RCP
canonical history still travels exclusively through its existing archive owner.
An interrupted multi-repository import can be resumed with the same archive;
already-restored repositories are verified, and the project remains inactive
until the normal complete-import/activation boundary succeeds.

Source-side provider-history selection and archive capture are implemented. The
source indexer copies each selected original native transcript byte-for-byte to
`provider-history/<provider>/<sha256>` in the transfer capture. It uses the
configured provider root on the exact local or SSH source account, then rechecks
the copied file's recorded working path against the same declared repository.
RCP does not normalize the bytes into its lossy conversation-record model.
Provider session ids, source paths, tool output, and other passive metadata may
remain inside them, but none becomes a live execution or resumption binding.
Selection is deliberately best-effort; unmatched, rewritten, malformed, or
unreadable sources are summarized without a completeness claim, and historical
checkout inference and a conversation-classification UI remain outside this
slice. The target imported-source owner now atomically publishes sealed bytes
under `<RCP_DATA_DIR>/project-sources/<project-id>/provider-history/<provider>/`
with a checksummed inventory receipt and read-only modes. Local Seed/Refresh
receives those validated project-owned roots separately from native provider
homes. Missing, rewritten, writable, symlinked, special, or undeclared entries
fail the run visibly. Remote Seed/Refresh stages only that sealed inventory,
rebinds imported roots to the immutable task input, and verifies the retained
fingerprint before Resume or prepared-context reuse.

Given a request-scoped archive tree already decoded by the target transfer
owner, the target importer validates its exact manifest inventory, regular-file
safety, checksums, identities, canonical heads, record references, reviewed
target configuration, and excluded-field rules before mutation. It inserts the
selected operational records in one SQLite transaction with explicit
source-to-target id maps, an import receipt, and the exact pre-publication target
configuration receipt, including retained-history evidence. It then publishes the reviewed
target manifest, canonical history, transformed RCP chats, Paper, facts, kept
files, and imported provider histories through their concrete atomic owners.
Imported task rows are history-only; imported kept result views are already
kept and non-revisable; no project row or writing session is created. Each
publication call verifies the declared bytes, canonical replay verifies the
observed head, and one deterministic completion digest binds those readbacks.
The publication sequence is repairable rather than one cross-filesystem
transaction: an interruption can leave matching target bytes and a
`database_imported` receipt, but the project remains unregistered and invisible,
and a retry of the same exact digests idempotently reads back or republishes the
same corpus. Such a retry rebuilds from the stored configuration receipt and
never re-inventories target state that a partial publication may already have
changed. Activation follows only a complete receipt. Sealed-byte upload,
codec decoding, activation, and source retirement remain separate target/source
transfer-owner steps.

Once the source home change commits, the personal backend atomically seals the
one exact mode-0600 archive at
`<RCP_DATA_DIR>/transfer-exports/<request-id>.rcp-transfer` and binds its digest
receipt to those bytes. Its control envelope contains the raw source-release
proof only after the source fence has committed; that proof contributes to the
archive digest and is consumed, not imported, by the target. Every relay retry
re-hashes and streams that same file;
an already bound archive is never regenerated from a later provider-history
selection. The file remains recovery-critical until the matching target
activation receipt arrives. Cleanup validates the still-present bound archive
before consuming the raw proof or retiring the source; missing or corrupt bytes
leave the project visible for repair. After proof consumption it retires the
catalog row and revalidates before unlinking that exact request file. Cleanup
requests are serialized by the project operation lock and retries use the
durable consumed-proof plus retirement receipts to distinguish a completed
unlink from premature loss. Ordinary project Delete is unavailable while the
source fence or sealed export is needed.

`source_released` is also the durable new-work fence. Fresh human-root task,
episode, Auto-research, direct Experiment, and branch-merge admissions recheck
that fence inside their database write transaction; HTTP routes additionally
hold the per-project operation lock across admission. Already-authorized
watcher and episode continuations may settle, but terminal export refuses any
remaining live work. Canonical and transformed project-file capture holds the
workspace transaction, including the remote advisory lease for SSH state.
Source retirement hides the project from catalogs and
active membership checks without deleting its retained membership or invitation
audit rows.

An interruption after release or the home-change fence remains resumable through
the same source-release action. Backend projection advertises that action until
archive binding completes; its read-only boundary endpoint returns the original
confirmed configuration and head, not the later fenced head. Re-entry finishes
settlement/capture using the existing receipt before the desktop attempts relay.
It never needs a second transfer request or another ownership confirmation.

The desktop is the transfer-byte relay for this first target. Its final review
records target admission before source release through the two separate
authenticated backends. The source backend persists its human release receipt,
then fences source admission, settles authorized work, commits the home change
with both human actors, and binds the resulting exact archive digest to both
linked requests. Only after both human receipts and the source-fence receipt
exist does the native Rust shell re-verify the pinned personal backend, request
the confirmed request-bound sealed export itself with the exact pinned-instance
header, and stream bounded response chunks
into the stdin of one system-SSH child running the fixed remote command
`rcp server project transfer-import <request-id>`. Through the private control
socket, that CLI obtains the expected digest/size and an upload lease, then alone
writes a mode-0600 same-directory `.partial` under
`<RCP_DATA_DIR>/transfer-inbox/`, publishes it without overwrite through a
same-filesystem hard link to `<request-id>.rcp-transfer`, and removes the partial
after verification. It accepts no arbitrary archive path and never opens SQLite.
The running service owns the durable `active`, `complete`, `consumed`, or
`invalidated` upload record; the CLI owns only the request-derived filesystem
lease and byte stream. Completion re-hashes the final file before committing its
typed receipt, and an exact retry consumes and verifies stdin without replacing
the existing final. The CLI then invokes a separate control operation on that
same request and lease boundary. The running service decodes the exact sealed
archive into a disposable request stage, revalidates both human confirmations,
the source-fence receipt, target readiness, ownership/mode, digest, reviewed
manifest, and the precommitted source-release proof, captures retained history
through the concrete local or SSH state owner, and invokes the atomic target
importer. Neither upload completion nor CLI success is project authority.

After importer readback and canonical replay, target activation compound-commits
the prepared project registration, the admitting target member's first seat,
provisioning completion and its step receipt, the immutable activation receipt,
the request's `target_activated` phase, and the upload's `consumed` state in one
SQLite transaction. Only that transaction makes the project visible and makes
the raw target-activation proof legally retrievable. The verified inbox archive
and disposable decode stage are then removed. If the process stops after the
transaction but before file cleanup, an exact retry reads the same activation
receipt, refreshes process-local catalog state, and removes only the verified
request file. If decode, import, replay, or final review fails before activation,
the request remains unregistered and the exact completed inbox file is retained
for repair.

Update maintenance refuses immediately while an upload is active, leaving
admission open so the running service can accept that upload's completion. Its
semantic preparation preserves only receipt-backed `complete` files, ignores
already-`consumed` records, and rejects a leftover or untyped inbox file. The
independent rollback checkpoint retains the whole inbox before validation.
Restore invalidates active and complete uploads for every nonterminal target
request, so an old lease cannot complete after replacement. A reviewed
`archive_bound` restore re-entry binds the exact restored revision, final-review
digest, confirmer, archive, and a fresh relay lease before returning the request
to `archive_bound`; the desktop/operator recovery flow still has to invoke that
boundary explicitly.
After activation, the native relay carries the target's precommitted activation
proof from that permanent-member-token-authenticated native route directly back
to the pinned source backend so source cleanup cannot be authorized by a forged
JSON receipt. The proof never appears in CLI progress or a cookie-authenticated
browser response. Tauri constructs no `scp`, `mv`, or remote shell pipeline.
Browser JavaScript, URLs, command arguments, shell strings, logs, and either
space's credential store never contain archive bytes, either raw transition
proof, or the other space's credential. The Web command supplies only the
validated request id and receives only progress/result metadata; bytes and raw
proofs never cross Tauri IPC. Without a proven
operator route the desktop exports one protected local file and shows bounded
Terminal commands instead of collecting SSH or sudo secrets.

Partial target inbox files are not team backup data. If a team restore contains
a nonterminal incoming request, its old upload lease and in-progress machine
state are invalidated and it becomes **operator action needed**. For an
`archive_bound` request, re-entry requires the exact restored revision, rebuilt
ready-for-review digest, and original current target confirmer, then issues a
new upload lease; it never treats the absent inbox as imported. Later restored
phases remain frozen until their owning proof/cleanup recovery step revalidates
them. The sealed source archive belongs to the personal app data, not the team
backup. A committed source home change remains fenced and is never reversed
merely because the target was restored.

## Backup and restore

An unattended backup uses an `age` public recipient stored on the server. By
default, `backup configure` creates its matching identity once at
`/etc/rcp/backup-recovery.agekey`, owned by root with mode `0600`, and reuses it
without displaying or copying its private text. An operator may instead supply
an externally managed public recipient. The encrypted archive contains a
consistent SQLite snapshot, a manifest of captured main and graph-branch
canonical heads, and the append-only main/branch history needed to replay or
validate those heads. Immutable branch metadata, Patches, and merge receipts are
included; derived main and branch materializations are not. It separately
captures canonical RCP chat JSONL, the optional canonical Paper introduction,
safe regular `.research/facts/` files, and only the kept artifacts and legacy
kept result views referenced by the SQLite snapshot. It also contains
project-owned provider histories imported by personal-to-team transfer because
those files may be the team's only durable Seed/Refresh source. It excludes Git and provider
authentication/configuration stores, live provider homes and logs, SSH keys,
source repositories, other materialized outputs, temporary input attachments,
run/transfer staging, scratch, and caches. Backup does not pause dispatch or
Apply and never marks an unreachable project protected.

Pending artifact revision candidates are task-stage state and are likewise not
copied into an offline backup. Restore atomically marks them Abandoned before
task-session detachment; it never publishes candidate bytes, and the original
temporary or kept artifact remains unchanged. Server update checkpoints preserve
whole stopped roots, including unresolved local candidates, before old preparation
settles any accepting local temporary or kept-artifact replacement journal.
Semantic preparation separately validates the recovery-stage inventory and
refuses if replacement state remains unresolved.
When the SQLite snapshot contains an unresolved kept-artifact revision, its
kept-file inventory is bound to the candidate's base digest. A later mismatch
makes that project uncaptured instead of archiving unaccepted candidate bytes.
A project inventory accepts every canonical task identity RCP mints: UUID4 for
ordinary tasks and deterministic UUID5 for Auto-research child Experiments, so a
project that has run one such episode stays capturable and updatable.

The app-data inventory is closed rather than an implicit recursive copy.
`rcp.sqlite3` enters only through SQLite's online snapshot, and transferred
`project-sources/` enters through its typed project-history owner. Raw SQLite
WAL/shared-memory files, `rcp.lock`, `rcp-server.json`,
`bootstrap-manifests/`, `project-snapshots/`, `paper-snapshots/`,
`state-cache/`, `project-caches/`, legacy `source-cache/` and
`session-slices/`, `chat-attachments/`, `run-stage/`, `transfer-inbox/`, and
`transfer-exports/` are explicit exclusions. They are respectively database
ephemera, process metadata, reconstructed locator copies, derived
snapshots/caches, temporary execution or upload state, and personal
transfer-recovery state owned by its source receipt. An unknown direct app-data
child makes capture visibly partial until its concrete owner classifies it.
For every project in the copied database, backup records the exact sealed
imported-history inventory, including an explicit absent result. Project-file
capture revalidates present bytes through that same owner and the archive binds
its canonical owner manifest, content-addressed files, byte counts, and digests.
An orphan, incomplete, rewritten, symlinked, special, or otherwise unsafe owner
makes capture fail visibly; backup never substitutes a live provider home.
An uncaptured project retains its safe failure category and relative failing
component, including local state, checkout, imported-history and SSH distinctions.
Raw exception text and absolute locators are not capture diagnostics. The backup
CLI result and doctor `problems` include these per-project causes; the supervisor
reports them in `backup_warning` when a pre-update backup is incomplete, including
nonzero CLI results. Existing strict receipt formats are unchanged. An optional diagnostic
sidecar, bound to the backup operation ID, preserves causes for later inspection
without breaking older readers. Sources without that sidecar retain their older
diagnostic limits; the supervisor names the retained receipt instead of inventing
a cause.

For each protected team project, the manifest also binds a nonsecret recovery
descriptor from the same captured provisioning state: repository sources and
aliases, resolved central paths and machine/SSH-route references, canonical
manifest configuration, and old deploy-key labels/fingerprints. This descriptor
is enough to reconstruct the checkout set without a member checkout or personal
Git credential. Every configured machine remains in the descriptor and restored
manifest, including execution machines with no checkout. A resolved central root
is required only for a machine that owns a repository; an unused machine may
retain an unresolved root without making the project uncapturable. Host/account
bindings remain exact for every machine. A missing, stale, credential-bearing,
or inconsistent descriptor makes that project uncaptured. The completed
provisioning proof continues to bind project identity and checkout topology.
Settings-owned provider paths, agent
profiles, skill defaults, default run scope, and Experiment invocation ceiling
may change afterward; backup captures their current canonical manifest values
rather than treating those supported edits as stale provisioning.

The first archive contract accepts only a native X25519 `age1...` recipient and
uses the upstream `age` CLI from `1.0.0` through the 1.x line. Plugin, SSH,
passphrase, and post-quantum recipients are not accepted in this slice, so an
archive created on either supported Ubuntu release has the same required
decrypt path.

The first backup destination is one explicit writable filesystem directory.
RCP owns archive creation, atomic placement, integrity status, and retention in
that directory; it does not implement S3, SSH upload, cloud synchronization, or
another storage transport. The directory may be a local path or a mounted
filesystem. RCP neither infers nor warns whether its physical storage is on or
off the server, and it makes no durability claim based on that topology.

Backup destination, `age` public recipient, schedule, and retention are strict
versioned machine configuration in the installed server config file, not team
SQLite state. Its schema-v2 `[backup]` table remains exactly those four keys.
The root-owned config is readable by `rcp`, contains no private recovery
identity, and is replaced atomically only through the following explicit
operation:

```bash
sudo rcp server backup configure \
  --destination <absolute-directory> \
  --schedule <HH:MM> \
  --retention <count> \
  --confirm
```

The schedule and retention flags default to `02:00` server-local
time and 30 newest integrity-readback archives; only the destination and
explicit confirmation are required. The default path uses `age-keygen` to
create the fixed root-only identity atomically and records only its derived
native X25519 public recipient in `server.toml`. It atomically publishes the
same nonsecret recipient in the root-owned mode-`0644`
`backup-recovery.agekey.pub` sidecar. The presence of the private identity file,
not a config key, identifies the server-managed path for progress; recipient
equality with the sidecar preserves a loud missing-identity refusal if that file
is later lost. Reconfiguration without `--recipient` must validate and reuse the
same identity. A missing, damaged, unsafe, or mismatched retained identity fails
loudly and is never silently replaced. `--recipient <age1-public-recipient>`
remains an advanced path for an externally managed identity; an already
configured external recipient must be supplied again exactly, and recipient
rotation is not implicit. Private `AGE-SECRET-KEY-...` text is never accepted by
the CLI or emitted in progress.
The same resolved schedule renders the systemd timer; there is no second
editable timer value. Retention also preserves the newest complete archive if
it has fallen outside the configured count. This bounds archive and receipt pairs at
`retention + 1`; nightly, manual, and pre-update protected captures use the same
owner and destination. Status and optional diagnostic sidecars overwrite fixed
paths and retain their existing byte/count limits. Backup capture stages retain
only the newest failed capture (`BACKUP_RETAINED_FAILED_CAPTURES` in `limits.py`);
the next completed protected or partial archive removes all prior backup stages.
Task scratch is not eligible. Under the backup lock, retry reconciles exact
publication intents before reclaiming recognized interrupted archive, receipt,
and status temporary files and orphan receipts from interrupted retention.
Research history is never truncated to fit a byte quota.

Keeping the default recovery identity on the same server makes routine backup
setup and same-machine restore simple, but does not by itself survive total
machine loss. A lab that needs that disaster-recovery property must either
retain a protected copy of the generated identity outside the machine or use
the explicit externally managed recipient path. RCP does not infer or claim
that either the archive destination or identity placement is off-server.
One stable root-owned operation lock serializes install and configuration. RCP
fences an already loaded timer before changing either unit and proves it
inactive and disabled after daemon reload. Before the first unit mutation it
atomically records the complete intended public configuration in a pending
file; an interrupted operation must finish and read back that exact pending
configuration under the same lock before a later install or configuration may
continue. Only an exact config/timer/systemd readback clears the pending file.
Backup outcomes and archive manifests remain project-visible operational status,
but restoring SQLite never silently reconfigures this machine or its timer.

The timer is not enabled in an intermediate source commit that lacks the
concrete `backup run` owner. Configuration and unit rendering may land first,
but activation follows only after the command and unit readback exist; a failed
first run/readback leaves the timer disabled with an exact diagnostic.

Project-file capture does not take canonical append/chat/publication or remote
refresh locks and therefore does not delay dispatch or Apply. Append-only chats
are captured only through a complete typed-valid JSONL byte boundary. Mutable
Paper, facts, and referenced kept files use bounded stable reads; continued
churn, a missing referenced file, an unsafe entry, or an unclassified durable
project root makes that project visibly uncaptured. A file created or replaced
after its observed boundary is absent, never claimed as half-captured.

Every archive records exact entry and total sizes and streams through fixed-size
buffers. Required scientific history is never silently truncated or subjected
to an arbitrary archive-size ceiling; retry and diagnostic outputs are bounded
in code, and insufficient staging or destination capacity produces an explicit
partial/failure outcome. Transfer uses its exact manifest size as the upload
lease boundary rather than loading the archive into browser or process memory.

Restore is a console workflow with integrity checks, replay verification, and
operator confirmation of the installed server's displayed configured
`RCP_DATA_DIR` and that the old copy of the space cannot resume serving; the
target may be an initialized team or uninitialized.
An initialized target gets a protected backup, closed admission, and a rollback
checkpoint, and returns to serving its previous data on pre-selection failure;
an uninitialized target stays stopped on that failure.
Restore defaults to the fixed root-only server identity and accepts
`--identity-file <absolute-path>` for an external identity or a fresh
replacement host. The private file is read only for that run; raw identity text
never enters argv, environment, progress, installed config, or restored data.
This first contract does not silently redirect systemd to a second data root. Before serving it
names the old source and project deploy-key labels/fingerprints,
server-to-remote SSH authorization, and provider-native login state that must be
revoked or proven destroyed, then names the replacement checkout and SSH routes
that data restoration requires. RCP
does not perform provider or SSH login/revocation and never asks for those
secrets.
An unknown newer archive or persistence boundary is rejected before target
mutation with the compatible-update requirement; an older restore binary never
best-effort interprets future data.
Restore preparation is bound to the archive and selected-release identity in
root-owned state outside application data. Decryption retains a protected,
bounded plaintext input readable only by root and the service group. Typed
archive validation, lifecycle detachment, checkout recovery, member policy and
project replay belong to the selected application's offline worker; it never
writes a deployment journal or selects a release. Root retains the exact
operator confirmations and preparation progress. A review or credential pause
returns an existing server to ordinary service; re-entry captures a fresh
rollback checkpoint and revalidates the prepared candidate before publication.
A fresh host remains stopped and needs no dummy team initialization.

It preserves `space_id`, converts captured active work to interrupted, and never
claims that RCP itself can prove the old authority is offline. Because provider
homes, the `providers` credential directory, run stages, and provider-native
conversation state are excluded, restore
marks every pre-restore task history-only, clears `writing_sessions` and
`chat_session_contexts`, and exposes no old native-session id as an executable
continuation. Task answers, receipts, RCP chat text, and Paper content remain
readable. A later message in the same RCP chat starts a fresh provider session
only after the configured account passes readiness.

Every restored browser session and unused bootstrap/team-enrollment code is
invalidated before startup. The snapshot's active permanent member-token hashes
remain so existing members can reconnect from their credential stores. Before
serving, restore shows the archive time and exact snapshot-time member roster and
requires operator confirmation; it never claims to know about a token rotation
or revocation that occurred after capture. A known stale credential keeps the
service closed until the operator chooses a safe newer archive or, when another
active enrolled member remains, removes that member through restore's explicit
offline console step. The step reuses the ordinary member-removal transaction
and completion fence under the stopped-service ownership lock after restored
work has been detached; it is not a second policy or a general offline database
editor. If the known-stale credential belongs to the only active member, the
last-member guard correctly refuses removal and restore remains stopped for a
separate human-identity recovery design outside this slice. Machine authority
cannot mint or impersonate a replacement member credential.

Restore also terminally detaches every nonterminal episode, report attempt,
external or graph watcher, automatic recovery, and child admission before the
ordinary startup path runs. Completed history remains readable, but the
replacement must prove that startup schedules no pre-restore provider turn,
watcher check/delivery, report retry, child admission, or automatic graph
mutation. A database snapshot is not treated as safe merely because its task
rows were interrupted.

Snapshotted in-progress provisioning and machine-operation leases are also
invalid on the replacement. Completed receipts remain history, while unfinished
project setup becomes **operator action needed** with old step claims cleared;
an interrupted backup/update is reported but never auto-resumed as though its
old process still had machine authority.

On a fresh installation, restore must reconstruct every captured central
checkout from Git before publishing its archived `.research` state. It uses the
recovery descriptor and the same repository-key/checkout helpers as project
provisioning, generates fresh repository-scoped keys on the exact local or
remote checkout account, and requires any remote SSH route to be re-established
and verified. It never extracts a source checkout from the archive or creates a
bare `.research/` directory where a later clone must go. If a clone already
contains retained RCP inputs, only byte-identical archive entries with no later
canonical commit are accepted; a conflict is not overwritten. Every captured
checkout, file group, and replay must validate before the replacement serves.
Any local bootstrap manifest is regenerated from the validated recovery
descriptor and the restored catalog row is rebound to the replacement checkout;
an old locator file or absolute path is never restored as authority.
Projects explicitly recorded as uncaptured remain visible but unavailable.

Provider-native login is not required to restore or read that durable history.
If the configured execution account is not authenticated, backend readiness
keeps new task dispatch and chat continuation unavailable and names the exact
provider-native login action. The operator performs that login outside RCP and
then asks RCP to recheck; missing provider auth is not reported as failed data
restore.

The fixed service-account layout, source installation, nonsecret desktop
connection registry, durable provisioning-request boundary, active protected
backup workflow, repository-scoped deploy-key primitive, exact central-checkout
owner, exact-account provider check, final human project creation, and strict
backup-manifest/read-only inventory boundary now exist. The installed service
also creates a private immutable online SQLite snapshot and derives typed
project, provisioning, task, and kept-file inventory only from that copy. The
backup boundary classifies every direct app-data and `.research` root, rejects
materialized or credential-bearing archive entries, binds a captured project to
its unchanged completed provisioning identity and checkout proof, while retaining
current Settings-owned manifest values, and can record a project as
uncaptured without refreshing remote state or taking a canonical writer lock.
It now consumes that immutable SQLite receipt to optimistically copy exact local
or SSH canonical main/branch history, typed chat prefixes, Paper introduction,
facts, and only SQLite-referenced kept files. Checkout identity and remote
direct-root inventories are revalidated without fetch or provider credentials;
one unavailable or continuously changing project becomes uncaptured while
healthy projects remain usable. It streams that captured boundary through
upstream `age` 1.x, atomically publishes and fully reads back the ciphertext and
immutable receipt, records durable protected/partial/failure status, deletes
only revalidated proven retention targets, and enables the systemd timer only
after a successful first run.

Protected restore uses the same supervisor operation and filesystem publication
protocol as release update. Before replacement, it validates the exact archive,
matching protected age identity, canonical manifest, every declared byte,
accepted schema boundary and full source identity. The app produces detached
candidate data, local canonical trees and typed kept-artifact/view payloads.
Rollback captures every existing destination and records absent destinations
without creating them. Additional local project, artifact and view roots are
fully copied before activation. Candidate artifact and view trees preserve
unrelated previous files through the same privileged copier before overlaying
validated archive content; publication replaces whole roots. A same-host remote root is reused only when it already matches the
archived bytes; divergent remote history refuses because local rollback cannot
undo remote writes. Fresh remote reconstruction requires explicit archived
old-authority review and the ordinary exact-account key/checkout grants.

Main/branch replay, imported-history integrity, member roster disposition, and
startup lifecycle detachment are application proofs, including explicit
unavailability for uncaptured projects. Root then publishes the verified
candidate under closed admission, runs its fenced live-state proof, durably
chooses it and opens the ordinary service. Interrupted publication rolls back
automatically before startup; after selection, recovery preserves accepted work.
Provider-native login remains separate from data restoration.

The private installed-service control socket retains probe, provider plan/check,
project provisioning and transfer operations, online SQLite capture, and member
removal. Protocol version 10 adds root-authenticated maintenance enter/status,
verify and release. Protocol version 12 requires an explicit compute probe route
while retaining versions 8 through 11 for other operations. Older clients do not
receive the probe operation in their advertised operation list. It contains no
update or restore coordinator.
Legacy source adoption is an explicit stopped-data path and does not pretend an older process
supports this maintenance protocol.

`rcp server project provision <request-id>` publishes one complete plan, advances one
stale-boundary-checked durable step at a time, and stops with a structured human
action when Git, checkout, transport, or provider readiness needs repair. It
exits successfully only after reading back the same request as **ready for
review**, and it has no project-creation route; only the authenticated final
review route can append the reserved identity and complete the request.

Machine orchestration, final creation, confirmed team catalog deletion, console
member removal, and replacement activation are
hermetically covered. Provisioning, cancellation after machine preparation, the
unified wizard and desktop operator bridge, live restore and member removal,
transfer, and protected backup have not been driven live against a source-built
team service. Current RCP must not simulate those journeys or describe
**ready for review** as an existing project.
