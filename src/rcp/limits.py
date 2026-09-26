from __future__ import annotations

# Operational storage retention and query bounds.
EPISODE_TIMELINE_EVENT_LIMIT = 400
EPISODE_TIMELINE_PREVIEW_MAX_LENGTH = 500
EPISODE_TIMELINE_HEADLINE_MAX_LENGTH = 240
EPISODE_TIMELINE_ERROR_MAX_LENGTH = 500
AGENT_TASK_LIST_DEFAULT_LIMIT = 20
AGENT_TASK_LIST_MAX_LIMIT = 100
# Chats whose latest turn is still moving or waiting on a person, listed beyond
# the recency limit so the Chats panel never loses one.
AGENT_TASK_LIST_OPEN_CHAT_LIMIT = 50
# How long such a chat's turn stays listed after it finishes, so an open client
# sees the terminal record and marks the result unread.
AGENT_TASK_LIST_FINISHED_CHAT_SECONDS = 600
AGENT_TASK_EVENT_LIST_DEFAULT_LIMIT = 200
AGENT_TASK_EVENT_LIST_MAX_LIMIT = 500
AGENT_TASK_EVENT_RETENTION_COUNT = 200
AGENT_TASK_RECEIPT_LIST_LIMIT = 112
AGENT_TASK_RECEIPT_RETENTION_COUNTS = {
    "summary": 64,
    "diagnostic": 32,
    "trace": 16,
}
AGENT_TASK_ESTIMATE_HISTORY_LIMIT = 100
AGENT_TASK_ESTIMATE_SAMPLE_LIMIT = 20
AGENT_TASK_RECEIPT_MAX_BYTES = 32 * 1024
# Episode ending receipts feed episode reports; they keep their own tighter budget.
EPISODE_RECEIPT_MAX_BYTES = 8 * 1024
AGENT_TASK_RESULT_MAX_BYTES = 64 * 1024
AGENT_COMMAND_EVENT_MAX_BYTES = 32 * 1024
PATCH_OUTPUT_RETENTION_DAYS = 7
RUN_TRACE_RETENTION_DAYS = 90
WRITING_SESSION_RETENTION_DAYS = 180
WRITING_SESSIONS_PER_PROJECT = 50

# Team enrollment and browser authentication.
TEAM_INVITATION_TTL_DAYS = 7
TEAM_CODE_FAILED_ATTEMPT_LIMIT = 5
TEAM_SESSION_IDLE_DAYS = 14
TEAM_PUBLIC_AUTH_REQUEST_MAX_BYTES = 4 * 1024
TEAM_ENROLLMENT_CODE_MAX_LENGTH = 128
TEAM_MEMBER_TOKEN_MAX_LENGTH = 64
TEAM_SESSION_TOKEN_MAX_LENGTH = 80
TEAM_SESSION_LABEL_MAX_LENGTH = 80
TEAM_DEVICE_PAIRING_TTL_MINUTES = 10
TEAM_DEVICE_PAIRING_CODE_MAX_LENGTH = 32
# Exact inventories are rendered into the bounded server CLI contract. Thirty-two
# identifiers fit in one nonsecret field; larger consequence sets must be reduced
# before an operator can confirm them safely.
MEMBER_REMOVAL_PREVIEW_MAX_ITEMS = 32

