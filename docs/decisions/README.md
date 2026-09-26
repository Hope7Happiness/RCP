# Active decision records

- [Desktop installs follow releases](2026-09-26-desktop-installs-follow-releases.md)
  records why desktop and local Web installs follow promoted releases like
  team servers, why each release ships an unsigned prebuilt app in a companion
  pre-release, why RCP skips Apple signing, and why updates are notified
  rather than applied.

- [Job managers add rules, never remove the helper](2026-09-25-job-managers-add-rules-never-remove-the-helper.md)
  records why the launch helper stays offered on machines set to Slurm, and
  why each job manager adds its own instructions instead of replacing it.

- [Team launches carry Git transport, including Discuss](2026-09-24-team-launches-carry-git-transport.md)
  records why every team launch carries its repository's deploy key, why RCP
  supplies a default commit identity, and what that gives up: membership is
  write access, authorship is unverified, and Discuss can push.

- [Graph rules render from the model](2026-09-23-graph-rules-render-from-the-model.md)
  records why agents learn field and relation meaning from descriptions in code
  rendered into every graph contract, why authority stays with each call site,
  and why continuations repeat the rules unless their digest changed.

- [A member terminal inherits the Work turn's trust boundary](2026-09-19-a-member-terminal-inherits-the-work-trust-boundary.md)
  records why a project terminal runs as the service account without isolation,
  why the safer-sounding fence was rejected, and why it must never describe
  itself as containment.

- [Provider logins are kept alive](2026-09-14-provider-logins-are-kept-alive.md)
  records why every credential gets one refresh path and no needless process
  (Codex per turn under the gate, Claude on a static token), why the shared
  owner process is deferred, how sign-in moves into the RCP UI, and what that
  reverses in the operator and authority docs.

- [Reauthorization continues on the same branch](2026-09-14-reauthorization-continues-on-the-same-branch.md)
  records why adding turns creates a continuation episode chained to the ended
  one on the same branch and session, instead of a new branch or a reopened row.

- [A branch merges on branch facts](2026-09-14-a-branch-merges-on-branch-facts.md)
  records why merge eligibility depends on the branch head and its writers alone
  and no longer on the episode's lifecycle.

- [Reconciler failures are durable state](2026-09-14-reconciler-failures-are-durable-state.md)
  records why a lifecycle step that cannot complete is written on the episode
  once and shown, instead of being retried and logged forever.

- [Agents retire graph conditions](2026-09-13-agents-retire-graph-conditions.md)
  records why an agent withdraws a canonical condition the same way it withdraws
  an observer, why the human control's narrower scope is not an argument against
  it, and which question about an ended episode stays open.

- [Claude Work runs without the OS sandbox](2026-09-13-claude-work-runs-without-the-os-sandbox.md)
  records why that sandbox is off for one provider, what enforces write roots
  instead, the shell gap this accepts, and why re-enabling it is not a cleanup.

- [Graph-branch scope is reopened](2026-09-08-graph-branch-scope-is-reopened.md)
  retires the outright rejection of a version-control model for the research
  graph, fixes what human authority keeps, and puts the deterministic merge core
  first.

- [Graph authoring and product boundaries](2026-09-05-graph-authoring-and-product-boundaries.md)
  records glossary authoring, validator advice, human graph editing and the
  explicit exclusions replacing the retired open-question register.

- [Servers install promoted release artifacts through an external supervisor](2026-09-02-deployment-moves-to-an-external-supervisor.md)
  records one CI build per merge, human promotion to `stable` without rebuild,
  thirty-day build retention, a Python supervisor that imports nothing from
  `rcp`, going public inside that work, and the deletion of the in-app update
  and restore control plane.

- [The native team entrance negotiates one thin protocol range](2026-09-01-team-shell-handshake-compatibility.md)
  records the live highest-overlap handshake, source-commit diagnostics,
  immutable per-version contracts, and removal of persisted compatibility state.

- [Team spaces use desktop-owned pinned local HTTPS origins](2026-08-30-desktop-local-https-origins.md)
  records the deterministic per-connection host, sealed desktop identity with a
  Keychain-held key, app-scoped certificate pin, and independent navigation and
  capability fences.

- [Personal-to-team transfer uses one bounded project archive](2026-08-27-personal-to-team-transfer-archive.md)
  records the sole transfer format, complete finished and provider-history
  boundary, independent source/target human authority, removal of source
  execution bindings, and validated atomic target import.

- [Source server uses staged releases and split operator/service privilege](2026-08-27-source-server-install-and-update-privilege.md)
  records the disposable bootstrap, clean per-commit releases, unprivileged
  source builds, and narrow root coordinator for systemd lifecycle.

- [Every server-era schema remains directly upgradeable](2026-08-27-server-schema-compatibility.md)
  records permanent one-step upgrade support and one immutable fixture bundle
  per distinct persistence boundary.

- [Codex app-server is a profile runtime](2026-08-25-codex-app-server-runtime.md)
  records per-profile selection, per-invocation evidence, the exact pre-prompt
  fallback boundary, and why RCP does not own a persistent provider-session
  runtime or Codex Desktop ordering.

- [Backend structural refactor closure](2026-08-20-backend-structural-refactor-closure.md)
  records the deliberately retained engine/owner coupling, ordinary-Work fallback
  for an unproven child route, and the decision not to extract more control layers
  from `api/app.py` without measured need.

Decision records explain rationale that remains materially useful for an active
migration, live tradeoff, or easy-to-regress architectural boundary. They link to
the current specification that owns behavior and never override design or specs.
Archive a decision after its rationale no longer needs active implementation
attention.