# Durable canonical chat history queries and summary labels.
CHAT_PAGE_DEFAULT_LIMIT = 50
CHAT_PAGE_MAX_LIMIT = 200
CHAT_TITLE_MAX_CHARS = 120
CHAT_PREVIEW_MAX_CHARS = 240
STEERING_MESSAGE_MAX_CHARS = 32_000
# One provider startup at a time per credential; see agents/credential_gate.py.
# The minimum outlives the provider's first line because neither CLI reports when
# it rotates its refresh token, and that call may follow the first line.
# One waiting attempt, not the whole wait: a waiter retries until it wins. Short
# enough that a queued startup hands its worker thread back well inside
# BACKGROUND_TASKS_SHUTDOWN_TIMEOUT_SECONDS.
PROVIDER_CREDENTIAL_ACQUIRE_SLICE_SECONDS = 0.5
PROVIDER_CREDENTIAL_STARTUP_MIN_HOLD_SECONDS = 2.0
# Generous, because it caps a hold rather than a startup: remote launches add an
# SSH round trip, and expiring mid-startup reopens the very race this closes.
PROVIDER_CREDENTIAL_STARTUP_TIMEOUT_SECONDS = 60.0
PROVIDER_STEER_WRITE_TIMEOUT_SECONDS = 10.0
PROVIDER_STEER_ACK_TIMEOUT_SECONDS = 30.0
PROVIDER_STDERR_DRAIN_TIMEOUT_SECONDS = 2.0
REMOTE_PROVIDER_PID_WAIT_SECONDS = 2.0
REMOTE_PROVIDER_TERM_WAIT_SECONDS = 5.0
REMOTE_PROVIDER_KILL_WAIT_SECONDS = 2.0
REMOTE_PROVIDER_STOP_POLL_SECONDS = 0.05
REMOTE_PROVIDER_STOP_TIMEOUT_SECONDS = 12.0

# Per-pass execution-host durability; overflow is an explicit incomplete turn.
TURN_JOURNAL_MAX_BYTES = 64 * 1024 * 1024
TURN_JOURNAL_MAX_EVENT_BYTES = 16 * 1024 * 1024
TURN_JOURNAL_MAX_STDERR_BYTES = 1024 * 1024
TURN_JOURNAL_MAX_PATCH_BYTES = 16 * 1024 * 1024
TURN_JOURNAL_MAX_UPLINK_BYTES = 1024 * 1024
TURN_JOURNAL_MAX_CONTROL_MESSAGES = 1024
# Experiment watcher maintenance snapshots a set the provider chose the size of,
# so the set is bounded as a whole and not only file by file. The count also
# bounds the digest map `outcome.json` carries, which the journal reader has to
# read back within its own limit.
TURN_JOURNAL_MAX_EXPERIMENT_WATCH_FILES = 64
TURN_JOURNAL_MAX_EXPERIMENT_WATCH_BYTES = 16 * 1024 * 1024
REMOTE_RESULT_RECONCILIATION_INTERVAL_SECONDS = 5.0

# Staged agent command mailbox, and the Auto-research broker that fronts it.
# The broker deliberately outwaits the client. Whichever side gives up first owns
# the diagnostic the agent reads, and the client's is the one that correctly says
# "unavailable" rather than blaming the request. Keep the grace positive, or a
# slow RCP starts reporting a perfectly good command as a broker-side failure.
COMMAND_MAILBOX_TIMEOUT_SECONDS = 30.0
COMMAND_MAILBOX_POLL_SECONDS = 0.2
COMMAND_BROKER_RESPONSE_GRACE_SECONDS = 5.0
AUTO_RESEARCH_PROMPT_FILE_MAX_BYTES = 16 * 1024
AUTO_RESEARCH_APPLY_MAX_PER_TURN = 32
# One turn's in-turn Applies plus the end-of-turn settlement disposition. The
# capture side and the storage side must agree, so it is derived once here.
GRAPH_UPDATE_HISTORY_MAX_COUNT = AUTO_RESEARCH_APPLY_MAX_PER_TURN + 1

# Temporary agent-created preview artifacts.
CHAT_ARTIFACT_MAX_COUNT = 8
ARTIFACT_CHAT_OPEN_TIMEOUT_MS = 5000
ARTIFACT_DISPLAY_TITLE_MAX_CHARS = 240
CHAT_ARTIFACT_MAX_FILE_BYTES = 16 * 1024 * 1024
CHAT_ARTIFACT_MAX_TOTAL_BYTES = 32 * 1024 * 1024
# One paid Auto-research mail wake carries only this bounded prefix. The byte limit
# stays well inside the reusable stage mailbox's per-file artifact ceiling.
AUTO_RESEARCH_MAIL_MAX_MESSAGES = 64
AUTO_RESEARCH_MAIL_MAX_BYTES = min(1024 * 1024, CHAT_ARTIFACT_MAX_FILE_BYTES)
# Let settlements that land together coalesce and let a graph-condition wake fired by the
# same settlement claim the notices first; every lifecycle wake waits at most this long.
AUTO_RESEARCH_LIFECYCLE_WAKE_GRACE_SECONDS = 5.0
AUTO_RESEARCH_LIFECYCLE_MAX_NOTICES = 50
AUTO_RESEARCH_LIFECYCLE_MAX_BYTES = 256 * 1024
# One authorized Auto-research turn may allocate this many child Experiments.
AUTO_RESEARCH_CHILD_EXPERIMENTS_PER_INVOCATION = 5
# Temporary human-provided chat inputs. Keep these independent from output artifact
# limits even while their initial bounds happen to be the same.
CHAT_ATTACHMENT_MAX_COUNT = 8
CHAT_ATTACHMENT_MAX_FILE_BYTES = 16 * 1024 * 1024
CHAT_ATTACHMENT_MAX_TOTAL_BYTES = 32 * 1024 * 1024
RUN_STAGE_RETENTION_DAYS = 7
REMOTE_ARTIFACT_READ_TIMEOUT_SECONDS = 30

# Human-requested repository source previews. These bytes are held only for the
# request and are never copied into RCP storage.
REPOSITORY_PREVIEW_MAX_BYTES = 2 * 1024 * 1024
REPOSITORY_PREVIEW_TIMEOUT_SECONDS = 30
# Lines kept on each side of a cited line when the file exceeds the byte limit.
REPOSITORY_PREVIEW_WINDOW_LINES = 100
COMPUTE_CONNECTION_MAX_COUNT = 32
ACTIVE_COMPUTE_ID_MAX_COUNT = COMPUTE_CONNECTION_MAX_COUNT
COMPUTE_JOB_LAUNCH_TIMEOUT_SECONDS = 20
COMPUTE_JOB_STATUS_TIMEOUT_SECONDS = 10
COMPUTE_PROBE_TIMEOUT_SECONDS = 15
COMPUTE_PROBE_JOB_SECONDS = 0.5
COMPUTE_JOB_LOG_TAIL_MAX_BYTES = 64 * 1024
# A helper launch re-checks its job once after this delay so startup failures
# (port in use, bad path) reach the agent in the launch response.
COMPUTE_JOB_STARTUP_CHECK_SECONDS = 2.0
COMPUTE_JOB_STARTUP_LOG_TAIL_BYTES = 2048
COMPUTE_JOB_LABEL_MAX_CHARS = 80
COMPUTE_JOBS_PER_PROJECT_LIST_LIMIT = 100
COMPUTE_JOB_DIAGNOSTIC_MAX_CHARS = 600
COMPUTE_JOB_POLL_INTERVAL_SECONDS = 0.05
REMOTE_RUN_STAGE_COMMAND_TIMEOUT_SECONDS = 60
# A probe resolves identity/facility, then may try mirrored and cooperative jobs.
# Each job includes root setup, launch, polling (including one in-flight pair
# of status/file reads past the poll deadline), log read, cancel and cleanup.
_COMPUTE_PROBE_RESPONSE_TIMEOUT_SECONDS = 4 * COMPUTE_JOB_STATUS_TIMEOUT_SECONDS + 2 * (
    7 * COMPUTE_JOB_STATUS_TIMEOUT_SECONDS
    + COMPUTE_JOB_LAUNCH_TIMEOUT_SECONDS
    + COMPUTE_PROBE_TIMEOUT_SECONDS
    + COMPUTE_JOB_POLL_INTERVAL_SECONDS
)
# Outwait cwd resolution, two mailbox listings, request read and response write;
# two probes if the first binding goes stale; both launch resolutions and the
# final launch/receipt or cleanup. The existing client/broker share this budget.
COMPUTE_COMMAND_TIMEOUT_SECONDS = (
    5 * REMOTE_RUN_STAGE_COMMAND_TIMEOUT_SECONDS
    + 2 * _COMPUTE_PROBE_RESPONSE_TIMEOUT_SECONDS
    + 10 * COMPUTE_JOB_STATUS_TIMEOUT_SECONDS
    + COMPUTE_JOB_LAUNCH_TIMEOUT_SECONDS
    # The startup check: its delay, then one refresh (alive + three reads) and a log read.
    + COMPUTE_JOB_STARTUP_CHECK_SECONDS
    + 5 * COMPUTE_JOB_STATUS_TIMEOUT_SECONDS
    + COMMAND_BROKER_RESPONSE_GRACE_SECONDS
)
SSH_REPOSITORY_BROWSER_MAX_ENTRIES = 200
SSH_REPOSITORY_BROWSER_TIMEOUT_SECONDS = 20

# Live patch self-validation through the run-stage file mailbox.
PATCH_SELF_CHECK_MAX_COUNT = 6
PATCH_SELF_CHECK_POLL_SECONDS = 0.2
PATCH_SELF_CHECK_TIMEOUT_SECONDS = 30
PATCH_SELF_CHECK_MAX_REQUEST_BYTES = 16 * 1024 * 1024

# Scratch-only correction rounds in the recovery ladder. Seed/Refresh, Work, and the
# Auto-research worker each hand validation errors back to the same live session at
# most this many times before the run is rejected. One number, one policy: raising it
# here raises it everywhere, which is the point.
PATCH_CORRECTION_MAX_ROUNDS = 2

# The Experiment loop corrects a watcher handoff once. Its deliverable is a joint
# Patch/watch admission, so a second round costs a full loop turn to re-decide
# what the first round already had every fact to fix.
EXPERIMENT_LOOP_WATCH_CORRECTION_MAX_ROUNDS = 1

# Durable external-work watchers.
WATCHER_CHECK_TIMEOUT_SECONDS = 15
WATCHER_POLL_INTERVAL_SECONDS = 5
ACCEPTANCE_AGENT_JOB_SECONDS = 2.0
WATCHER_CHECK_WORKERS = 4
WATCHER_ERROR_MAX_CHARS = 4000
WATCHER_HEALTHY_INTERVAL_SECONDS = 2 * 60
WATCHER_ERROR_BACKOFF_SECONDS = (2 * 60, 4 * 60, 8 * 60, 15 * 60, 30 * 60)
WATCHER_SCHEDULE_JITTER_RATIO = 0.10
WATCHER_GROUP_DIAGNOSTIC_ERROR_COUNT = 5

# Agent context budgets.
CHAT_CONVERSATION_LIMIT = 120
RUN_INLINE_SESSION_LIMIT = 40
RUN_INLINE_SESSION_BYTES = 12 * 1024
REFRESH_DELTA_MAX_ENTRIES = 50
REFRESH_DELTA_MAX_BYTES = 16 * 1024

# Rebuildable display/source caches and remote source operations.
PROJECT_DISPLAY_SNAPSHOT_MAX_BYTES = 16 * 1024 * 1024
REMOTE_STATE_HEAD_PROBE_INTERVAL_SECONDS = 3.0
REMOTE_STATE_HEAD_PROBE_TIMEOUT_SECONDS = 5.0
REMOTE_STATE_RECONCILE_WINDOW_SECONDS = 2.0
# Display-only routes may read a remote-state mirror this old; gating reads keep the window above.
REMOTE_STATE_DISPLAY_READ_MAX_AGE_SECONDS = 10.0
REMOTE_SOURCE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
REMOTE_SOURCE_CACHE_MAX_COUNT = 256
REMOTE_SOURCE_CACHE_MAX_BYTES = 1024 * 1024 * 1024
SESSION_SLICE_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60
SESSION_SLICE_CACHE_MAX_COUNT = 512
PROJECT_TRANSFER_SOURCE_PROBE_TIMEOUT_SECONDS = 30
PROJECT_TRANSFER_GIT_TIMEOUT_SECONDS = 600
PROJECT_TRANSFER_GIT_OUTPUT_MAX_BYTES = 16 * 1024 * 1024
SESSION_SLICE_CACHE_MAX_BYTES = 512 * 1024 * 1024
REMOTE_SOURCE_OPERATION_TIMEOUT_SECONDS = 180
SOURCE_ORIGINAL_COPY_BUFFER_BYTES = 1024 * 1024

# Personal-to-team transfer archives fail visibly when an inventory or diagnostic
# cannot be represented. Scientific payload bytes have no aggregate size ceiling;
# later capture/relay owners stream them with this fixed buffer instead.
PROJECT_TRANSFER_INVENTORY_MAX_ENTRIES = 100_000
PROJECT_TRANSFER_DIAGNOSTIC_MAX_COUNT = 128
PROJECT_TRANSFER_DIAGNOSTIC_MAX_CHARS = 4000
PROJECT_TRANSFER_MANIFEST_MAX_BYTES = 64 * 1024 * 1024
PROJECT_TRANSFER_COPY_BUFFER_BYTES = 1024 * 1024
PROJECT_TRANSFER_STABLE_READ_ATTEMPTS = 3

# SSH clients notice a dead peer within about a minute after a network change.
SSH_SERVER_ALIVE_INTERVAL_SECONDS = 15
SSH_SERVER_ALIVE_COUNT_MAX = 4

# How long a multiplexed master outlives its last client. The window only
# spares a follow-up call the cost of a fresh handshake; it never shortens a
# call in progress, because the timer does not run while a client is attached.
SSH_CONTROL_PERSIST_SECONDS = 60
# Asking a leftover mux socket whether anyone is still listening is a local
# connect, so anything slower than this is a socket that cannot answer.
SSH_CONTROL_PROBE_TIMEOUT_SECONDS = 1.0

# A run keeps its own SSH connection, so a dropped link ends that run and not
# its neighbours. It still ends it for a reason that has nothing to do with the
# work, so RCP reattempts such a turn a bounded number of times and then leaves
# it to a human, because a link still down after the last wait is not a
# transient stall. The waits grow so a host rebooting or a laptop changing
# networks has time to come back.
AGENT_TRANSPORT_RETRY_LIMIT = 3
AGENT_TRANSPORT_RETRY_BACKOFF_SECONDS = (30.0, 120.0, 600.0)

# A laptop sleeping with its lid closed still wakes for a few seconds at a time,
# too briefly to finish a remote launch (median 8 s, p90 14 s). Automatic
# launches wait until the machine has stayed awake this long since it last
# slept. Growth in the gap between a sleep-counting clock and a clock that
# skips sleep past the tolerance is a sleep; less is clock-read jitter.
AUTOMATIC_LAUNCH_AWAKE_SECONDS = 30.0
SLEEP_DETECTION_TOLERANCE_SECONDS = 2.0

# Canonical-state advisory lock acquisition and holder lifecycle.
STATE_LOCK_ATTEMPT_TIMEOUT_SECONDS = 30.0
# A read-side snapshot refresh gives up on a lock another run holds instead of
# blocking every reader of the project behind one stuck writer.
STATE_LOCK_REFRESH_WAIT_TIMEOUT_SECONDS = 20.0
STATE_LOCK_HOLDER_STOP_TIMEOUT_SECONDS = 5.0
STATE_LOCK_POLL_INTERVAL_SECONDS = 0.2
# Holder-enforced liveness tolerates command round trips and missed heartbeats.
STATE_LOCK_HOLDER_HEARTBEAT_INTERVAL_SECONDS = 10.0
STATE_LOCK_HOLDER_HEARTBEAT_TIMEOUT_SECONDS = 60.0

# Server and frontend-build lifecycle timings.
# Replacement outwaits request grace, both watcher joins, and background shutdown.
SERVER_SHUTDOWN_TIMEOUT_SECONDS = 60.0
# Request grace leaves room for lifespan teardown within the replacement window.
SERVER_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 10
# After uvicorn returns, request threads still in a bounded remote call get this
# long; then the process ends while it still holds its instance lock.
SERVER_THREAD_DRAIN_TIMEOUT_SECONDS = 5.0
BACKGROUND_TASKS_SHUTDOWN_TIMEOUT_SECONDS = 7.0
SERVER_LOCK_DEFAULT_TIMEOUT_SECONDS = 0.0
SERVER_LOCK_OWNER_READ_ATTEMPTS = 10
SERVER_LOCK_POLL_INTERVAL_SECONDS = 0.05
SERVER_HEALTH_REQUEST_TIMEOUT_SECONDS = 2
SERVER_INSTALL_PROBE_TIMEOUT_SECONDS = 30.0
SERVER_SUPERVISOR_COMMAND_TIMEOUT_SECONDS = 2 * 60 * 60.0
SERVER_INSTALL_ACCOUNT_TIMEOUT_SECONDS = 300.0
SERVER_INSTALL_SOURCE_TIMEOUT_SECONDS = 300.0
SERVER_INSTALL_BUILD_TIMEOUT_SECONDS = 30 * 60.0
SERVER_UPDATE_REHEARSAL_TIMEOUT_SECONDS = 30 * 60.0
SERVER_UPDATE_CHECKPOINT_TIMEOUT_SECONDS = 30 * 60.0
SERVER_INSTALL_SERVICE_TIMEOUT_SECONDS = 60.0
SERVER_INSTALL_HEALTH_TIMEOUT_SECONDS = 15.0
SERVER_INSTALL_HEALTH_POLL_INTERVAL_SECONDS = 0.25
SERVER_INSTALL_HEALTH_RESPONSE_MAX_BYTES = 64 * 1024
SERVER_GIT_CREDENTIAL_TIMEOUT_SECONDS = 30.0
SERVER_GIT_PROBE_TIMEOUT_SECONDS = 120.0
SERVER_PROJECT_CHECKOUT_TIMEOUT_SECONDS = 120.0
SERVER_BACKUP_CONFIGURATION_TIMEOUT_SECONDS = 30.0
SERVER_RESTORE_DECRYPT_TIMEOUT_SECONDS = 30 * 60.0
SERVER_CONTROL_IO_TIMEOUT_SECONDS = 5.0
SERVER_CONTROL_BACKUP_CAPTURE_TIMEOUT_SECONDS = 30 * 60.0
SERVER_CONTROL_UPDATE_MAINTENANCE_TIMEOUT_SECONDS = 2 * 60 * 60.0
SERVER_CONTROL_UPDATE_VERIFY_TIMEOUT_SECONDS = 5 * 60.0
SERVER_CONTROL_PROVIDER_CHECK_TIMEOUT_SECONDS = 60.0
# Machine and facility discovery, a probe job start, observation, and cleanup, with the
# mirrored-containment fallback running the job probe twice.
SERVER_CONTROL_COMPUTE_PROBE_TIMEOUT_SECONDS = 180.0
SERVER_CONTROL_PROJECT_PROVISION_TIMEOUT_SECONDS = 30 * 60.0
SERVER_CONTROL_ACCEPT_POLL_INTERVAL_SECONDS = 0.2
SERVER_CONTROL_STOP_TIMEOUT_SECONDS = 5.0
SERVER_WEB_BUILD_MAX_FILES = 8192
SERVER_WEB_BUILD_MAX_BYTES = 512 * 1024 * 1024

# Online team-server backup capture. Entry and diagnostic limits fail a capture
# visibly; they never truncate scientific history and call the result complete.
BACKUP_INVENTORY_MAX_ENTRIES = 100_000
BACKUP_STABLE_READ_ATTEMPTS = 3
BACKUP_COPY_BUFFER_BYTES = 1024 * 1024
BACKUP_SQLITE_PAGES_PER_STEP = 256
BACKUP_SQLITE_BUSY_SLEEP_SECONDS = 0.01
BACKUP_RECEIPT_MAX_BYTES = 64 * 1024 * 1024
BACKUP_REMOTE_EXPORT_TIMEOUT_SECONDS = 30 * 60.0
BACKUP_DIAGNOSTIC_MAX_COUNT = 128
BACKUP_DIAGNOSTIC_MAX_CHARS = 4000
# Keep one failed plaintext capture for diagnosis; a protected run removes it.
BACKUP_RETAINED_FAILED_CAPTURES = 1
BROWSER_OPEN_DELAY_SECONDS = 0.7
WEB_BUILD_TIMEOUT_SECONDS = 60.0
WEB_BUILD_STOP_TIMEOUT_SECONDS = 5.0
WEB_BUILD_POLL_INTERVAL_SECONDS = 0.05

# Bounded conversation worktree Git/SSH operations.
WORKTREE_GIT_TIMEOUT_SECONDS = 30

SERVER_SUPERVISOR_PROJECTION_MAX_BYTES = 16 * 1024

SERVER_SUPERVISOR_CHILD_STOP_TIMEOUT_SECONDS = 5.0
SERVER_SUPERVISOR_CHILD_WAIT_MIN_SECONDS = 0.1
SERVER_SUPERVISOR_PIPE_CHUNK_BYTES = 64 * 1024

PROVIDER_LOGIN_DETAIL_MAX_CHARS = 500
# A device-code sign-in the human never finishes is abandoned after this long;
# the provider's own code expires on the same order.
PROVIDER_SIGN_IN_TIMEOUT_SECONDS = 15 * 60
#: How long a canceled device sign-in may take to end before RCP stops it.
PROVIDER_SIGN_IN_CANCEL_GRACE_SECONDS = 5
PROVIDER_SIGN_OUT_TIMEOUT_SECONDS = 60
PROVIDER_TOKEN_PLACEMENT_TIMEOUT_SECONDS = 60
PROVIDER_TOKEN_MAX_CHARS = 4096
# A Claude setup token carries no expiry RCP can read; its documented lifetime
# is about one year, so the UI warns from eleven months after the paste.
PROVIDER_CLAUDE_TOKEN_ESTIMATED_LIFETIME_DAYS = 335

# A minimal authenticated sign-in request can outlast a metadata probe.
PROVIDER_LOGIN_VERIFY_TIMEOUT_SECONDS = 60

# Member terminal lifetime and bounded in-memory transport; no byte log is stored.
TERMINAL_IDLE_TIMEOUT_SECONDS = 30 * 60
TERMINAL_SWEEP_INTERVAL_SECONDS = 5.0
# Output admission is rechecked on this interval rather than per PTY chunk.
TERMINAL_OUTPUT_ADMISSION_INTERVAL_SECONDS = 1.0
TERMINAL_LAUNCH_TIMEOUT_SECONDS = 15.0
TERMINAL_PROBE_TIMEOUT_SECONDS = 30.0
TERMINAL_PROBE_COMMAND_TIMEOUT_SECONDS = 5.0
TERMINAL_PROBE_WORKERS = 4
# Probes run on their own threads, not the interpreter's shared default pool,
# which the rest of the application uses for every other blocking call. A probe
# cannot be stopped once it is in its thread, so one abandoned by a refresh
# runs out its own timeout above; on the shared pool a burst of refreshes
# against unreachable machines could therefore hold up unrelated work. This
# bounds what probes can hold, with room above the admitted count for the ones
# a burst abandons, so the newest answer still finds a thread.
TERMINAL_PROBE_THREADS = 16
TERMINAL_STOP_TIMEOUT_SECONDS = 5.0
# Stops run on their own threads, not the interpreter's shared default pool,
# which the rest of the application uses for every other blocking call. Ending
# a project's worth of shells at once is only as concurrent as the pool it runs
# on, and a stop against a machine that has gone spends its own timeout while
# its caller holds the instance lock. This admits a realistic project's worth
# at once; beyond it they still queue, but never behind unrelated work.
TERMINAL_STOP_THREADS = 32
# Startup reconciles every record at once, but their stops run in a shared
# thread pool, so enough unreachable records still queue into timeout-sized
# batches. This bounds what they can cost the boot; whatever has not finished
# keeps its record and blocks its repository, and a later attempt retries it.
TERMINAL_STARTUP_RECONCILE_TIMEOUT_SECONDS = 30.0
TERMINAL_POLL_INTERVAL_SECONDS = 0.05
TERMINAL_OUTPUT_BUFFER_BYTES = 256 * 1024
TERMINAL_SUBSCRIBER_QUEUE_SIZE = 64
TERMINAL_IO_CHUNK_BYTES = 16 * 1024
TERMINAL_MAX_DIMENSION = 1000

# Public release metadata polling, shared by the app and the explicit doctor lookup.
RELEASE_CHECK_START_DELAY_SECONDS = 5.0
RELEASE_CHECK_INTERVAL_SECONDS = 6 * 60 * 60
RELEASE_CHECK_DEADLINE_SECONDS = 10.0
RELEASE_CHECK_MAX_BYTES = 256 * 1024
RELEASE_CHECK_MAX_REDIRECTS = 3
