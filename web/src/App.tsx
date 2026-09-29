import { UpdateNotice } from "./components/UpdateNotice";
import { useUpdateNotice } from "./hooks/useUpdateNotice";
import { TerminalTab } from "./components/TerminalTab";
import { branchMergeStateLabel } from "./components/CampaignRuns";
import {
  graphSessionKey,
  graphTargetFromHash,
  graphTargetUrl,
  graphViewHash,
  MAIN_GRAPH,
  sameGraphTarget,
} from "./graphTarget";
import type { GraphEditingProps } from "./components/GraphEditingControls";
import {
  AlertTriangle,
  ArrowLeft,
  CloudUpload,
  ChevronDown,
  ChevronUp,
  FileText,
  FlaskConical,
  FolderLock,
  Files,
  GitBranch,
  History,
  Inbox,
  LayoutList,
  LoaderCircle,
  MessageCircle,
  Network,
  RefreshCw,
  RotateCcw,
  Settings2,
  Telescope,
  TerminalSquare,
  X,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { isActiveTask } from "./agentTasks";
import { mergeProviderLogins } from "./providers";
import { loadChatTranscript } from "./chatApi";
import { listenForArtifactChatNavigation } from "./artifactChatNavigation";
import {
  chatIndicator,
  chatEntryConversationId,
  groupChatConversations,
  startConversationTurn,
  unsentConversation,
  type ChatKind,
  type ConversationTurnSubmission,
} from "./chatWorkspace";
import {
  api,
  archiveEpisode,
  ApiError,
  loadEpisodes,
  loadProjectReadiness,
  loadProviderLogins,
  mergeEpisodeToMain,
  continueEpisode,
  sendEpisodeMessage,
  startEpisode,
  stopEpisode,
} from "./api";
import {
  BACKEND_IDENTITY_EVENT,
  backendReconnectLabel,
  desktopShowReady,
  setDesktopWebviewZoom,
  isDesktopRuntime,
  listenDesktopEvent,
  returnDesktopToPersonal,
  TEAM_TRANSPORT_RECOVERED,
  type BackendIdentityEventDetail,
} from "./desktopRuntime";
import {
  projectGraphMutationFailureLabel,
  projectGraphMutationsDisabled,
  taskMayMutateGraph,
} from "./graphAuthority";
import { buildGlossaryIndex } from "./glossary";
import {
  experimentBoardRouteToken,
  experimentIndexEntryForRoute,
  experimentStopPath,
  mainExperimentRouteMatchesControl,
  parseProjectHash,
  projectExperimentExecution,
  projectRunsNeedsExperimentIndex,
  type ProjectHashRoute,
} from "./experimentBoard";
import {
  decodeTransitionTriggerManifest,
  reduceProjectTransitionProjection,
  transitionHeadsEqual,
  transitionPreviewRouting,
  transitionSnapshotRefusal,
  transitionSyncCompletionDisposition,
  type ProjectTransitionProjection,
  type StagedTransitionEdit,
  type TransitionPreviewRouting,
} from "./projectTransition";
import { nodeDetailSizeStorageKey, type DetailWindowSlot } from "./floatingWindow";
import { episodeReportPreviewUrl } from "./campaigns";
import {
  cloneAgentTasksSnapshot,
  useAgentTasks,
  type AgentTasksSnapshot,
} from "./hooks/useAgentTasks";
import { useActorIdentity } from "./hooks/useActorIdentity";
import {
  cloneChatStateSnapshot,
  experimentChatFreshnessToken,
  useChatState,
  visibleChatTranscriptIds,
  visibleUnreadChatId,
  type ChatStateSnapshot,
} from "./hooks/useChatState";
import { useDesktopShell } from "./hooks/useDesktopShell";
import { startLiveEpisodePolling, useEpisodeDialogs } from "./hooks/useEpisodeDialogs";
import {
  emptyGraph,
  useGraphSelection,
  type GraphSelectionTabSnapshot,
} from "./hooks/useGraphSelection";
import {
  cloneProjectHistorySnapshot,
  useProjectHistory,
  validationNoticeId,
  type ProjectHistorySnapshot,
} from "./hooks/useProjectHistory";
import {
  EXPERIMENT_BOARD_POLL_DELAY_MS,
  startProjectCachePolling,
  useProjectTabs,
} from "./hooks/useProjectTabs";
import {
  cachedSnapshotCanReplace,
  canonicalGraphHead,
  latestSnapshotRequestCanApply,
  persistProjectHumanDraft,
  projectDraftPreviewEffectInputs,
  projectHeartbeatSnapshotDisposition,
  projectHeartbeatMetadataChanged,
  projectSettingsSavedProject,
  reconcileInactiveProjectSession,
  RETAIN_ALL_PROJECT_READINESS,
  serializeProjectSessionTabState,
  trustedProjectTransitionManifest,
  type BrowserTransitionProjection,
  type ProjectReadinessRetention,
  type ProjectSessionTabState,
} from "./hooks/projectSession";
import { useProjectSession } from "./hooks/useProjectSession";
import { AutoResearchDialog } from "./components/AutoResearchDialog";
import { AgentTaskInspector } from "./components/AgentTaskInspector";
import { AttentionRail, ProposalJudgmentSection } from "./components/AttentionRail";
import { DetailDrawer } from "./components/DetailDrawer";
import { DraggableWindow } from "./components/DraggableWindow";
import { ProjectHistoryDrawer } from "./components/ProjectHistoryDrawer";
import { ProjectDock } from "./components/ProjectDock";
import { RunDialog } from "./components/RunDialog";
import { TeamLoginBoundary } from "./components/TeamLoginBoundary";
import {
  applyHumanDraft,
  deserializeHumanDraft,
  draftNodeIsBehind,
  humanDraftBehindCount,
  humanDraftChangeCount,
  humanDraftCommittableCount,
  humanDraftOntologyIsStale,
  humanDraftStorageKey,
  humanSyncFailure,
  normalizeHumanDraft,
  stageDecisionChoice,
  stageNodeEdit,
  stageNodeEditStart,
  stageNodeRemoval,
  stageNodeStanding,
  stageProposalDecision,
  stageCustomNode,
  stageEdgeAddition,
  stageEdgeRemoval,
  unstageEdgeRemoval,
  unstageCustomNode,
  unstageNodeRemoval,
  toHumanSyncRequest,
  type HumanDraft,
  type HumanSyncRequest,
} from "./humanDraft";
import type {
  AgentExecutionProfile,
  AgentRunConfig,
  AgentTask,
  AgentTaskKind,
  AgentTaskRequest,
  AgentUsageSnapshot,
  AppView,
  Episode,
  ExperimentControlState,
  GraphAttentionProjection,
  GraphHeadRef,
  GraphRevisionSnapshot,
  GraphNode,
  GraphState,
  GraphTargetRef,
  Health,
  PaperSnapshot,
  ProjectCard,
  ProjectInvitation,
  ProjectSnapshot,
  ProviderLoginState,
  ProjectTransitionResponse,
  TransitionPreviewResponse,
  TransitionTriggerManifest,
  TrustView,
  WatcherRecord,
} from "./types";
import { decodeProjectTransitionResponse, DISPLAY_NAME_MAX_LENGTH } from "./types";
import { ProjectLanding } from "./views/ProjectLanding";
import { ProjectOverview } from "./views/ProjectOverview";
import { ProjectSetup } from "./views/ProjectSetup";
import {
  parseProjectSetupRoute,
  projectMoveSetupHash,
  type ProjectSetupRoute,
} from "./projectSetup";
import {
  changeTextScale,
  normalizeTextScale,
  TEXT_SCALE_STORAGE_KEY,
  textScaleShortcut,
  type TextScaleAction,
} from "./textScale";
import { useTheme } from "./hooks/useTheme";
import { NOTICE_TIMEOUT_MS } from "./uiConstants";
import {
  createWebMcpToolRegistry,
  projectArtifactToolDefinitions,
  projectConversationSendToolDefinitions,
  projectConversationToolDefinitions,
  projectExperimentStopToolDefinitions,
  projectExperimentToolDefinitions,
  projectIndexToolDefinitions,
  projectReadToolDefinitions,
  type WebMcpToolRegistry,
  webMcpSurface,
} from "./webmcp";

import { initialProjectHash, isEditableShortcutTarget, projectTabShortcut } from "./projectTabs";

const PROVIDER_SKILL_READINESS_POLL_DELAY_MS = 1_000;
const PROVIDER_SKILL_READINESS_MAX_FOLLOW_UPS = 20;

interface ProviderReadinessRequestState {
  pending: boolean;
  providerError: string | null;
  computeError: string | null;
}

type ProjectReadinessSnapshot = Awaited<ReturnType<typeof loadProjectReadiness>>;

interface ProviderReadinessInFlight {
  refresh: boolean;
  generation: ProjectReadinessGeneration;
  request: Promise<ProjectReadinessSnapshot | null>;
}

/** Separate request generations for the provider and compute readiness slices. */
export interface ProjectReadinessGeneration {
  provider: number;
  compute: number;
}

const INITIAL_PROJECT_READINESS_GENERATION: ProjectReadinessGeneration = {
  provider: 0,
  compute: 0,
};

export function currentProjectReadinessGeneration(
  generations: ReadonlyMap<string, ProjectReadinessGeneration>,
  projectId: string,
): ProjectReadinessGeneration {
  return generations.get(projectId) ?? INITIAL_PROJECT_READINESS_GENERATION;
}

/** Advance the request generation of every readiness slice this retention drops. */
export function invalidateProjectReadinessGenerations(
  generations: Map<string, ProjectReadinessGeneration>,
  projectId: string,
  retention: ProjectReadinessRetention,
): ProjectReadinessGeneration {
  const current = currentProjectReadinessGeneration(generations, projectId);
  const next = {
    provider: current.provider + (retention.provider ? 0 : 1),
    compute: current.compute + (retention.compute ? 0 : 1),
  };
  generations.set(projectId, next);
  return next;
}

/**
 * Which slices of one readiness response are still current.
 *
 * A resolve invalidates provider readiness alone, so an in-flight compute probe
 * that answers afterwards still carries the live matrix.
 */
export function projectReadinessResponseApplies(
  generations: ReadonlyMap<string, ProjectReadinessGeneration>,
  projectId: string,
  requestGeneration: ProjectReadinessGeneration,
): ProjectReadinessRetention {
  const current = currentProjectReadinessGeneration(generations, projectId);
  return {
    provider: current.provider === requestGeneration.provider,
    compute: current.compute === requestGeneration.compute,
  };
}

export function projectReadinessUpdate(
  readiness: ProjectReadinessSnapshot,
  applies: ProjectReadinessRetention,
): Partial<ProjectReadinessSnapshot> {
  return {
    ...(applies.compute ? { compute_status: readiness.compute_status } : {}),
    ...(applies.provider
      ? {
          provider_logins: readiness.provider_logins,
          provider_readiness: readiness.provider_readiness,
          providers: readiness.providers,
          provider_skill_inventories: readiness.provider_skill_inventories,
          // Profiles resolve their unnamed model against this catalog, so a
          // refresh that changes the head re-exports them with it.
          agent_profiles: readiness.agent_profiles,
        }
      : {}),
  };
}

/**
 * Whether one failed readiness response may still write shared request state.
 *
 * A failure carries no slice data, so it speaks for the project only while it
 * is the registered request. A replaced request must stay silent: the `finally`
 * that clears `pending` runs only for the registered request, so a late failure
 * would otherwise leave readiness controls disabled until reload.
 */
export function projectReadinessFailureApplies(
  registered: boolean,
  applies: ProjectReadinessRetention,
): boolean {
  return registered && (applies.provider || applies.compute);
}

/**
 * The request state after one failed readiness response.
 *
 * The failure reports only for the slices this request still owns. A slice a
 * later edit superseded keeps whatever its own newer decision left behind.
 * `pending` stays true because only a registered request reaches here.
 */
export function projectReadinessFailureState(
  previous: ProviderReadinessRequestState | undefined,
  applies: ProjectReadinessRetention,
  message: string,
): ProviderReadinessRequestState {
  return {
    pending: true,
    providerError: applies.provider ? message : (previous?.providerError ?? null),
    computeError: applies.compute ? message : (previous?.computeError ?? null),
  };
}

export function shouldPollProviderSkillReadiness(
  inventories: ProjectSnapshot["provider_skill_inventories"] | undefined,
  completedFollowUps: number,
): boolean {
  return (
    inventories !== undefined &&
    completedFollowUps < PROVIDER_SKILL_READINESS_MAX_FOLLOW_UPS &&
    Object.values(inventories).some((providers) =>
      Object.values(providers).some((inventory) => inventory?.status === "refreshing"),
    )
  );
}

export function shouldRequestProviderReadiness(
  readiness: ProjectSnapshot["provider_readiness"],
  pending: boolean,
): boolean {
  return (
    !pending && !Object.values(readiness).some((providers) => Object.keys(providers).length > 0)
  );
}

const AttentionOverview = lazy(() =>
  import("./views/GraphViews").then((module) => ({ default: module.AttentionOverview })),
);
const DagView = lazy(() =>
  import("./views/GraphViews").then((module) => ({ default: module.DagView })),
);
const ExecutionView = lazy(() =>
  import("./views/GraphViews").then((module) => ({ default: module.ExecutionView })),
);
const ScientificView = lazy(() =>
  import("./views/GraphViews").then((module) => ({ default: module.ScientificView })),
);
const PaperWorkspace = lazy(() =>
  import("./views/PaperWorkspace").then((module) => ({ default: module.PaperWorkspace })),
);
const ProjectSettings = lazy(() =>
  import("./views/ProjectSettings").then((module) => ({ default: module.ProjectSettings })),
);
const ChatsWorkspace = lazy(() =>
  import("./views/ChatsWorkspace").then((module) => ({ default: module.ChatsWorkspace })),
);
const NodeChat = lazy(() =>
  import("./components/NodeChat").then((module) => ({ default: module.NodeChat })),
);

const Artifacts = lazy(() =>
  import("./views/Artifacts").then((module) => ({ default: module.Artifacts })),
);

const Terminals = lazy(() =>
  import("./views/Terminals").then((module) => ({ default: module.Terminals })),
);

const navItems: Array<{ view: AppView; label: string; icon: React.ReactNode }> = [
  { view: "overview", label: "Overview", icon: <LayoutList size={14} /> },
  { view: "attention", label: "Inbox", icon: <Inbox size={14} /> },
  { view: "scientific", label: "Research", icon: <GitBranch size={14} /> },
  { view: "execution", label: "Runs", icon: <FlaskConical size={14} /> },
  // Paper is a sub-panel of Artifacts; its route stays `paper`.
  { view: "artifacts", label: "Artifacts", icon: <Files size={14} /> },
  { view: "terminals", label: "Terminals", icon: <TerminalSquare size={14} /> },
  { view: "chats", label: "Agents", icon: <MessageCircle size={14} /> },
  { view: "settings", label: "Settings", icon: <Settings2 size={14} /> },
];

/** A tab stays highlighted while one of its sub-views is open. */
function navItemActive(item: AppView, view: AppView): boolean {
  return (
    view === item ||
    (item === "scientific" && view === "dag") ||
    (item === "artifacts" && view === "paper")
  );
}

function ArtifactsSubnav({
  view,
  paperUnsynced,
  onChange,
}: {
  view: AppView;
  paperUnsynced: boolean;
  onChange: (view: AppView) => void;
}) {
  return (
    <div className="artifacts-subnav" role="group" aria-label="Artifacts sections">
      {(
        [
          ["artifacts", "Files"],
          ["paper", "Paper"],
        ] as const
      ).map(([target, label]) => (
        <button
          key={target}
          type="button"
          aria-pressed={view === target}
          onClick={() => onChange(target)}
        >
          {target === "paper" ? <FileText size={13} /> : <Files size={13} />}
          {label}
          {target === "paper" && paperUnsynced && <small>1</small>}
        </button>
      ))}
    </div>
  );
}

export async function loadGraphRevision(
  fetchJson: <T>(path: string) => Promise<T>,
  apiBase: string,
): Promise<GraphRevisionSnapshot> {
  return fetchJson<GraphRevisionSnapshot>(`${apiBase}/cached/revision`);
}

/**
 * Open a project in two steps: the cached display snapshot paints first when the
 * session accepts it, and the authoritative reload always follows and finishes
 * the open. A cached snapshot the session declines — a newer snapshot request
 * already started, such as the active-tab heartbeat's reload, or a stale
 * revision — must never end the open early, or the view keeps its spinner with
 * nothing left to clear it.
 */
export async function openProjectSequence(steps: {
  applyCachedSnapshot: () => Promise<void>;
  reloadAuthoritative: () => Promise<void>;
  stillOpening: () => boolean;
  settle: () => void;
}): Promise<void> {
  await steps.applyCachedSnapshot();
  if (!steps.stillOpening()) return;
  try {
    await steps.reloadAuthoritative();
  } finally {
    if (steps.stillOpening()) steps.settle();
  }
}

export function canonicalRevisionNeedsReload(
  observedRevision: number,
  renderedRevision: number,
  observedMutation?: ProjectSnapshot["graph_mutation"],
  renderedMutation?: ProjectSnapshot["graph_mutation"],
): boolean {
  return (
    observedRevision > renderedRevision ||
    Boolean(
      observedMutation &&
      renderedMutation &&
      (observedMutation.available !== renderedMutation.available ||
        observedMutation.reason !== renderedMutation.reason),
    )
  );
}

function pageIsHidden(): boolean {
  return document.visibilityState === "hidden";
}

export function AcceptanceAgentIndicator({
  agentMode,
}: {
  agentMode: Health["agent_mode"] | null | undefined;
}) {
  if (agentMode !== "acceptance") return null;
  return (
    <aside className="acceptance-agent-indicator" role="status" aria-live="polite">
      <strong>Fake acceptance agent active</strong>
      <span>Acceptance mode · no real provider calls</span>
    </aside>
  );
}

export async function projectIsStillReadable(
  fetchJson: <T>(path: string) => Promise<T>,
  projectId: string,
): Promise<boolean> {
  // The project index is already filtered to what the caller may see, so its
  // answer covers both a deleted project and one that is no longer ours.
  // A failure to ask is not an answer: keep the tab.
  try {
    const cards = await fetchJson<ProjectCard[]>("/api/projects");
    return cards.some((card) => card.id === projectId);
  } catch {
    return true;
  }
}

export function terminalTaskNeedsAuthoritativeProjectReload(task: AgentTask): boolean {
  return (
    task.kind === "branch_merge" ||
    Boolean(task.applied_revision) ||
    task.request.patch_kind === "experiment_loop"
  );
}

export function experimentControlsNeedWrapupPolling(
  controls: Readonly<Record<string, Pick<ExperimentControlState, "health">>>,
): boolean {
  return Object.values(controls).some((control) => control.health === "wrapping_up");
}

export function activeBranchMergeTask(episode: Episode): AgentTask | null {
  const operationId = episode.graph_branch?.active_merge_task_id;
  if (!operationId) return null;
  return (
    episode.tasks.find(
      (task) =>
        task.operation_id === operationId && task.kind === "branch_merge" && isActiveTask(task),
    ) ?? null
  );
}

export function taskActionNeedsAuthoritativeProjectReload(
  task: AgentTask,
  action: "pause" | "resume" | "retry",
): boolean {
  return task.request.patch_kind === "experiment_loop" && action !== "pause";
}

export function humanAttentionBlockers(
  blockerIds: readonly string[],
  presentedNodes: GraphState["nodes"],
): GraphNode[] {
  return blockerIds.map((nodeId) => {
    const node = presentedNodes[nodeId];
    if (node?.type !== "blocker") {
      throw new Error(`Attention member ${nodeId} is not a presented Blocker.`);
    }
    return node;
  });
}

export function decisionsAwaitingChoice(
  decisionIds: readonly string[],
  membershipNodes: GraphState["nodes"],
  presentedNodes: GraphState["nodes"],
): GraphNode[] {
  return decisionIds.map((nodeId) => {
    const membershipNode = membershipNodes[nodeId];
    const presented = presentedNodes[nodeId] ?? membershipNode;
    if (membershipNode?.type !== "decision" || presented?.type !== "decision") {
      throw new Error(`Attention member ${nodeId} is not a presented Decision.`);
    }
    return { ...presented, status: membershipNode.status };
  });
}

export async function loadExperimentWatcherPoll(
  fetchJson: <T>(path: string) => Promise<T>,
  base: string,
  graphTarget: GraphTargetRef = MAIN_GRAPH,
): Promise<{
  watchers: WatcherRecord[];
  tasks: AgentTask[];
  project: ProjectSnapshot;
}> {
  const [watchers, tasks, project] = await Promise.all([
    fetchJson<WatcherRecord[]>(graphTargetUrl(`${base}/watchers`, graphTarget)),
    fetchJson<AgentTask[]>(`${base}/tasks`),
    fetchJson<ProjectSnapshot>(graphTargetUrl(base, graphTarget)),
  ]);
  return { watchers, tasks, project };
}

type ProjectReconciliation = "opening" | "reconciling" | "authoritative" | "failed";

const EMPTY_GRAPH_ATTENTION: GraphAttentionProjection = {
  pending_proposal_ids: [],
  decisions_awaiting_choice_ids: [],
  open_blocker_ids: [],
  proposal_actions: {},
  decision_prior_choices: {},
};

export function projectAttentionForPresentation(
  project: ProjectSnapshot | null,
  projection: BrowserTransitionProjection | null,
): GraphAttentionProjection {
  if (projection) {
    if (!projection.attention) {
      throw new Error("Transition projection omitted graph attention.");
    }
    return projection.attention;
  }
  if (project) {
    if (!project.attention) {
      throw new Error("Project snapshot omitted graph attention.");
    }
    return project.attention;
  }
  return EMPTY_GRAPH_ATTENTION;
}

export {
  cachedSnapshotCanReplace,
  canonicalGraphHead,
  latestSnapshotRequestCanApply,
  persistProjectHumanDraft,
};

export function experimentStartNeedsSync(projection: BrowserTransitionProjection | null): boolean {
  return projection?.base_head != null;
}

interface CachedProjectTabState
  extends
    ProjectHistorySnapshot,
    AgentTasksSnapshot,
    ChatStateSnapshot,
    GraphSelectionTabSnapshot,
    ProjectSessionTabState {
  project: ProjectSnapshot;
  projectHeaderCollapsed: boolean;
  usage: AgentUsageSnapshot | null;
  watchers: WatcherRecord[];
}

export function attentionGraphForProjection(
  canonicalGraph: GraphState,
  projection: BrowserTransitionProjection | null,
  route: TransitionPreviewRouting["route"] = "backend_preview",
  draft: HumanDraft | null = null,
): GraphState {
  if (route === "local_draft") return applyHumanDraft(canonicalGraph, draft);
  return projection?.graph ?? canonicalGraph;
}

export function transitionProjectionForRoute(
  projection: BrowserTransitionProjection | null,
  route: TransitionPreviewRouting["route"],
): BrowserTransitionProjection | null {
  return route === "backend_preview" ? projection : null;
}

export function humanDraftTransitionRouting(
  draft: HumanDraft,
  graph: GraphState,
  manifest: TransitionTriggerManifest | null,
  rulesetTag: string | null,
): TransitionPreviewRouting {
  const request = toHumanSyncRequest(draft, graph);
  const edits: StagedTransitionEdit[] = request.nodes.map((item) => ({
    operation: "update_nodes",
    node_types: graph.nodes[item.node_id] ? [graph.nodes[item.node_id].type] : undefined,
    node_fields: [
      ...Object.keys(item.changes),
      ...(item.standing ? ["standing"] : []),
      ...(item.cancel_attempt_ids?.length ? ["attempts"] : []),
    ],
    relations: [],
  }));
  if (request.custom_nodes.length > 0) {
    edits.push({
      operation: "create_nodes",
      node_types: request.custom_nodes.map((node) => node.type),
      node_fields: [],
      relations: [],
    });
  }
  if (request.ontology) {
    edits.push({ operation: "set_ontology", node_types: [], node_fields: [], relations: [] });
  }
  const changesExperimentControl =
    request.nodes.some(
      (item) =>
        graph.nodes[item.node_id]?.type === "experiment" &&
        Object.hasOwn(item.changes, "invocation_ceiling"),
    ) || request.custom_nodes.some((node) => node.type === "experiment");
  // Removal expands to incident relation changes, and a Proposal decision may expand to any
  // Proposal operation. Experiment ceiling updates and new Experiments also change the coherent
  // control projection even though the current manifest does not list them. The browser does not
  // infer any outcomes; absent tags route all of these shapes to preview conservatively.
  if (
    request.removed_node_ids.length > 0 ||
    request.custom_nodes.length > 0 ||
    request.added_edges.length > 0 ||
    request.removed_edge_ids.length > 0 ||
    request.proposals.length > 0 ||
    changesExperimentControl
  ) {
    edits.push({});
  }
  for (const edit of edits) {
    const routing = transitionPreviewRouting(manifest, rulesetTag, edit);
    if (routing.route === "backend_preview") return routing;
  }
  return { route: "local_draft", reason: "no_manifest_trigger" };
}

export function reconcileInactiveProjectTabState(
  state: CachedProjectTabState,
  snapshot: ProjectSnapshot,
): CachedProjectTabState {
  const session = reconcileInactiveProjectSession(state, snapshot);
  if (session === state) return state;
  if (!session.project) return state;
  const presented = applyHumanDraft(session.project.graph, session.humanDraft);
  return {
    ...state,
    ...session,
    project: session.project,
    selectedNodeId:
      state.selectedNodeId && presented.nodes[state.selectedNodeId] ? state.selectedNodeId : null,
    companionNodeId:
      state.companionNodeId && presented.nodes[state.companionNodeId]
        ? state.companionNodeId
        : null,
    floatingChat:
      state.floatingChat && presented.nodes[state.floatingChat.nodeId] ? state.floatingChat : null,
  };
}

export function proposalChoicesClearedNotice(proposalIds: string[]): string {
  return `Externally resolved proposal choices were cleared: ${proposalIds.join(", ")}.`;
}

export function humanSyncSuccessNotice(
  revision: number,
  submittedProposals: HumanSyncRequest["proposals"],
  nextGraph: GraphState,
): string {
  const withdrawnProposalIds = submittedProposals
    .filter((judgment) => nextGraph.proposals[judgment.proposal_id]?.status === "withdrawn")
    .map((judgment) => judgment.proposal_id)
    .sort();
  return withdrawnProposalIds.length > 0
    ? `Synced revision ${revision}. Stale proposals were withdrawn and their proposed changes were not applied: ${withdrawnProposalIds.join(", ")}.`
    : `Synced revision ${revision}.`;
}

export default function App() {
  const desktop = useMemo(() => isDesktopRuntime(), []);
  const [initialRoute] = useState(() => {
    const navigation = window.performance.getEntriesByType("navigation")[0] as
      PerformanceNavigationTiming | undefined;
    const requestedHash = window.location.hash;
    const hash = isSetupHash(requestedHash)
      ? requestedHash
      : initialProjectHash(requestedHash, navigation?.type);
    if (hash !== window.location.hash) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }
    return {
      project: parseProjectHash(hash),
      graphTarget: graphTargetFromHash(hash),
      setupOpen: isSetupHash(hash),
    };
  });
  const [graphTarget, setGraphTarget] = useState<GraphTargetRef>(initialRoute.graphTarget);
  const [requestedChat, setRequestedChat] = useState(() => ({
    hash: window.location.hash,
    projectId: initialRoute.project.projectId,
    chatId: initialRoute.project.chatId,
    graphTarget: initialRoute.graphTarget,
  }));
  const pendingArtifactChatNavigation = useRef<{
    hash: string;
    expiresAt: number;
    resolve: () => void;
    reject: (error: Error) => void;
  } | null>(null);
  const activeGraphTargetRef = useRef(graphTarget);
  // One request id per logical continuation, kept until the server has answered
  // it, so a retry after a lost response replays the episode already created.
  const continuationRequestIds = useRef(new Map<string, string>());
  activeGraphTargetRef.current = graphTarget;
  const {
    identityReady,
    identityIssue,
    verifiedHealth,
    actorIdentity,
    actorIdentityError,
    actorIdentityChecked,
    teamSessionRequired,
    actorNamePromptOpen,
    actorNameDraft,
    actorNameSaving,
    actorNameError,
    requestActorName,
    settleActorNamePrompt,
    saveActorName,
    authenticateTeamSession: authenticateIdentityTeamSession,
    pairTeamDevice: pairIdentityTeamDevice,
    reportIdentityIssue,
    reverifyIdentity,
    currentActiveAgentTasks,
    updateActorNameDraft,
  } = useActorIdentity();
  // Every backend-facing surface, including the WebMCP inventory, waits for the
  // same verified identity, actor, and team-session state that gates the page.
  const backendSessionReady =
    identityReady && !identityIssue && actorIdentityChecked && !teamSessionRequired;
  const releaseUpdate = useUpdateNotice(backendSessionReady);
  const {
    buildIdentity,
    reconnecting,
    desktopUpdate,
    updateExpanded,
    updateApplying,
    updateError,
    pendingDesktopProject,
    desktopAccessError,
    refreshDesktopUpdate,
    recordDesktopUpdateReady,
    requestDesktopProjectOpen,
    continueDesktopProjectOpen: continueDesktopProjectAccess,
    dismissDesktopProjectOpen,
    reconnectBackend: reconnectDesktopBackend,
    applyUpdate: applyDesktopShellUpdate,
    expandUpdate,
    dismissUpdate,
  } = useDesktopShell(desktop);
  const [notice, setNotice] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const [webMcpArtifactViewerUrl, setWebMcpArtifactViewerUrl] = useState<string | null>(null);
  const [webMcpExperimentStartProjectId, setWebMcpExperimentStartProjectId] = useState<
    string | null
  >(null);
  const showWebMcpArtifactViewer = useCallback(async (viewerUrl: string, contentUrl: string) => {
    const response = await fetch(contentUrl, {
      method: "HEAD",
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(`Artifact content is unavailable (${response.status}).`);
    }
    setWebMcpArtifactViewerUrl(viewerUrl);
    return true;
  }, []);
  const reportErrorNotice = useCallback((text: string) => {
    setNotice({ kind: "error", text });
  }, []);
  const [projectInvitations, setProjectInvitations] = useState<ProjectInvitation[]>([]);
  const refreshProjectInvitations = useCallback(async () => {
    try {
      setProjectInvitations(await api<ProjectInvitation[]>("/api/project-invitations"));
    } catch {
      // Invitations are additive to the index; failing to read them must not
      // stop the projects you already have from rendering.
    }
  }, []);
  const {
    state: projectSession,
    dispatchProjectSession,
    getProjectSessionState,
    beginProjectSnapshotRequest,
    projectSnapshotRequestIsCurrent,
    updateProjectHumanDraft,
    beginProjectSync,
    restoreProjectSessionTab,
  } = useProjectSession(initialRoute.project.projectId);
  const {
    project: sessionProject,
    transitionHead,
    transitionRulesetTag,
    transitionManifestRefresh,
    draftTransitionProjection,
    draftPreviewConflict,
    draftPreviewPending,
  } = projectSession;
  const {
    projectId,
    setupOpen,
    projects,
    openProjectTabs,
    experimentLoops,
    spaceRuns,
    projectHeaderCollapsed,
    isActiveProject,
    getActiveProjectId,
    replaceProjects,
    loadProjectIndex,
    refreshExperimentLoops,
    refreshProjectExperimentLoops,
    refreshSpaceRuns,
    replaceEpisodeRunArchive,
    applyHashRoute,
    clearProjectRoute,
    openSetup,
    returnToProjects: returnToProjectIndex,
    commitProjectOpen: commitProjectRoute,
    activateProjectTab: activateProjectRoute,
    closeDockedProject: closeProjectRoute,
    removeProject,
    resetProjectHeader,
    restoreProjectHeader,
    toggleProjectHeader,
    cacheProjectState,
    rememberLeftGraphTarget,
    cachedProjectStateForOpen,
    inactiveCachedProjectState,
    isProjectTabOpen,
    projectIdsForHeartbeat,
    adjacentProjectId,
    runProjectHeartbeat,
  } = useProjectTabs<CachedProjectTabState>({
    initialProjectId: initialRoute.project.projectId,
    initialSetupOpen: initialRoute.setupOpen,
    projectIndexReady: backendSessionReady,
    project: sessionProject,
    reportError: reportErrorNotice,
  });
  useEffect(() => setWebMcpArtifactViewerUrl(null), [projectId]);
  const { project, humanDraft } = projectDraftPreviewEffectInputs(
    projectSession,
    projectId,
    graphTarget,
  );
  const graph = project?.graph ?? emptyGraph;
  const paper = project?.paper ?? null;
  const openMoveProjectSetup = useCallback((sourceProjectId: string) => {
    window.location.hash = projectMoveSetupHash({ sourceProjectId });
  }, []);
  const [textScale, setTextScale] = useState(readTextScale);
  const appearance = useTheme();
  const [loading, setLoading] = useState(true);
  const [projectReconciliation, setProjectReconciliation] =
    useState<ProjectReconciliation>("opening");
  const [usage, setUsage] = useState<AgentUsageSnapshot | null>(null);
  const [watchers, setWatchers] = useState<WatcherRecord[]>([]);
  const [providerReadinessRequests, setProviderReadinessRequests] = useState<
    Record<string, ProviderReadinessRequestState>
  >({});
  const {
    view,
    trustView,
    runScope,
    selectedNode,
    companionNode,
    detailFocusTokens,
    selectedExperimentRunId,
    focusExperimentRunId,
    selectedExperimentRoute,
    selectedAutoResearchEpisodeId,
    experimentStopId,
    watcherCheckId,
    dockedNodeIds,
    dagRelationFocusId,
    panelRef,
    activeDagViewportRef,
    captureProjectSelection,
    restoreProjectSelection,
    resetProjectSelection,
    applyCanonicalProject,
    replaceRunScope,
    applyRouteSelection,
    changeView,
    openLastResearchView,
    changeTrustView,
    openNode,
    openRelatedNode: openRelatedGraphNode,
    closeDetailSlot,
    clearNodeSelections,
    dockNode,
    restoreDockedNode: restoreDockedGraphNode,
    replaceExactAutoResearchSelection,
    replaceExactExperimentEpisode,
    selectExperiment,
    clearExperimentFocus,
    showExperiment,
    beginExperimentStop,
    beginWatcherCheck,
    clearDagRelationFocus,
    forgetProjectViewport,
  } = useGraphSelection({
    initialView: initialRoute.project.view,
    initialExperimentId: initialRoute.project.experimentId,
    initialExperimentRoute: initialRoute.project.experimentRoute,
    initialAutoResearchEpisodeId: initialRoute.project.autoResearchEpisodeId,
    projectId,
    graphTarget,
    loadedProjectId: project?.id ?? null,
    loading,
    getActiveProjectId,
  });
  const selectedIndexedExperiment = experimentIndexEntryForRoute(
    experimentLoops,
    projectId,
    selectedExperimentRoute,
  );
  const selectedExperimentUsesBranch = selectedExperimentRoute?.graph_target.kind === "branch";
  const selectedBranchExperiment = selectedExperimentUsesBranch ? selectedIndexedExperiment : null;
  const authoritativeProjectId = useRef<string | null>(null);
  const reloadRef = useRef<(includeTasks?: boolean) => Promise<void>>(async () => undefined);
  const authoritativeReloadInFlight = useRef<{
    projectId: string;
    graphTarget: GraphTargetRef;
    request: Promise<void>;
  } | null>(null);
  const initialShowHandshake = useRef(false);
  const providerReadinessRequestsInFlight = useRef(new Map<string, ProviderReadinessInFlight>());
  const projectReadinessGenerations = useRef(new Map<string, ProjectReadinessGeneration>());
  const providerSkillReadinessPoll = useRef<{ projectId: string; timeoutId: number } | null>(null);
  const currentProjectStateRef = useRef<Omit<CachedProjectTabState, "viewState"> | null>(null);
  const updateProject = useCallback(
    (update: (current: ProjectSnapshot | null) => ProjectSnapshot | null) => {
      const current = getProjectSessionState().project;
      dispatchProjectSession({ kind: "project_replaced", project: update(current) });
    },
    [dispatchProjectSession, getProjectSessionState],
  );
  const apiBase = projectId ? `/api/projects/${encodeURIComponent(projectId)}` : "";
  const graphPath = useCallback((path: string) => graphTargetUrl(path, graphTarget), [graphTarget]);
  const isActiveGraph = useCallback(
    (id: string) =>
      isActiveProject(id) && sameGraphTarget(activeGraphTargetRef.current, graphTarget),
    [graphTarget, isActiveProject],
  );
  const syncingDraft = projectId
    ? Boolean(
        projectSession.transitionCoordinator.sync_requests[graphSessionKey(projectId, graphTarget)],
      )
    : false;
  const transitionManifest = trustedProjectTransitionManifest(projectSession, projectId);
  const {
    snapshot: agentTasksSnapshot,
    taskStarting,
    taskActionId,
    taskInspectorLoading,
    activeTask,
    activityTask,
    replaceTasks,
    consumeTerminalTasks,
    upsertTask,
    recordStartedTask,
    presentTask: presentAgentTask,
    selectTaskInspector,
    chooseRetryTask,
    closeRetryTask,
    beginTaskStart,
    beginTaskAction,
    beginTaskRepair,
    resetProjectTasks,
    restoreProjectTasks,
  } = useAgentTasks({ projectId, reportError: reportErrorNotice });
  const { retryTask, tasks: projectTasks, taskInspectorId, inspectedTask } = agentTasksSnapshot;
  const tasks = useMemo(
    () => projectTasks.filter((task) => sameGraphTarget(task.graph_target, graphTarget)),
    [projectTasks, graphTarget],
  );
  const selectedMainExperimentRouteIsCurrent =
    !selectedExperimentRoute ||
    selectedExperimentUsesBranch ||
    mainExperimentRouteMatchesControl(
      selectedExperimentRoute,
      selectedExperimentRunId ? project?.experiment_control[selectedExperimentRunId] : undefined,
    );
  const selectedExperimentOperational =
    view === "execution" && selectedExperimentRunId && selectedMainExperimentRouteIsCurrent
      ? selectedExperimentUsesBranch
        ? (selectedBranchExperiment?.control.operational ?? null)
        : (project?.experiment_control[selectedExperimentRunId]?.operational ?? null)
      : null;
  const selectedExperimentChatId = selectedExperimentOperational?.chat_id ?? null;
  // The Runs panel keeps a branch-scoped Experiment's graph out of the viewed
  // target, so its chat must be loaded against the route's own graph. Without
  // an exact route the chat id comes from the viewed graph's own projection, so
  // that target stays correct and is the default.
  const selectedExperimentChatTarget =
    selectedExperimentUsesBranch && selectedExperimentRoute
      ? selectedExperimentRoute.graph_target
      : graphTarget;
  const selectedExperimentChatFreshness = experimentChatFreshnessToken(
    selectedExperimentChatId,
    selectedExperimentOperational,
    selectedExperimentChatTarget,
    graphTarget,
  );
  const resolveVisibleChatTranscriptIds = useCallback(
    (selectedId: string | null, floatingId: string | null) =>
      visibleChatTranscriptIds(view, selectedId, floatingId, selectedExperimentChatId),
    [selectedExperimentChatId, view],
  );
  const {
    snapshot: chatStateSnapshot,
    chatSummariesLoading,
    visibleChatSummaries,
    selectChat,
    selectCanonicalChat,
    selectListedConversation,
    setFloatingChat,
    reconcileFloatingChat,
    startConversation,
    discardDraft,
    ensureConversation,
    refreshChatSummaries,
    loadMoreChatSummaries,
    recordTaskUpdates,
    recordWatcherResults,
    markVisibleChatRead,
    resetProjectChats,
    restoreProjectChats,
  } = useChatState({
    projectId,
    apiBase,
    graphTarget,
    selectedExperimentChatId,
    selectedExperimentChatTarget,
    selectedExperimentChatFreshness,
    isActiveProject: isActiveGraph,
    visibleTranscriptIds: resolveVisibleChatTranscriptIds,
    reportError: reportErrorNotice,
  });
  const {
    floatingChat,
    draftConversations,
    selectedChatId,
    unreadChatTaskIds,
    chatSummaryTotal,
    chatSummaryNextOffset,
    chatTranscripts,
  } = chatStateSnapshot;
  const {
    runDialogOpen,
    autoResearchDialogOpen,
    autoResearchStartError,
    episodeAction,
    episodeRefreshError,
    episodes,
    liveAutoResearchEpisode,
    openRunDialog,
    closeRunDialog,
    openAutoResearchDialog,
    closeAutoResearchDialog,
    reportAutoResearchStartError,
    beginEpisodeAction,
    replaceEpisode,
    recordEpisodeMessage,
    refreshEpisodes,
    refreshEpisodeMessages,
  } = useEpisodeDialogs({
    projectId,
    apiBase,
    selectedAutoResearchEpisodeId,
    isActiveProject,
    runsVisible: view === "execution",
  });
  const activeBranchEpisode =
    graphTarget.kind === "branch"
      ? episodes.find((episode) => episode.graph_branch?.branch_id === graphTarget.branch_id)
      : null;
  const {
    snapshot: projectHistorySnapshot,
    openProjectHistory,
    closeProjectHistory,
    resetProjectHistory,
    restoreProjectHistory,
    dismissHistoryNotices,
  } = useProjectHistory({
    projectId,
    apiBase,
    graphTarget,
    loadedProjectId: project?.id ?? null,
    revision: graph.revision,
    isActiveProject: isActiveGraph,
    reportError: reportErrorNotice,
  });
  const {
    latestRevisionSummary,
    historyRevisionSummaries,
    historySummariesRevision,
    historySummariesError,
    projectHistoryOpen,
    dismissedHistoryNoticeIds,
  } = projectHistorySnapshot;
  currentProjectStateRef.current = project
    ? {
        ...serializeProjectSessionTabState(projectSession),
        project,
        projectHeaderCollapsed,
        runScope,
        selectedNodeId: selectedNode?.id ?? null,
        companionNodeId: companionNode?.id ?? null,
        detailFocusTokens,
        selectedExperimentRunId,
        focusExperimentRunId,
        selectedExperimentRoute,
        selectedAutoResearchEpisodeId,
        dockedNodeIds,
        ...chatStateSnapshot,
        dagRelationFocusId,
        ...agentTasksSnapshot,
        ...projectHistorySnapshot,
        usage,
        watchers,
      }
    : null;

  const rememberProjectState = useCallback(
    (id: string | null) => {
      if (!id) return;
      // The routed target, so a branch still loading is remembered too.
      rememberLeftGraphTarget(id, activeGraphTargetRef.current);
      const current = currentProjectStateRef.current;
      if (!current || current.project.id !== id) return;
      const selection = captureProjectSelection(id, current.project.graph_target);
      cacheProjectState(id, {
        ...current,
        ...selection,
        ...cloneChatStateSnapshot(current),
        ...cloneAgentTasksSnapshot(current),
        ...cloneProjectHistorySnapshot(current),
        watchers: [...current.watchers],
      });
    },
    [cacheProjectState, captureProjectSelection, rememberLeftGraphTarget],
  );

  useEffect(() => {
    if (!notice) return;
    const timeoutId = window.setTimeout(() => {
      setNotice((current) => (current === notice ? null : current));
    }, NOTICE_TIMEOUT_MS);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  useEffect(() => {
    const proposalIds = projectSession.draftReconciliationDiscardedProposalIds;
    if (proposalIds.length === 0) return;
    setNotice({ kind: "info", text: proposalChoicesClearedNotice(proposalIds) });
    dispatchProjectSession({ kind: "discarded_proposals_consumed" });
  }, [dispatchProjectSession, projectSession.draftReconciliationDiscardedProposalIds]);

  const restoreProjectTabState = useCallback(
    (id: string, state: CachedProjectTabState, requestedRoute?: ProjectHashRoute) => {
      const discardedProposalIds = state.draftReconciliationDiscardedProposalIds;
      const { next } = restoreProjectSessionTab(id, state, {
        consumeDiscardedProposals: true,
      });
      if (!next.project) return;
      const nextGraph = next.project.graph;
      const presented = applyHumanDraft(nextGraph, next.humanDraft);
      cacheProjectState(id, {
        ...state,
        ...serializeProjectSessionTabState(next),
        project: next.project,
      });
      authoritativeProjectId.current = id;
      restoreProjectHeader(state.projectHeaderCollapsed);
      restoreProjectSelection(
        id,
        nextGraph,
        presented.nodes,
        state,
        requestedRoute,
        next.graphTarget,
      );
      restoreProjectChats(state, presented.nodes);
      restoreProjectTasks(state);
      restoreProjectHistory(state);
      setUsage(state.usage);
      setWatchers([...state.watchers]);
      setProjectReconciliation("authoritative");
      setLoading(false);
      if (discardedProposalIds.length > 0) {
        setNotice({ kind: "info", text: proposalChoicesClearedNotice(discardedProposalIds) });
      }
    },
    [
      cacheProjectState,
      restoreProjectChats,
      restoreProjectHeader,
      restoreProjectSelection,
      restoreProjectSessionTab,
    ],
  );

  const applyProjectSnapshot = useCallback(
    (
      nextProject: ProjectSnapshot,
      preserveReadiness: boolean,
      request?: { projectId: string; requestId: number },
    ): boolean => {
      const { previous, next } = dispatchProjectSession({
        kind: "snapshot_applied",
        snapshot: nextProject,
        preserve_readiness: preserveReadiness,
        request: request
          ? { project_id: request.projectId, request_id: request.requestId }
          : undefined,
      });
      if (next === previous || !next.project) return false;
      const authoritative = nextProject.snapshot_freshness === "fresh";
      applyCanonicalProject(next.project, authoritative);
      try {
        persistProjectHumanDraft(localStorage, next.project.id, next.humanDraft, next.graphTarget);
      } catch {
        // The in-memory draft remains usable if browser storage is unavailable.
      }
      const nextGraph = next.project.graph;
      reconcileFloatingChat(nextGraph.nodes, !authoritative);
      return true;
    },
    [applyCanonicalProject, dispatchProjectSession, reconcileFloatingChat],
  );

  const reload = useCallback(
    async (includeTasks = true) => {
      if (!projectId) return;
      const requestedProjectId = projectId;
      const requestId = beginProjectSnapshotRequest(requestedProjectId);
      const responseIsCurrent = () =>
        isActiveGraph(requestedProjectId) &&
        projectSnapshotRequestIsCurrent(requestedProjectId, requestId);
      const base = `/api/projects/${encodeURIComponent(requestedProjectId)}`;
      const projectRequest = api<ProjectSnapshot>(graphPath(base)).then((nextProject) => {
        if (!responseIsCurrent()) return;
        const applied = applyProjectSnapshot(
          nextProject,
          authoritativeProjectId.current === requestedProjectId,
          { projectId: requestedProjectId, requestId },
        );
        if (!applied) return;
        authoritativeProjectId.current = requestedProjectId;
        setProjectReconciliation("authoritative");
      });
      const tasksRequest = includeTasks
        ? api<AgentTask[]>(`${base}/tasks`).then((nextTasks) => {
            if (responseIsCurrent()) replaceTasks(nextTasks);
          })
        : Promise.resolve();
      const usageRequest = api<AgentUsageSnapshot>(`${base}/usage`)
        .then((nextUsage) => {
          if (responseIsCurrent()) setUsage(nextUsage);
        })
        .catch((error) => {
          if (!(error instanceof ApiError && error.status === 404)) throw error;
          if (responseIsCurrent()) setUsage(null);
        });
      const watchersRequest = api<WatcherRecord[]>(graphPath(`${base}/watchers`)).then(
        (nextWatchers) => {
          if (responseIsCurrent()) setWatchers(nextWatchers);
        },
      );
      const chatsRequest = refreshChatSummaries(requestedProjectId, base).catch((error) => {
        if (responseIsCurrent()) {
          setNotice({
            kind: "error",
            text: `Chats could not be loaded: ${error instanceof Error ? error.message : String(error)}`,
          });
        }
      });
      await Promise.all([
        projectRequest,
        tasksRequest,
        usageRequest,
        watchersRequest,
        chatsRequest,
      ]);
    },
    [
      applyProjectSnapshot,
      graphPath,
      isActiveGraph,
      beginProjectSnapshotRequest,
      isActiveProject,
      projectId,
      projectSnapshotRequestIsCurrent,
      refreshChatSummaries,
    ],
  );
  reloadRef.current = reload;

  useEffect(() => {
    if (!projectId || !apiBase) return;
    const requestedProjectId = projectId;
    let cancelled = false;
    const currentManifest = getProjectSessionState().transitionManifestState;
    dispatchProjectSession({
      kind: "manifest_loading",
      project_id: requestedProjectId,
      manifest: currentManifest.project_id === requestedProjectId ? currentManifest.manifest : null,
    });
    void api<unknown>(graphPath(`${apiBase}/transition-manifest`))
      .then((payload) => {
        if (cancelled || !isActiveGraph(requestedProjectId)) return;
        const manifest = decodeTransitionTriggerManifest(
          payload,
          getProjectSessionState().transitionManifestExpectedRulesetTag,
        );
        if (!manifest) {
          dispatchProjectSession({ kind: "manifest_invalid", project_id: requestedProjectId });
          return;
        }
        dispatchProjectSession({
          kind: "manifest_valid",
          project_id: requestedProjectId,
          manifest,
        });
      })
      .catch(() => {
        // A missing manifest is an intentional fail-safe state: staged edits use backend preview.
        if (!cancelled && isActiveGraph(requestedProjectId)) {
          dispatchProjectSession({ kind: "manifest_invalid", project_id: requestedProjectId });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    apiBase,
    graphPath,
    isActiveGraph,
    dispatchProjectSession,
    getProjectSessionState,
    isActiveProject,
    projectId,
    transitionManifestRefresh,
  ]);

  const reloadAuthoritativeProject = useCallback(
    (requestedProjectId?: string | null) => {
      const activeId = requestedProjectId ?? getActiveProjectId();
      if (!activeId || !isActiveProject(activeId)) return Promise.resolve();
      if (
        authoritativeReloadInFlight.current?.projectId === activeId &&
        sameGraphTarget(
          authoritativeReloadInFlight.current.graphTarget,
          activeGraphTargetRef.current,
        )
      ) {
        return authoritativeReloadInFlight.current.request;
      }
      const request = reloadRef.current().finally(() => {
        if (authoritativeReloadInFlight.current?.request === request) {
          authoritativeReloadInFlight.current = null;
        }
      });
      authoritativeReloadInFlight.current = {
        projectId: activeId,
        graphTarget: activeGraphTargetRef.current,
        request,
      };
      return request;
    },
    [getActiveProjectId, isActiveProject],
  );

  const heartbeatProjectCache = useCallback(
    (requestedProjectId: string): Promise<void> =>
      runProjectHeartbeat(requestedProjectId, async () => {
        const base = `/api/projects/${encodeURIComponent(requestedProjectId)}`;
        const requestedTarget = isActiveProject(requestedProjectId)
          ? activeGraphTargetRef.current
          : MAIN_GRAPH;
        let observation: GraphRevisionSnapshot;
        try {
          observation = await loadGraphRevision(
            (path) => api(graphTargetUrl(path, requestedTarget)),
            base,
          );
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 404)) throw error;
          // A 404 here is ambiguous: the display cache may merely be missing,
          // or the project may have stopped being readable — deleted, or no
          // longer ours. The filtered index answers which.
          if (await projectIsStillReadable(api, requestedProjectId)) return;
          // Close the tab *and* leave the view: closing alone would strand the
          // reader on a project they can no longer load anything from.
          closeProjectRoute(requestedProjectId);
          removeProject(requestedProjectId);
          forgetProjectViewport(requestedProjectId);
          setNotice({ kind: "error", text: "This project is no longer available." });
          return;
        }
        const observedRevision = observation.revision;
        const tabIsOpen = () => isProjectTabOpen(requestedProjectId);
        if (!tabIsOpen()) return;
        if (isActiveProject(requestedProjectId)) {
          if (!sameGraphTarget(requestedTarget, activeGraphTargetRef.current)) return;
          if (
            canonicalRevisionNeedsReload(
              observedRevision,
              getProjectSessionState().renderedRevision,
              observation.graph_mutation,
              getProjectSessionState().project?.graph_mutation,
            ) ||
            (observedRevision === getProjectSessionState().renderedRevision &&
              projectHeartbeatMetadataChanged(
                observation,
                getProjectSessionState().project,
                requestedTarget,
              ))
          ) {
            await reloadAuthoritativeProject(requestedProjectId);
          }
          return;
        }

        const retained = inactiveCachedProjectState(requestedProjectId);
        if (
          !retained ||
          observedRevision < retained.project.graph.revision ||
          (observedRevision === retained.project.graph.revision &&
            !projectHeartbeatMetadataChanged(observation, retained.project))
        )
          return;
        const snapshot = await api<ProjectSnapshot>(`${base}/cached`);
        const current = inactiveCachedProjectState(requestedProjectId);
        const disposition = projectHeartbeatSnapshotDisposition({
          requestedProjectId,
          activeProjectId: getActiveProjectId(),
          tabOpen: tabIsOpen(),
          inactiveState: current,
          snapshotRevision: snapshot.graph.revision,
          renderedRevision: getProjectSessionState().renderedRevision,
          metadataChanged: projectHeartbeatMetadataChanged(
            snapshot,
            getProjectSessionState().project,
            activeGraphTargetRef.current,
          ),
        });
        if (disposition.kind === "reload_active") {
          await reloadAuthoritativeProject(requestedProjectId);
          return;
        }
        if (disposition.kind === "ignore") {
          return;
        }
        const next = reconcileInactiveProjectTabState(disposition.state, snapshot);
        if (next === disposition.state) return;
        cacheProjectState(requestedProjectId, next);
        try {
          persistProjectHumanDraft(localStorage, requestedProjectId, next.humanDraft);
        } catch {
          // A background cache refresh must not discard the in-memory draft.
        }
      }),
    [
      cacheProjectState,
      closeProjectRoute,
      forgetProjectViewport,
      getActiveProjectId,
      getProjectSessionState,
      inactiveCachedProjectState,
      isActiveProject,
      isProjectTabOpen,
      reloadAuthoritativeProject,
      removeProject,
      runProjectHeartbeat,
    ],
  );

  useEffect(() => {
    if (!identityReady || identityIssue || !actorIdentityChecked || teamSessionRequired) return;
    const runHeartbeat = (id: string) => {
      void heartbeatProjectCache(id).catch(() => {
        // Heartbeat failures leave the last usable display cache intact.
      });
    };
    return startProjectCachePolling(
      {
        setInterval: (callback, delay) => window.setInterval(callback, delay),
        clearInterval: (intervalId) => window.clearInterval(intervalId),
      },
      {
        isHidden: pageIsHidden,
        listen: (callback) => {
          document.addEventListener("visibilitychange", callback);
          return () => document.removeEventListener("visibilitychange", callback);
        },
      },
      () => projectIdsForHeartbeat().forEach(runHeartbeat),
      () => {
        const activeId = getActiveProjectId();
        if (activeId) runHeartbeat(activeId);
      },
    );
  }, [
    actorIdentityChecked,
    heartbeatProjectCache,
    identityIssue,
    identityReady,
    getActiveProjectId,
    projectIdsForHeartbeat,
    teamSessionRequired,
  ]);

  const settleTeamSignIn = useCallback(() => {
    clearProjectRoute();
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  }, [clearProjectRoute]);

  const authenticateTeamSession = useCallback(
    async (token: string) => {
      await authenticateIdentityTeamSession(token);
      settleTeamSignIn();
    },
    [authenticateIdentityTeamSession, settleTeamSignIn],
  );

  const pairTeamDevice = useCallback(
    async (code: string, label: string) => {
      await pairIdentityTeamDevice(code, label);
      settleTeamSignIn();
    },
    [pairIdentityTeamDevice, settleTeamSignIn],
  );

  useEffect(() => {
    if (!desktop) return;
    let stopped = false;
    const cleanups: Array<() => void> = [];
    // Reload what the window shows: the active project, or the project index.
    const reloadVisibleState = async () => {
      const activeId = getActiveProjectId();
      if (activeId) {
        const visibleProjectId = activeId;
        const nextTasks = await api<AgentTask[]>(
          `/api/projects/${encodeURIComponent(visibleProjectId)}/tasks`,
        );
        if (isActiveProject(visibleProjectId)) replaceTasks(nextTasks);
        setProjectReconciliation("reconciling");
        void reloadRef.current(false).catch((error) => {
          if (!isActiveProject(visibleProjectId) || stopped) return;
          setProjectReconciliation("failed");
          setNotice({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          });
        });
      } else {
        const nextProjects = await api<ProjectCard[]>("/api/projects");
        if (!stopped) replaceProjects(nextProjects);
      }
    };
    const prepareShow = async () => {
      try {
        const identity = await reverifyIdentity("prepare-show");
        if (identity.ok) {
          await reloadVisibleState();
          await refreshDesktopUpdate();
        }
      } catch (error) {
        if (!stopped)
          setNotice({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          });
      } finally {
        try {
          await desktopShowReady();
        } catch (error) {
          if (!stopped)
            setNotice({
              kind: "error",
              text: error instanceof Error ? error.message : String(error),
            });
        }
      }
    };
    void Promise.all([
      listenDesktopEvent("rcp://prepare-show", prepareShow),
      listenDesktopEvent<{ message?: string }>("rcp://backend-mismatch", async (payload) => {
        if (!stopped && payload.message) reportIdentityIssue(payload.message);
        await reverifyIdentity("desktop-backend-mismatch");
      }),
      listenDesktopEvent<{ version?: string }>("rcp://update-ready", (payload) => {
        if (stopped) return;
        recordDesktopUpdateReady(payload.version, currentActiveAgentTasks());
      }),
    ]).then((nextCleanups) => {
      if (stopped) nextCleanups.forEach((cleanup) => cleanup());
      else {
        cleanups.push(...nextCleanups);
        if (!initialShowHandshake.current) {
          initialShowHandshake.current = true;
          void prepareShow();
        }
      }
    });
    // Loads that failed while the team tunnel was down are not polled again.
    const onTeamTransportRecovered = (event: Event) => {
      const detail = (event as CustomEvent<BackendIdentityEventDetail>).detail;
      if (stopped || !detail.ok || detail.reason !== TEAM_TRANSPORT_RECOVERED) return;
      void reloadVisibleState().catch((error) => {
        if (!stopped)
          setNotice({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          });
      });
    };
    window.addEventListener(BACKEND_IDENTITY_EVENT, onTeamTransportRecovered);
    cleanups.push(() =>
      window.removeEventListener(BACKEND_IDENTITY_EVENT, onTeamTransportRecovered),
    );
    void refreshDesktopUpdate();
    return () => {
      stopped = true;
      cleanups.forEach((cleanup) => cleanup());
    };
  }, [desktop, refreshDesktopUpdate]);

  const requestProjectReadiness = useCallback(
    (refresh: boolean): Promise<ProjectReadinessSnapshot | null> => {
      if (!apiBase || !projectId) return Promise.resolve(null);
      const requestedProjectId = projectId;
      const requestGeneration = currentProjectReadinessGeneration(
        projectReadinessGenerations.current,
        requestedProjectId,
      );
      const existing = providerReadinessRequestsInFlight.current.get(requestedProjectId);
      if (
        existing !== undefined &&
        existing.generation.provider === requestGeneration.provider &&
        existing.generation.compute === requestGeneration.compute
      ) {
        if (!refresh || existing.refresh) return existing.request;
        return existing.request.then(() => requestProjectReadiness(true));
      }

      setProviderReadinessRequests((current) => ({
        ...current,
        [requestedProjectId]: { pending: true, providerError: null, computeError: null },
      }));
      let request: Promise<ProjectReadinessSnapshot | null>;
      request = loadProjectReadiness(apiBase, refresh)
        .then((readiness) => {
          const applies = projectReadinessResponseApplies(
            projectReadinessGenerations.current,
            requestedProjectId,
            requestGeneration,
          );
          if (!applies.provider && !applies.compute) return null;
          if (isActiveProject(requestedProjectId)) {
            updateProject((current) =>
              current?.id === requestedProjectId
                ? { ...current, ...projectReadinessUpdate(readiness, applies) }
                : current,
            );
          }
          // The caller polls provider skill inventories, so a superseded
          // provider slice has no follow-up left to decide.
          return applies.provider ? readiness : null;
        })
        .catch((error) => {
          const applies = projectReadinessResponseApplies(
            projectReadinessGenerations.current,
            requestedProjectId,
            requestGeneration,
          );
          if (!applies.provider && !applies.compute) return null;
          const message = error instanceof Error ? error.message : String(error);
          const registered =
            providerReadinessRequestsInFlight.current.get(requestedProjectId)?.request === request;
          if (projectReadinessFailureApplies(registered, applies)) {
            setProviderReadinessRequests((current) => ({
              ...current,
              [requestedProjectId]: projectReadinessFailureState(
                current[requestedProjectId],
                applies,
                message,
              ),
            }));
            if (isActiveProject(requestedProjectId)) {
              setNotice({ kind: "error", text: message });
            }
          }
          if (refresh) throw error instanceof Error ? error : new Error(message);
          return null;
        })
        .finally(() => {
          if (
            providerReadinessRequestsInFlight.current.get(requestedProjectId)?.request === request
          ) {
            providerReadinessRequestsInFlight.current.delete(requestedProjectId);
            setProviderReadinessRequests((current) => ({
              ...current,
              [requestedProjectId]: {
                pending: false,
                providerError: current[requestedProjectId]?.providerError ?? null,
                computeError: current[requestedProjectId]?.computeError ?? null,
              },
            }));
          }
        });
      providerReadinessRequestsInFlight.current.set(requestedProjectId, {
        refresh,
        generation: requestGeneration,
        request,
      });
      return request;
    },
    [apiBase, isActiveProject, projectId, updateProject],
  );

  // The Runs view overlays the live machine-account login states on the
  // project's own account list. One small read per poll; the readiness
  // snapshot is not re-requested for it.
  const [liveProviderLogins, setLiveProviderLogins] = useState<ProviderLoginState[] | null>(null);
  const refreshProviderLogins = useCallback(async () => {
    setLiveProviderLogins(await loadProviderLogins());
  }, []);
  const runsProviderLogins = useMemo(
    () => mergeProviderLogins(project?.provider_logins ?? [], liveProviderLogins),
    [project?.provider_logins, liveProviderLogins],
  );
  useEffect(() => {
    if (!projectId || !projectRunsNeedsExperimentIndex(projectId, view)) return;
    let stopped = false;
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(() => void poll(), EXPERIMENT_BOARD_POLL_DELAY_MS);
    };
    const poll = async () => {
      if (stopped) return;
      if (document.visibilityState === "hidden") {
        schedule();
        return;
      }
      try {
        await Promise.all([refreshProjectExperimentLoops(projectId), refreshProviderLogins()]);
      } catch (error) {
        if (!stopped) {
          reportErrorNotice(
            `Experiment board could not be refreshed: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }
      if (!stopped) schedule();
    };
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [projectId, refreshProjectExperimentLoops, refreshProviderLogins, reportErrorNotice, view]);

  const refreshReadiness = useCallback(async () => {
    await requestProjectReadiness(true);
  }, [requestProjectReadiness]);

  const ensureProjectReadiness = useCallback(() => {
    if (
      !apiBase ||
      !projectId ||
      project?.id !== projectId ||
      projectReconciliation !== "authoritative" ||
      !shouldRequestProviderReadiness(
        project.provider_readiness,
        providerReadinessRequestsInFlight.current.has(projectId),
      )
    )
      return;
    const requestedProjectId = projectId;
    const readCachedReadiness = (completedFollowUps: number) => {
      void requestProjectReadiness(false).then((readiness) => {
        if (!readiness) return;
        if (!isActiveProject(requestedProjectId)) return;
        if (
          shouldPollProviderSkillReadiness(readiness.provider_skill_inventories, completedFollowUps)
        ) {
          const timeoutId = window.setTimeout(() => {
            providerSkillReadinessPoll.current = null;
            if (!isActiveProject(requestedProjectId)) return;
            readCachedReadiness(completedFollowUps + 1);
          }, PROVIDER_SKILL_READINESS_POLL_DELAY_MS);
          providerSkillReadinessPoll.current = { projectId: requestedProjectId, timeoutId };
        } else {
          providerSkillReadinessPoll.current = null;
        }
      });
    };
    readCachedReadiness(0);
  }, [
    apiBase,
    isActiveProject,
    project,
    projectId,
    projectReconciliation,
    requestProjectReadiness,
  ]);

  useEffect(() => {
    return () => {
      const pending = providerSkillReadinessPoll.current;
      if (pending?.projectId === projectId) {
        window.clearTimeout(pending.timeoutId);
        providerSkillReadinessPoll.current = null;
      }
    };
  }, [projectId]);

  const refreshUsage = useCallback(async () => {
    if (!apiBase) return;
    try {
      const nextUsage = await api<AgentUsageSnapshot>(`${apiBase}/usage`);
      if (projectId && isActiveProject(projectId)) setUsage(nextUsage);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }, [apiBase, isActiveProject, projectId]);

  useLayoutEffect(() => {
    // A new editor supersedes the old one's pending save. Leaving Paper alone
    // still lets that save update the project snapshot used by other views.
    if (view === "paper" && project?.id) {
      dispatchProjectSession({ kind: "paper_editor_opened" });
    }
  }, [dispatchProjectSession, project?.id, view]);

  const updatePaper = useCallback(
    (nextPaper: PaperSnapshot) => {
      if (projectId) {
        dispatchProjectSession({
          kind: "paper_updated",
          project_id: projectId,
          editor_generation: projectSession.paperEditorGeneration,
          paper: nextPaper,
        });
      }
    },
    [dispatchProjectSession, projectId, projectSession.paperEditorGeneration],
  );

  useEffect(() => {
    const handleHashChange = () => {
      const pending = pendingArtifactChatNavigation.current;
      if (pending && pending.hash !== window.location.hash) {
        pending.reject(new Error("Chat navigation was cancelled."));
        pendingArtifactChatNavigation.current = null;
      }
      const route = parseProjectHash(window.location.hash);
      const activeId = getActiveProjectId();
      const nextTarget = graphTargetFromHash(window.location.hash);
      setRequestedChat({
        hash: window.location.hash,
        projectId: route.projectId,
        chatId: route.chatId,
        graphTarget: nextTarget,
      });
      if (
        route.projectId !== activeId ||
        !sameGraphTarget(nextTarget, activeGraphTargetRef.current)
      ) {
        rememberProjectState(activeId);
      }
      activeGraphTargetRef.current = nextTarget;
      setGraphTarget((current) => (sameGraphTarget(current, nextTarget) ? current : nextTarget));
      applyHashRoute(route.projectId, isSetupRoute());
      applyRouteSelection(
        route.view,
        route.experimentId,
        route.experimentRoute,
        route.autoResearchEpisodeId,
      );
    };
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, [applyHashRoute, applyRouteSelection, getActiveProjectId, rememberProjectState]);

  useLayoutEffect(() => {
    if (!identityReady || identityIssue || !actorIdentityChecked || teamSessionRequired) return;
    const requestedRoute = parseProjectHash(window.location.hash);
    const routeMatchesProject = requestedRoute.projectId === projectId;
    const retainedOpen = projectId ? cachedProjectStateForOpen(projectId, graphTarget) : null;
    const retained = retainedOpen?.state;
    setNotice(null);
    if (projectId && retained) {
      restoreProjectTabState(
        projectId,
        retained,
        routeMatchesProject && requestedRoute.projectViewSpecified ? requestedRoute : undefined,
      );
    } else {
      setLoading(true);
      setProjectReconciliation("opening");
      authoritativeProjectId.current = null;
      let storedDraft: HumanDraft | null = null;
      if (projectId) {
        try {
          storedDraft = deserializeHumanDraft(
            localStorage.getItem(humanDraftStorageKey(projectId, graphTarget)),
          );
        } catch (error) {
          setNotice({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          });
        }
      }
      dispatchProjectSession({
        kind: "reset",
        project_id: projectId,
        graph_target: graphTarget,
        human_draft: storedDraft,
      });
      resetProjectSelection(
        routeMatchesProject ? requestedRoute.view : "overview",
        routeMatchesProject ? requestedRoute.experimentId : null,
        routeMatchesProject ? requestedRoute.experimentRoute : null,
        routeMatchesProject ? requestedRoute.autoResearchEpisodeId : null,
      );
      resetProjectChats();
      resetProjectTasks();
      resetProjectHistory(projectId, graphTarget);
      setUsage(null);
      setWatchers([]);
      resetProjectHeader(projectId);
    }
    if (setupOpen) {
      setLoading(false);
      return;
    }
    if (!projectId) {
      void refreshProjectInvitations();
      loadProjectIndex()
        .catch((error) =>
          setNotice({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          }),
        )
        .finally(() => setLoading(false));
      return;
    }
    let cancelled = false;
    const stillOpening = () => !cancelled && isActiveGraph(projectId);
    const applyCachedSnapshot = async () => {
      const cachedRequestId = beginProjectSnapshotRequest(projectId);
      try {
        const cachedProject = await api<ProjectSnapshot>(
          graphPath(`/api/projects/${encodeURIComponent(projectId)}/cached`),
        );
        if (!stillOpening()) return;
        // The session declines a cached snapshot that lost to a newer snapshot
        // request — the active-tab heartbeat may already be reloading — or that
        // is behind the rendered revision. Only an accepted snapshot paints early;
        // the authoritative reload finishes the open either way.
        if (
          !applyProjectSnapshot(cachedProject, false, {
            projectId,
            requestId: cachedRequestId,
          })
        )
          return;
        setProjectReconciliation("authoritative");
        setLoading(false);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404) && !cancelled) {
          setNotice({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          });
        }
      }
    };
    const reloadAuthoritative = async () => {
      try {
        // Always a fresh request: joining a reload already in flight (from the
        // heartbeat, or from this project before a quick close and reopen) could
        // hand this open a promise whose responses are all older than the cached
        // request above and therefore discarded, settling an empty view.
        await reload();
      } catch (error) {
        if (!stillOpening()) return;
        if (!retained && authoritativeProjectId.current !== projectId) {
          setProjectReconciliation("failed");
        }
        setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
      }
    };
    void openProjectSequence({
      applyCachedSnapshot,
      reloadAuthoritative,
      stillOpening,
      settle: () => setLoading(false),
    });
    return () => {
      cancelled = true;
    };
  }, [
    applyProjectSnapshot,
    actorIdentityChecked,
    beginProjectSnapshotRequest,
    cachedProjectStateForOpen,
    dispatchProjectSession,
    identityIssue,
    identityReady,
    isActiveProject,
    loadProjectIndex,
    projectId,
    graphTarget,
    graphPath,
    isActiveGraph,
    reload,
    resetProjectHeader,
    resetProjectSelection,
    restoreProjectTabState,
    selectChat,
    setupOpen,
    teamSessionRequired,
  ]);

  useEffect(() => {
    if (projectReconciliation === "authoritative") ensureProjectReadiness();
  }, [ensureProjectReadiness, projectReconciliation]);

  useEffect(() => {
    try {
      localStorage.setItem(TEXT_SCALE_STORAGE_KEY, String(textScale));
    } catch {
      // Text size is a convenience; storage failures must not affect the project.
    }
  }, [textScale]);

  useEffect(() => {
    if (!desktop) return;
    void setDesktopWebviewZoom(textScale / 100).catch((error) => {
      setNotice({
        kind: "error",
        text: `Text size could not be applied: ${error instanceof Error ? error.message : String(error)}`,
      });
    });
  }, [desktop, textScale]);

  useEffect(() => {
    if (!desktop) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const action = textScaleShortcut(event);
      if (!action) return;
      event.preventDefault();
      setTextScale((current) => changeTextScale(current, action));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [desktop]);

  const watchersAwaitingDelivery = useMemo(
    () => watchers.some((watcher) => !watcher.notified),
    [watchers],
  );
  const mutationsDisabled = project ? projectGraphMutationsDisabled(project) : false;
  const candidateTransitionProjection = mutationsDisabled ? null : draftTransitionProjection;
  const retryConfig = useMemo(
    () => (retryTask && project ? taskRetryConfig(retryTask, project) : null),
    [project, retryTask],
  );
  const normalizedPreviewDraft = useMemo(
    () => (humanDraft ? normalizeHumanDraft(humanDraft, graph) : null),
    [graph, humanDraft],
  );
  const draftPreviewRouting = useMemo(
    () =>
      normalizedPreviewDraft
        ? humanDraftTransitionRouting(
            normalizedPreviewDraft,
            graph,
            transitionManifest,
            transitionRulesetTag,
          )
        : ({ route: "local_draft", reason: "no_manifest_trigger" } as const),
    [graph, normalizedPreviewDraft, transitionManifest, transitionRulesetTag],
  );
  const presentedTransitionProjection = transitionProjectionForRoute(
    candidateTransitionProjection,
    draftPreviewRouting.route,
  );
  const presentedExperimentControl =
    presentedTransitionProjection?.experiment_control ?? project?.experiment_control ?? {};
  const experimentWrapupPollingActive = experimentControlsNeedWrapupPolling(
    project?.experiment_control ?? {},
  );
  useEffect(() => {
    if (!projectId || !experimentWrapupPollingActive) return;
    const requestedProjectId = projectId;
    return startLiveEpisodePolling(
      {
        setTimeout: (callback, delay) => window.setTimeout(callback, delay),
        clearTimeout: (timeoutId) => window.clearTimeout(timeoutId),
      },
      () => reloadAuthoritativeProject(requestedProjectId),
      (error) => {
        if (!isActiveProject(requestedProjectId)) return;
        reportErrorNotice(
          `Experiment report status could not refresh: ${error instanceof Error ? error.message : String(error)}`,
        );
      },
      () => undefined,
    );
  }, [
    experimentWrapupPollingActive,
    isActiveProject,
    projectId,
    reloadAuthoritativeProject,
    reportErrorNotice,
  ]);
  const experimentControlForNode = (node: GraphNode): ExperimentControlState | null => {
    if (!project || node.type !== "experiment") return null;
    const control = presentedExperimentControl[node.id];
    if (!control) {
      throw new Error(`Experiment ${node.id} is missing its backend control projection.`);
    }
    return control;
  };
  const presentedGraph = useMemo(
    () =>
      attentionGraphForProjection(
        graph,
        presentedTransitionProjection,
        draftPreviewRouting.route,
        mutationsDisabled ? null : humanDraft,
      ),
    [
      graph,
      presentedTransitionProjection,
      draftPreviewRouting.route,
      mutationsDisabled,
      humanDraft,
    ],
  );
  const presentedAttention = projectAttentionForPresentation(
    project,
    presentedTransitionProjection,
  );
  const experimentStartRequiresSync = experimentStartNeedsSync(presentedTransitionProjection);
  const attentionGraph = presentedGraph;
  const glossaryIndex = useMemo(
    () => buildGlossaryIndex(presentedGraph.glossary),
    [presentedGraph.glossary, presentedGraph.revision],
  );
  const openNodeById = (nodeId: string) => openNode(presentedGraph.nodes[nodeId] ?? null);
  const openRelatedNode = (sourceSlot: DetailWindowSlot, nodeId: string) => {
    openRelatedGraphNode(sourceSlot, presentedGraph.nodes[nodeId] ?? null);
  };
  const restoreDockedNode = (nodeId: string) => {
    restoreDockedGraphNode(nodeId, presentedGraph.nodes[nodeId] ?? null);
  };
  const dockedNodes = dockedNodeIds.flatMap((nodeId) => {
    const node = presentedGraph.nodes[nodeId];
    return node ? [{ nodeId, node }] : [];
  });
  const nodeTitles = useMemo(
    () =>
      Object.fromEntries(Object.values(presentedGraph.nodes).map((node) => [node.id, node.title])),
    [presentedGraph.nodes],
  );
  const conversations = useMemo(
    () =>
      groupChatConversations(
        visibleChatSummaries,
        tasks,
        nodeTitles,
        project?.name ?? "Project",
        draftConversations,
      ),
    [draftConversations, nodeTitles, project?.name, tasks, visibleChatSummaries],
  );
  useEffect(() => {
    if (selectedExperimentChatId && floatingChat?.chatId === selectedExperimentChatId) {
      setFloatingChat(null);
    }
  }, [floatingChat?.chatId, selectedExperimentChatId]);
  const draftChangeCount = humanDraftChangeCount(humanDraft);
  const committableDraftCount = humanDraftCommittableCount(humanDraft, graph);
  const behindDraftCount = humanDraftBehindCount(humanDraft, graph);
  const ontologyDraftIsStale = humanDraftOntologyIsStale(humanDraft, graph);
  useLayoutEffect(() => {
    if (mutationsDisabled || !humanDraft) {
      dispatchProjectSession({
        kind: "draft_preview_changed",
        projection: null,
        conflict: null,
        pending: false,
      });
      return;
    }
    if (committableDraftCount === 0 || ontologyDraftIsStale) {
      dispatchProjectSession({
        kind: "draft_preview_changed",
        projection: draftTransitionProjection,
        conflict: ontologyDraftIsStale
          ? "The staged ontology is based on an older canonical revision. Restage or reset it before previewing or Sync."
          : "The remaining staged node edits are behind canonical state. Reconcile or reset them before previewing or Sync.",
        pending: false,
      });
      return;
    }
    if (draftPreviewRouting.route === "local_draft") {
      dispatchProjectSession({
        kind: "draft_preview_changed",
        projection: localDraftTransitionProjection(
          applyHumanDraft(graph, humanDraft),
          project?.experiment_control ?? {},
          projectAttentionForPresentation(project, null),
          project?.primary_question ?? null,
          project?.counts ?? emptyProjectCounts(),
          transitionHead,
          transitionRulesetTag,
        ),
        conflict: null,
        pending: false,
      });
      return;
    }
    dispatchProjectSession({
      kind: "draft_preview_changed",
      projection: draftTransitionProjection,
      conflict: null,
      pending: true,
    });
  }, [
    committableDraftCount,
    dispatchProjectSession,
    draftPreviewRouting.route,
    graph,
    humanDraft,
    mutationsDisabled,
    ontologyDraftIsStale,
    project?.experiment_control,
    project?.attention,
    transitionHead,
    transitionRulesetTag,
  ]);

  useEffect(() => {
    if (
      !apiBase ||
      !projectId ||
      !project ||
      projectReconciliation !== "authoritative" ||
      !normalizedPreviewDraft ||
      committableDraftCount === 0 ||
      ontologyDraftIsStale ||
      mutationsDisabled ||
      draftPreviewRouting.route !== "backend_preview"
    )
      return;
    const requestedProjectId = projectId;
    const request = toHumanSyncRequest(normalizedPreviewDraft, graph);
    let cancelled = false;
    void api<TransitionPreviewResponse>(graphPath(`${apiBase}/sync/preview`), {
      method: "POST",
      body: JSON.stringify(request),
    })
      .then((response) => {
        if (cancelled || !isActiveGraph(requestedProjectId)) return;
        const projection = decodeProjectTransitionResponse(response.projection);
        const previewBaseHead = projection.base_head;
        if (!previewBaseHead) {
          dispatchProjectSession({
            kind: "draft_preview_changed",
            projection: getProjectSessionState().draftTransitionProjection,
            conflict: "Staged transition preview omitted its canonical base head.",
            pending: false,
          });
          return;
        }
        const traceMismatch = previewTraceMismatch(response, projection);
        if (traceMismatch) {
          dispatchProjectSession({
            kind: "draft_preview_changed",
            projection: getProjectSessionState().draftTransitionProjection,
            conflict: traceMismatch,
            pending: false,
          });
          return;
        }
        const currentProjection: ProjectTransitionProjection<
          GraphState,
          Record<string, ExperimentControlState>
        > = {
          head: transitionHead,
          graph,
          attention: project.attention,
          experiment_control: project.experiment_control,
          primary_question: project.primary_question ?? null,
          counts: project.counts,
          ruleset_tag: transitionRulesetTag,
          transition_id: transitionHead.transition_id,
          canonical: true,
        };
        const structuralRefusal = transitionSnapshotRefusal(currentProjection, {
          kind: "preview",
          snapshot: projection,
          expected_base_head: transitionHead,
          manifest_ruleset_tag: null,
        });
        if (structuralRefusal) {
          dispatchProjectSession({
            kind: "draft_preview_changed",
            projection: getProjectSessionState().draftTransitionProjection,
            conflict: `Staged transition preview was refused: ${structuralRefusal}.`,
            pending: false,
          });
          return;
        }
        if (
          (transitionRulesetTag && transitionRulesetTag !== projection.ruleset_tag) ||
          (transitionManifest && transitionManifest.ruleset_tag !== projection.ruleset_tag)
        ) {
          dispatchProjectSession({
            kind: "preview_ruleset_invalidated",
            project_id: requestedProjectId,
            head: previewBaseHead,
            ruleset_tag: projection.ruleset_tag,
            manifest: transitionManifest,
          });
          return;
        }
        const matchingManifestTag =
          transitionManifest?.ruleset_tag === transitionRulesetTag
            ? transitionManifest.ruleset_tag
            : null;
        const refusal = transitionSnapshotRefusal(currentProjection, {
          kind: "preview",
          snapshot: projection,
          expected_base_head: transitionHead,
          manifest_ruleset_tag: matchingManifestTag,
        });
        if (refusal) {
          dispatchProjectSession({
            kind: "draft_preview_changed",
            projection: getProjectSessionState().draftTransitionProjection,
            conflict: `Staged transition preview was refused: ${refusal}.`,
            pending: false,
          });
          return;
        }
        const next = reduceProjectTransitionProjection(currentProjection, {
          kind: "preview",
          snapshot: projection,
          expected_base_head: transitionHead,
          manifest_ruleset_tag: matchingManifestTag,
        });
        dispatchProjectSession({
          kind: "preview_applied",
          project_id: requestedProjectId,
          projection: next,
          base_head: previewBaseHead,
        });
      })
      .catch((error) => {
        if (cancelled || !isActiveGraph(requestedProjectId)) return;
        dispatchProjectSession({
          kind: "draft_preview_changed",
          projection: getProjectSessionState().draftTransitionProjection,
          conflict: error instanceof Error ? error.message : String(error),
          pending: false,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [
    apiBase,
    graphPath,
    isActiveGraph,
    committableDraftCount,
    dispatchProjectSession,
    draftPreviewRouting.route,
    graph,
    getProjectSessionState,
    isActiveProject,
    mutationsDisabled,
    normalizedPreviewDraft,
    ontologyDraftIsStale,
    project,
    projectId,
    projectReconciliation,
    transitionHead,
    transitionManifest,
    transitionRulesetTag,
  ]);
  const chatsIndicator = chatIndicator(tasks, unreadChatTaskIds);
  const hasActiveTasks = projectTasks.some(isActiveTask);

  const changeAppTextScale = (action: TextScaleAction) => {
    setTextScale((current) => changeTextScale(current, action));
  };

  const openChats = (preferredChatId?: string | null) => {
    const nextChatId =
      preferredChatId ??
      chatEntryConversationId(conversations, activityTask, unreadChatTaskIds, selectedChatId);
    selectChat(nextChatId);
    setFloatingChat(null);
    clearNodeSelections();
    changeView("chats");
  };

  useEffect(() => {
    if (!desktop || !backendSessionReady) return;
    const stopListening = listenForArtifactChatNavigation(async (hash, expiresAt) => {
      if (Date.now() >= expiresAt) throw new Error("Chat navigation timed out.");
      await new Promise<void>((resolve, reject) => {
        pendingArtifactChatNavigation.current?.reject(new Error("Chat navigation was replaced."));
        pendingArtifactChatNavigation.current = { hash, expiresAt, resolve, reject };
        if (window.location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
        else window.location.hash = hash;
      });
      if (Date.now() >= expiresAt) throw new Error("Chat navigation timed out.");
      await desktopShowReady();
    });
    return () => {
      stopListening();
      pendingArtifactChatNavigation.current?.reject(new Error("RCP disconnected."));
      pendingArtifactChatNavigation.current = null;
    };
  }, [desktop, backendSessionReady]);

  useEffect(() => {
    if (
      !requestedChat.chatId ||
      loading ||
      view !== "chats" ||
      !backendSessionReady ||
      project?.id !== requestedChat.projectId ||
      !sameGraphTarget(graphTarget, requestedChat.graphTarget)
    )
      return;
    let cancelled = false;
    const pending = pendingArtifactChatNavigation.current;
    const navigation = pending?.hash === requestedChat.hash ? pending : null;
    void loadChatTranscript(apiBase, requestedChat.chatId, api, graphTarget)
      .then((transcript) => {
        if (cancelled) return;
        if (navigation && Date.now() >= navigation.expiresAt)
          throw new Error("Chat navigation timed out.");
        selectCanonicalChat(transcript);
        clearNodeSelections();
        navigation?.resolve();
      })
      .catch((error) => {
        if (cancelled) return;
        const message = `Conversation could not be opened: ${String(error)}`;
        reportErrorNotice(message);
        navigation?.reject(new Error(message));
      })
      .finally(() => {
        if (cancelled) return;
        if (pendingArtifactChatNavigation.current === navigation)
          pendingArtifactChatNavigation.current = null;
        setRequestedChat((current) =>
          current === requestedChat ? { ...current, chatId: undefined } : current,
        );
      });
    return () => {
      cancelled = true;
    };
  }, [
    requestedChat,
    loading,
    view,
    backendSessionReady,
    project?.id,
    graphTarget,
    apiBase,
    selectCanonicalChat,
    clearNodeSelections,
    reportErrorNotice,
  ]);

  useEffect(() => {
    if (mutationsDisabled) {
      closeRunDialog();
      closeAutoResearchDialog();
    }
  }, [mutationsDisabled]);

  useEffect(() => {
    const visibleChatId = visibleUnreadChatId(view, selectedChatId, selectedExperimentChatId);
    if (recordTaskUpdates(tasks, visibleChatId)) {
      if (projectId) {
        void refreshChatSummaries(projectId, apiBase).catch((error) => {
          setNotice({
            kind: "error",
            text: `Chats could not be refreshed: ${error instanceof Error ? error.message : String(error)}`,
          });
        });
      }
    }
  }, [
    apiBase,
    graphPath,
    isActiveGraph,
    projectId,
    refreshChatSummaries,
    selectedChatId,
    selectedExperimentChatId,
    tasks,
    view,
  ]);

  useEffect(() => {
    const visibleChatId = visibleUnreadChatId(view, selectedChatId, selectedExperimentChatId);
    markVisibleChatRead(tasks, visibleChatId);
  }, [selectedChatId, selectedExperimentChatId, tasks, view]);

  useEffect(() => {
    if (!projectId || !hasActiveTasks) return;
    let stopped = false;
    let timer = 0;
    let consecutiveFailures = 0;
    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async () => {
      let next: AgentTask[];
      try {
        next = await api<AgentTask[]>(`/api/projects/${encodeURIComponent(projectId)}/tasks`);
      } catch (error) {
        if (!stopped) {
          setNotice({
            kind: "error",
            text: error instanceof Error ? error.message : String(error),
          });
          void reverifyIdentity("active-task-poll-failure");
          consecutiveFailures += 1;
          schedule(Math.min(8000, 1000 * 2 ** (consecutiveFailures - 1)));
        }
        return;
      }
      if (stopped) return;
      const recoveredAfterFailure = consecutiveFailures > 0;
      consecutiveFailures = 0;
      if (recoveredAfterFailure) void reverifyIdentity("active-task-poll-recovered");
      const terminalTasks = consumeTerminalTasks(next);
      if (terminalTasks.length > 0) {
        void api<AgentUsageSnapshot>(`/api/projects/${encodeURIComponent(projectId)}/usage`).then(
          (nextUsage) => {
            if (!stopped && isActiveProject(projectId)) setUsage(nextUsage);
          },
        );
        if (terminalTasks.some(terminalTaskNeedsAuthoritativeProjectReload)) {
          try {
            await reloadAuthoritativeProject();
          } catch (error) {
            if (!stopped) {
              setNotice({
                kind: "error",
                text: error instanceof Error ? error.message : String(error),
              });
            }
          }
        } else if (
          terminalTasks.some((task) => task.kind === "node_chat" || task.kind === "project_chat")
        ) {
          try {
            const nextWatchers = await api<WatcherRecord[]>(
              graphPath(`/api/projects/${encodeURIComponent(projectId)}/watchers`),
            );
            if (!stopped) setWatchers(nextWatchers);
          } catch (error) {
            if (!stopped) {
              setNotice({
                kind: "error",
                text: error instanceof Error ? error.message : String(error),
              });
            }
          }
        }
      }
      replaceTasks(next);
      if (next.some(isActiveTask)) schedule(1000);
    };
    schedule(500);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [consumeTerminalTasks, hasActiveTasks, projectId, graphTarget, reloadAuthoritativeProject]);

  useEffect(() => {
    if (!projectId || !watchersAwaitingDelivery) return;
    const requestedProjectId = projectId;
    const base = `/api/projects/${encodeURIComponent(requestedProjectId)}`;
    let stopped = false;
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(() => void poll(), 5000);
    };
    const poll = async () => {
      const requestId = beginProjectSnapshotRequest(requestedProjectId);
      try {
        const {
          watchers: nextWatchers,
          tasks: nextTasks,
          project: nextProject,
        } = await loadExperimentWatcherPoll(api, base, graphTarget);
        if (
          !stopped &&
          isActiveProject(requestedProjectId) &&
          projectSnapshotRequestIsCurrent(requestedProjectId, requestId)
        ) {
          const hasUnseenWatcherResults = recordWatcherResults(nextTasks);
          const applied = applyProjectSnapshot(
            nextProject,
            authoritativeProjectId.current === requestedProjectId,
            { projectId: requestedProjectId, requestId },
          );
          if (!applied) return;
          authoritativeProjectId.current = requestedProjectId;
          setProjectReconciliation("authoritative");
          setWatchers(nextWatchers);
          replaceTasks(nextTasks);
          if (hasUnseenWatcherResults) {
            void refreshChatSummaries(requestedProjectId, base).catch((error) => {
              if (!stopped && isActiveProject(requestedProjectId)) {
                reportErrorNotice(
                  `Chats could not be refreshed: ${error instanceof Error ? error.message : String(error)}`,
                );
              }
            });
          }
        }
      } catch (error) {
        if (!stopped && isActiveProject(requestedProjectId)) {
          reportErrorNotice(
            `Watcher status could not refresh: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      } finally {
        if (!stopped) schedule();
      }
    };
    schedule();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [
    applyProjectSnapshot,
    graphPath,
    isActiveGraph,
    beginProjectSnapshotRequest,
    isActiveProject,
    projectId,
    projectSnapshotRequestIsCurrent,
    refreshChatSummaries,
    reportErrorNotice,
    watchersAwaitingDelivery,
  ]);

  const pendingProposals = useMemo(
    () =>
      presentedAttention.pending_proposal_ids.map((proposalId) => {
        const proposal = attentionGraph.proposals[proposalId];
        if (!proposal) {
          throw new Error(`Attention references missing presented Proposal ${proposalId}.`);
        }
        return proposal;
      }),
    [attentionGraph.proposals, presentedAttention.pending_proposal_ids],
  );
  const attentionDecisions = useMemo(
    () =>
      decisionsAwaitingChoice(
        presentedAttention.decisions_awaiting_choice_ids,
        attentionGraph.nodes,
        presentedGraph.nodes,
      ),
    [attentionGraph.nodes, presentedAttention.decisions_awaiting_choice_ids, presentedGraph.nodes],
  );
  const openBlockers = useMemo(
    () => humanAttentionBlockers(presentedAttention.open_blocker_ids, presentedGraph.nodes),
    [presentedAttention.open_blocker_ids, presentedGraph.nodes],
  );
  const rejectedPatches = useMemo(
    () =>
      graph.validation_messages.filter(
        (message) =>
          message.level === "reject" &&
          !dismissedHistoryNoticeIds.has(validationNoticeId(message)) &&
          !(typeof message.patch_revision === "number" && message.patch_revision < graph.revision),
      ),
    [dismissedHistoryNoticeIds, graph.revision, graph.validation_messages],
  );

  const updateHumanDraft = (update: (draft: HumanDraft) => HumanDraft) => {
    if (!projectId || mutationsDisabled) return;
    setNotice(null);
    const { next } = updateProjectHumanDraft(projectId, graph, update);
    try {
      persistProjectHumanDraft(localStorage, projectId, next.humanDraft, graphTarget);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
    }
  };

  const resetHumanDraft = () => {
    if (!projectId) return;
    dispatchProjectSession({ kind: "human_draft_updated", project_id: projectId, draft: null });
    try {
      localStorage.removeItem(humanDraftStorageKey(projectId, graphTarget));
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
    }
  };

  const syncHumanDraft = async () => {
    if (
      !projectId ||
      !project ||
      projectReconciliation !== "authoritative" ||
      !humanDraft ||
      syncingDraft ||
      draftPreviewPending ||
      draftPreviewConflict ||
      ontologyDraftIsStale ||
      mutationsDisabled
    )
      return;
    const requestedProjectId = projectId;
    const expectedGraph = graph;
    const expectedProject = project;
    const expectedHead = transitionHead;
    const normalized = normalizeHumanDraft(humanDraft, graph);
    if (humanDraftCommittableCount(normalized, graph) === 0) return;
    const request = toHumanSyncRequest(normalized, graph);
    const fence = beginProjectSync(requestedProjectId, expectedHead);
    if (!fence) return;
    setNotice(null);
    let committedResponseReceived = false;
    const reconcileRequestedProject = async () => {
      if (isActiveGraph(requestedProjectId)) {
        await reloadAuthoritativeProject(requestedProjectId);
      } else {
        // The saved draft is reconciled against its exact target on next open.
        if (expectedHead.target.kind === "main") await heartbeatProjectCache(requestedProjectId);
      }
    };
    try {
      const response = await api<ProjectTransitionResponse>(graphPath(`${apiBase}/sync`), {
        method: "POST",
        body: JSON.stringify(request),
      });
      committedResponseReceived = true;
      dispatchProjectSession({
        kind: "activate",
        project_id: getActiveProjectId(),
        graph_target: activeGraphTargetRef.current,
      });
      const disposition = transitionSyncCompletionDisposition(
        getProjectSessionState().transitionCoordinator,
        fence,
      );
      if (
        disposition !== "apply" ||
        getProjectSessionState().renderedRevision !== fence.expected_head.revision
      ) {
        try {
          await reconcileRequestedProject();
          if (isActiveGraph(requestedProjectId)) {
            setNotice({ kind: "info", text: "Sync committed and canonical state was refreshed." });
          }
        } catch (error) {
          if (isActiveGraph(requestedProjectId)) {
            setNotice({
              kind: "error",
              text: `Sync committed, but canonical state could not be refreshed: ${error instanceof Error ? error.message : String(error)}`,
            });
          }
        }
        return;
      }
      const projection = decodeProjectTransitionResponse(response);
      if (projection.head.revision !== expectedHead.revision + 1) {
        throw new Error("Committed transition response did not advance exactly one revision.");
      }
      const currentProjection: ProjectTransitionProjection<
        GraphState,
        Record<string, ExperimentControlState>
      > = {
        head: expectedHead,
        graph: expectedGraph,
        attention: expectedProject.attention,
        experiment_control: expectedProject.experiment_control,
        primary_question: expectedProject.primary_question ?? null,
        counts: expectedProject.counts,
        ruleset_tag: transitionRulesetTag,
        transition_id: expectedHead.transition_id,
        canonical: true,
      };
      const refusal = transitionSnapshotRefusal(currentProjection, {
        kind: "canonical",
        snapshot: projection,
      });
      if (refusal) throw new Error(`Committed transition response was refused: ${refusal}.`);
      const committed = reduceProjectTransitionProjection(currentProjection, {
        kind: "canonical",
        snapshot: projection,
      }) as ProjectTransitionResponse;
      const nextGraph = committed.graph;
      const { previous: previousSession, next: committedSession } = dispatchProjectSession({
        kind: "committed_transition_applied",
        project_id: requestedProjectId,
        projection: committed,
        submitted_draft: normalized,
      });
      if (
        committedSession === previousSession ||
        committedSession.project?.id !== requestedProjectId ||
        committedSession.renderedRevision !== nextGraph.revision
      ) {
        throw new Error("Committed transition response lost the active project session.");
      }
      try {
        persistProjectHumanDraft(
          localStorage,
          requestedProjectId,
          committedSession.humanDraft,
          expectedHead.target,
        );
      } catch (error) {
        setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
      }
      applyCanonicalProject(committedSession.project, true);
      reconcileFloatingChat(nextGraph.nodes, false);
      if (expectedHead.target.kind === "branch") await reload();
      setNotice({
        kind: "info",
        text: humanSyncSuccessNotice(nextGraph.revision, request.proposals, nextGraph),
      });
    } catch (error) {
      if (committedResponseReceived) {
        try {
          await reconcileRequestedProject();
        } catch (reloadError) {
          if (isActiveGraph(requestedProjectId)) {
            setNotice({
              kind: "error",
              text: `Sync committed, but its response was refused and canonical refresh failed: ${reloadError instanceof Error ? reloadError.message : String(reloadError)}`,
            });
          }
          return;
        }
        if (isActiveGraph(requestedProjectId)) {
          setNotice({
            kind: "error",
            text: `Sync committed, but its response could not be applied directly: ${error instanceof Error ? error.message : String(error)}`,
          });
        }
        return;
      }
      const failure = humanSyncFailure(error);
      if (isActiveGraph(requestedProjectId)) {
        setNotice({ kind: "error", text: failure.text });
      }
      if (failure.revisionConflict) {
        try {
          await reconcileRequestedProject();
        } catch {}
      }
    } finally {
      dispatchProjectSession({ kind: "sync_finished", fence });
    }
  };

  const startAgentTask = useCallback(
    async (kind: AgentTaskKind, request: AgentTaskRequest): Promise<AgentTask> => {
      const finishTaskStart = beginTaskStart();
      if (!finishTaskStart) throw new Error("Another task start is already being submitted.");
      try {
        const task = await api<AgentTask>(
          kind === "node_chat" || kind === "project_chat"
            ? graphPath(`${apiBase}/tasks/${kind}`)
            : `${apiBase}/tasks/${kind}`,
          {
            method: "POST",
            body: JSON.stringify(request),
          },
        );
        if (
          (kind === "node_chat" || kind === "project_chat") &&
          !sameGraphTarget(task.graph_target, graphTarget)
        )
          throw new Error("Conversation start returned a different graph target.");
        if (projectId && isActiveGraph(projectId)) {
          recordStartedTask(task);
          setNotice(null);
        }
        return task;
      } finally {
        finishTaskStart();
      }
    },
    [apiBase, graphPath, graphTarget, projectId, isActiveGraph, beginTaskStart, recordStartedTask],
  );
  const loadWebMcpConversation = useCallback(
    (chatId: string) => loadChatTranscript(apiBase, chatId, api, graphTarget),
    [apiBase, graphTarget],
  );
  const loadWebMcpTask = useCallback(
    async (operationId: string): Promise<AgentTask | null> => {
      try {
        return await api<AgentTask>(`${apiBase}/tasks/${encodeURIComponent(operationId)}`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    [apiBase],
  );
  const webMcpConversationSource = useMemo(
    () => ({ loadTranscript: loadWebMcpConversation, loadTask: loadWebMcpTask }),
    [loadWebMcpConversation, loadWebMcpTask],
  );
  const loadWebMcpEpisode = useCallback(
    async (episodeId: string): Promise<Episode | null> => {
      try {
        return (await loadEpisodes(apiBase, undefined, episodeId))[0] ?? null;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    [apiBase],
  );
  const webMcpArtifactSource = useMemo(
    () => ({ loadEpisode: loadWebMcpEpisode, loadTask: loadWebMcpTask }),
    [loadWebMcpEpisode, loadWebMcpTask],
  );
  const createWebMcpConversation = useCallback(
    (kind: ChatKind, node: GraphNode | null) => {
      if (!project) throw new Error("No RCP project is open.");
      return startConversation(kind, node, project.name);
    },
    [project, startConversation],
  );
  const startWebMcpConversationTurn = useCallback(
    (submission: ConversationTurnSubmission) => startConversationTurn(startAgentTask, submission),
    [startAgentTask],
  );

  const stopWatcher = async (watcherId: string) => {
    if (!apiBase) return;
    try {
      await api<WatcherRecord>(`${apiBase}/watchers/${encodeURIComponent(watcherId)}/stop`, {
        method: "POST",
      });
      const nextWatchers = await api<WatcherRecord[]>(graphPath(`${apiBase}/watchers`));
      if (projectId && isActiveGraph(projectId)) setWatchers(nextWatchers);
      // Retiring an observer can release an Experiment that was held shut by it,
      // so the control projection is re-read here rather than waiting for a poll.
      await reload();
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
    }
  };

  const requestExperimentStop = useCallback(
    async (nodeId: string, episodeId: string | null = null): Promise<void> => {
      if (!apiBase) throw new Error("No RCP project is open.");
      if (experimentStopId) throw new Error("Another Experiment Stop is already being submitted.");
      const finishExperimentStop = beginExperimentStop(nodeId);
      try {
        await api<unknown>(graphPath(experimentStopPath(apiBase, nodeId, episodeId)), {
          method: "POST",
        });
        try {
          await Promise.all([reload(), episodeId ? refreshExperimentLoops() : Promise.resolve()]);
        } catch (error) {
          setNotice({
            kind: "error",
            text: `Stop was requested, but Runs could not refresh: ${error instanceof Error ? error.message : String(error)}`,
          });
        }
      } finally {
        finishExperimentStop();
      }
    },
    [apiBase, graphPath, beginExperimentStop, experimentStopId, refreshExperimentLoops, reload],
  );
  const stopExperimentLoop = useCallback(
    async (nodeId: string, episodeId: string | null = null) => {
      try {
        await requestExperimentStop(nodeId, episodeId);
      } catch (error) {
        setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
      }
    },
    [requestExperimentStop],
  );

  const checkExperimentWatcher = async (watcherId: string) => {
    if (
      !apiBase ||
      watcherCheckId ||
      taskStarting ||
      taskActionId ||
      experimentStopId ||
      mutationsDisabled
    )
      return;
    const finishWatcherCheck = beginWatcherCheck(watcherId);
    try {
      const checked = await api<WatcherRecord>(
        `${apiBase}/watchers/${encodeURIComponent(watcherId)}/check`,
        { method: "POST" },
      );
      setWatchers((current) =>
        current.map((watcher) => (watcher.watcher_id === checked.watcher_id ? checked : watcher)),
      );
      await reload();
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      finishWatcherCheck();
    }
  };

  const startExperiment = useCallback(
    async (node: GraphNode, invocationCeiling?: number): Promise<AgentTask> => {
      if (!project || node.type !== "experiment") {
        throw new Error("The requested Experiment is not present in the open project.");
      }
      if (mutationsDisabled) throw new Error("Graph mutations are currently disabled.");
      if (experimentStartRequiresSync) {
        throw new Error("Sync staged graph changes before starting an episode.");
      }
      const control = project.experiment_control?.[node.id];
      if (!control?.can_start) {
        throw new Error(control?.reasons.join(" ") ?? "This experiment is not ready to run.");
      }
      const finishTaskStart = beginTaskStart();
      if (!finishTaskStart) throw new Error("Another task start is already being submitted.");
      try {
        const chatId = ensureConversation(conversations, "node_chat", node, project.name);
        const profile = project.agent_profiles.node_chat;
        const task = await api<AgentTask>(
          graphPath(`${apiBase}/experiments/${encodeURIComponent(node.id)}/run`),
          {
            method: "POST",
            body: JSON.stringify({
              provider: profile.provider,
              model: profile.model || null,
              reasoning: profile.reasoning,
              run_on: profile.run_on,
              run_truth_scope: runScope.length ? runScope : project.default_run_truth_scope,
              chat_id: chatId,
              // Omitted unless the human reauthorized an explicit count; the
              // backend then keeps the Experiment node's own limit.
              ...(invocationCeiling === undefined ? {} : { invocation_ceiling: invocationCeiling }),
            }),
          },
        );
        if (!sameGraphTarget(task.graph_target, graphTarget))
          throw new Error("Experiment start returned a different graph target.");
        if (!isActiveGraph(project.id)) return task;
        recordStartedTask(task);
        setNotice(null);
        setFloatingChat(null);
        showExperiment(node.id);
        try {
          await Promise.all([reload(), refreshEpisodes()]);
        } catch (error) {
          setNotice({
            kind: "error",
            text: `The Experiment started, but Runs could not refresh: ${error instanceof Error ? error.message : String(error)}`,
          });
        }
        return task;
      } finally {
        finishTaskStart();
      }
    },
    [
      apiBase,
      graphPath,
      graphTarget,
      isActiveGraph,
      beginTaskStart,
      conversations,
      ensureConversation,
      experimentStartRequiresSync,
      mutationsDisabled,
      project,
      recordStartedTask,
      refreshEpisodes,
      reload,
      runScope,
      setFloatingChat,
      showExperiment,
    ],
  );
  const runExperiment = useCallback(
    async (node: GraphNode, invocationCeiling?: number) => {
      try {
        await startExperiment(node, invocationCeiling);
      } catch (caught) {
        setNotice({
          kind: "error",
          text: caught instanceof Error ? caught.message : String(caught),
        });
      }
    },
    [startExperiment],
  );
  const startWebMcpExperiment = useCallback(
    async (node: GraphNode): Promise<AgentTask> => {
      if (!project) throw new Error("No RCP project is open.");
      const pendingProjectId = project.id;
      setWebMcpExperimentStartProjectId(pendingProjectId);
      try {
        return await startExperiment(node);
      } finally {
        setWebMcpExperimentStartProjectId((current) =>
          current === pendingProjectId ? null : current,
        );
      }
    },
    [project, startExperiment],
  );

  const runAgent = async (config: AgentRunConfig, scope: string[], message: string | null) => {
    if (!project || taskStarting || mutationsDisabled) return;
    const runKind = project.last_refresh_at ? "refresh" : "seed";
    replaceRunScope(scope);
    try {
      await startAgentTask(runKind, {
        ...config,
        model: config.model || null,
        run_truth_scope: scope,
        message,
      });
      closeRunDialog();
    } catch (caught) {
      setNotice({ kind: "error", text: caught instanceof Error ? caught.message : String(caught) });
    }
  };

  const authorizeAutoResearch = async (
    invocationCeiling: number,
    startingInstruction: string | null,
  ) => {
    if (!project || !apiBase || mutationsDisabled || episodeAction || taskStarting) return;
    if (liveAutoResearchEpisode) {
      reportAutoResearchStartError("An auto-research episode is already live for this project.");
      return;
    }
    const finishTaskStart = beginTaskStart();
    if (!finishTaskStart) {
      reportAutoResearchStartError("Another task start is already being submitted.");
      return;
    }
    const finishEpisodeAction = beginEpisodeAction("start");
    if (!finishEpisodeAction) {
      finishTaskStart();
      return;
    }
    reportAutoResearchStartError(null);
    try {
      const started = await startEpisode(apiBase, {
        mode: "auto_research",
        invocation_ceiling: invocationCeiling,
        starting_instruction: startingInstruction,
      });
      replaceEpisode(started);
      replaceExactAutoResearchSelection(started.project_id, started.episode_id);
      closeAutoResearchDialog();
      changeView("execution");
      try {
        await reload();
      } catch (error) {
        setNotice({
          kind: "error",
          text: `Auto-research started, but Runs could not refresh: ${error instanceof Error ? error.message : String(error)}`,
        });
      }
    } catch (error) {
      reportAutoResearchStartError(error instanceof Error ? error.message : String(error));
    } finally {
      finishTaskStart();
      finishEpisodeAction();
    }
  };

  const requestEpisodeStop = async (episodeId: string) => {
    if (!apiBase || episodeAction) return;
    const finishEpisodeAction = beginEpisodeAction(`stop:${episodeId}`);
    if (!finishEpisodeAction) return;
    try {
      replaceEpisode(await stopEpisode(apiBase, episodeId));
      await refreshEpisodes();
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally {
      finishEpisodeAction();
    }
  };

  const requestEpisodeArchive = async (
    requestedProjectId: string,
    episodeId: string,
    archived: boolean,
  ) => {
    const finishEpisodeAction = beginEpisodeAction(`archive:${episodeId}`);
    if (!finishEpisodeAction) throw new Error("Wait for the current episode action to finish.");
    try {
      const nextEpisode = await archiveEpisode(
        `/api/projects/${encodeURIComponent(requestedProjectId)}`,
        episodeId,
        archived,
      );
      replaceEpisode(nextEpisode);
      replaceEpisodeRunArchive(nextEpisode);
      try {
        if (isActiveProject(requestedProjectId)) {
          await Promise.all([refreshEpisodes(), refreshProjectExperimentLoops(requestedProjectId)]);
        } else {
          await refreshSpaceRuns();
        }
      } catch (error) {
        setNotice({
          kind: "error",
          text: `Run ${archived ? "archived" : "unarchived"}, but Runs could not refresh: ${error instanceof Error ? error.message : String(error)}`,
        });
      }
    } finally {
      finishEpisodeAction();
    }
  };

  const requestEpisodeContinuation = async (episodeId: string, invocationCeiling: number) => {
    if (!apiBase || episodeAction) return;
    const finishEpisodeAction = beginEpisodeAction(`continue:${episodeId}`);
    if (!finishEpisodeAction) return;
    try {
      const requestId = continuationRequestIds.current.get(episodeId) ?? crypto.randomUUID();
      continuationRequestIds.current.set(episodeId, requestId);
      const nextEpisode = await continueEpisode(apiBase, episodeId, invocationCeiling, requestId);
      continuationRequestIds.current.delete(episodeId);
      replaceEpisode(nextEpisode);
      // Continuing ends one episode and starts its successor, so an exact route
      // pinned to the predecessor follows the run instead of handing off to History.
      if (nextEpisode.mode === "auto_research") {
        replaceExactAutoResearchSelection(nextEpisode.project_id, nextEpisode.episode_id);
      } else {
        replaceExactExperimentEpisode(nextEpisode);
      }
      await reload();
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally {
      finishEpisodeAction();
    }
  };

  const requestEpisodeMerge = async (episodeId: string) => {
    if (!apiBase || episodeAction) return;
    const finishEpisodeAction = beginEpisodeAction(`merge:${episodeId}`);
    if (!finishEpisodeAction) return;
    try {
      const nextEpisode = await mergeEpisodeToMain(apiBase, episodeId);
      replaceEpisode(nextEpisode);
      const mergeTask = activeBranchMergeTask(nextEpisode);
      if (mergeTask) recordStartedTask(mergeTask);
      await reload();
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally {
      finishEpisodeAction();
    }
  };

  const messageEpisodeOrchestrator = async (episodeId: string, body: string) => {
    if (!apiBase || !projectId || episodeAction) return;
    const finishEpisodeAction = beginEpisodeAction(`message:${episodeId}`);
    if (!finishEpisodeAction) return;
    try {
      const saved = await sendEpisodeMessage(apiBase, episodeId, body);
      recordEpisodeMessage(projectId, episodeId, saved);
      await refreshEpisodeMessages(episodeId);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally {
      finishEpisodeAction();
    }
  };

  const operateTask = async (
    task: AgentTask,
    action: "pause" | "resume" | "retry",
    presentTask = true,
  ) => {
    if (taskActionId) return;
    if (action !== "pause" && mutationsDisabled && taskMayMutateGraph(task)) return;
    const finishTaskAction = beginTaskAction(task.operation_id);
    if (!finishTaskAction) return;
    let recoveryStarted = false;
    try {
      const next = await api<AgentTask>(`${apiBase}/tasks/${task.operation_id}/${action}`, {
        method: "POST",
      });
      recoveryStarted = true;
      upsertTask(next);
      if (presentTask) presentAgentTask(next);
      setNotice(null);
      if (taskActionNeedsAuthoritativeProjectReload(task, action)) await reload();
    } catch (caught) {
      const taskError = caught instanceof Error ? caught.message : String(caught);
      if (recoveryStarted) {
        setNotice({
          kind: "error",
          text: `Recovery started, but Runs could not refresh: ${taskError}`,
        });
        return;
      }
      if (taskActionNeedsAuthoritativeProjectReload(task, action)) {
        try {
          await reload();
        } catch (reloadError) {
          setNotice({
            kind: "error",
            text: `${taskError} Runs could not refresh: ${reloadError instanceof Error ? reloadError.message : String(reloadError)}`,
          });
          return;
        }
      }
      setNotice({ kind: "error", text: taskError });
    } finally {
      finishTaskAction();
    }
  };

  const operateEpisodeOrchestratorTask = async (
    task: AgentTask,
    action: "pause" | "resume" | "retry",
  ) => {
    await operateTask(task, action, false);
    await refreshEpisodes();
  };

  const repairGraphUpdate = async (operationId: string): Promise<void> => {
    const finishTaskRepair = beginTaskRepair(operationId);
    if (!finishTaskRepair) {
      throw new Error("Another task action is already being submitted.");
    }
    try {
      if (mutationsDisabled) {
        throw new Error("Graph repair is unavailable while replay is degraded.");
      }
      const next = await api<AgentTask>(
        `${apiBase}/tasks/${encodeURIComponent(operationId)}/repair-graph-update`,
        { method: "POST" },
      );
      recordStartedTask(next);
      setNotice(null);
    } finally {
      finishTaskRepair();
    }
  };

  const retryAgentTask = async (task: AgentTask, config: AgentRunConfig) => {
    if (taskActionId || mutationsDisabled) return;
    const finishTaskAction = beginTaskAction(task.operation_id);
    if (!finishTaskAction) return;
    let recoveryStarted = false;
    try {
      const next = await api<AgentTask>(`${apiBase}/tasks/${task.operation_id}/retry`, {
        method: "POST",
        body: JSON.stringify(taskRetryRequestBody(task, config)),
      });
      recoveryStarted = true;
      upsertTask(next);
      if (!isExperimentLoopRecovery(task)) presentAgentTask(next);
      closeRetryTask();
      setNotice(null);
      if (isExperimentLoopRecovery(task)) await reload();
    } catch (caught) {
      const taskError = caught instanceof Error ? caught.message : String(caught);
      setNotice({
        kind: "error",
        text: recoveryStarted
          ? `Recovery started, but Runs could not refresh: ${taskError}`
          : taskError,
      });
    } finally {
      finishTaskAction();
    }
  };

  const refreshAgentTask = useCallback(
    async (operationId: string): Promise<AgentTask> => {
      const next = await api<AgentTask>(`${apiBase}/tasks/${encodeURIComponent(operationId)}`);
      upsertTask(next);
      return next;
    },
    [apiBase, upsertTask],
  );

  const requestRetry = (task: AgentTask) => {
    if (task.kind === "seed" || task.kind === "refresh") {
      chooseRetryTask(task);
      return;
    }
    void operateTask(task, "retry");
  };

  const commitProjectOpen = (id: string, experimentRoute: string | null = null) => {
    if (projectId !== id) rememberProjectState(projectId);
    commitProjectRoute(id, experimentRoute);
  };
  const openProject = (id: string, experimentRoute: string | null = null) => {
    if (requestDesktopProjectOpen(id, experimentRoute)) return;
    commitProjectOpen(id, experimentRoute);
  };
  const continueDesktopProjectOpen = () => {
    continueDesktopProjectAccess(commitProjectOpen);
  };
  const projectsRef = useRef(projects);
  projectsRef.current = projects;
  const requestDesktopProjectOpenRef = useRef(requestDesktopProjectOpen);
  requestDesktopProjectOpenRef.current = requestDesktopProjectOpen;
  const commitProjectOpenRef = useRef(commitProjectOpen);
  commitProjectOpenRef.current = commitProjectOpen;
  const projectIndexWebMcpTools = useMemo(
    () =>
      projectIndexToolDefinitions(
        () => projectsRef.current,
        (id) => {
          if (requestDesktopProjectOpenRef.current(id, null)) return false;
          // Let the current tool return before switching to the project tool surface. Aborting
          // its index registration during the call makes the browser report a false stale error.
          window.setTimeout(() => commitProjectOpenRef.current(id), 0);
          return true;
        },
      ),
    [],
  );
  const {
    project: webMcpProject,
    indexAvailable: projectIndexWebMcpAvailable,
    key: webMcpSurfaceKey,
  } = webMcpSurface({ backendSessionReady, setupOpen, loading, projectId, project });
  const webMcpTools = useMemo(() => {
    if (webMcpProject) {
      const project = webMcpProject;
      return [
        ...projectReadToolDefinitions(project),
        ...projectArtifactToolDefinitions(
          project,
          tasks,
          episodes,
          showWebMcpArtifactViewer,
          webMcpArtifactSource,
        ),
        ...projectConversationToolDefinitions(
          project,
          visibleChatSummaries,
          chatSummaryTotal,
          tasks,
          webMcpConversationSource,
          taskStarting,
        ),
        ...projectConversationSendToolDefinitions(
          project,
          tasks,
          webMcpConversationSource,
          taskStarting,
          createWebMcpConversation,
          startWebMcpConversationTurn,
        ),
        ...projectExperimentToolDefinitions(
          project,
          tasks,
          watchers,
          taskStarting,
          webMcpExperimentStartProjectId === project.id,
          mutationsDisabled,
          experimentStartRequiresSync,
          startWebMcpExperiment,
        ),
        ...projectExperimentStopToolDefinitions(
          project,
          requestExperimentStop,
          experimentStopId !== null,
        ),
      ];
    }
    return projectIndexWebMcpAvailable ? projectIndexWebMcpTools : [];
  }, [
    chatSummaryTotal,
    createWebMcpConversation,
    episodes,
    experimentStartRequiresSync,
    experimentStopId,
    mutationsDisabled,
    projectIndexWebMcpAvailable,
    projectIndexWebMcpTools,
    requestExperimentStop,
    showWebMcpArtifactViewer,
    startWebMcpConversationTurn,
    startWebMcpExperiment,
    taskStarting,
    tasks,
    visibleChatSummaries,
    watchers,
    webMcpArtifactSource,
    webMcpConversationSource,
    webMcpExperimentStartProjectId,
    webMcpProject,
  ]);
  const webMcpRegistryRef = useRef<{
    surfaceKey: string;
    registry: WebMcpToolRegistry;
  } | null>(null);
  useEffect(() => {
    const current = webMcpRegistryRef.current;
    if (!webMcpSurfaceKey || webMcpTools.length === 0) {
      current?.registry.dispose();
      webMcpRegistryRef.current = null;
      return;
    }
    if (current?.surfaceKey === webMcpSurfaceKey) {
      current.registry.update(webMcpTools);
      return;
    }
    current?.registry.dispose();
    const registry = createWebMcpToolRegistry(webMcpTools);
    webMcpRegistryRef.current = registry ? { surfaceKey: webMcpSurfaceKey, registry } : null;
  }, [webMcpSurfaceKey, webMcpTools]);
  useEffect(
    () => () => {
      webMcpRegistryRef.current?.registry.dispose();
      webMcpRegistryRef.current = null;
    },
    [],
  );
  // Leaving a project returns to the index of the space you are in. A team
  // space keeps its own index, so Cmd+T means the same thing in both. Leaving
  // the space itself is the separate, explicit action below.
  const returnToProjects = () => {
    rememberProjectState(projectId);
    returnToProjectIndex();
  };

  const exitTeamSpace = () => {
    void returnDesktopToPersonal().catch((error) => {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
    });
  };

  const answerProjectInvitation = async (invitationId: string, response: "accept" | "decline") => {
    // A team space refuses a bodyless mutation: JSON-only is what stops a
    // cross-site form forging one, so even an empty body must be JSON.
    await api(`/api/project-invitations/${encodeURIComponent(invitationId)}/${response}`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await refreshProjectInvitations();
    await loadProjectIndex();
  };

  const deleteProject = async (id: string) => {
    await api(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" });
    removeProject(id);
    forgetProjectViewport(id);
    try {
      localStorage.removeItem(humanDraftStorageKey(id));
    } catch {
      // The project is already deleted; a stranded draft key must not fail the action.
    }
  };

  const activateProjectTab = (id: string) => {
    if (id === projectId) return;
    rememberProjectState(projectId);
    activateProjectRoute(id);
  };

  const closeDockedProject = (id: string) => {
    if (!closeProjectRoute(id)) return;
    forgetProjectViewport(id);
  };

  useEffect(() => {
    if (!desktop) return;
    const onProjectTabKeyDown = (event: KeyboardEvent) => {
      const action = projectTabShortcut(event, isEditableShortcutTarget(event.target));
      if (!action) return;
      if (action === "index") {
        event.preventDefault();
        returnToProjects();
        return;
      }
      const nextProjectId = adjacentProjectId(action === "previous" ? -1 : 1);
      if (!nextProjectId) return;
      event.preventDefault();
      activateProjectTab(nextProjectId);
    };
    window.addEventListener("keydown", onProjectTabKeyDown);
    return () => window.removeEventListener("keydown", onProjectTabKeyDown);
  });

  const reconnectBackend = async () => {
    await reconnectDesktopBackend(reportIdentityIssue);
  };

  const movePersonalProjectToTeam =
    desktop &&
    verifiedHealth?.space_kind === "personal" &&
    verifiedHealth.project_creation.intents.some(
      (intent) => intent.intent === "move_personal_project_to_team" && intent.eligible,
    )
      ? openMoveProjectSetup
      : undefined;
  const updateHasActiveWork =
    Boolean(activeTask) ||
    (desktopUpdate?.active_agent_tasks ?? verifiedHealth?.active_agent_tasks ?? 0) > 0;
  const applyUpdate = async () => {
    await applyDesktopShellUpdate(Boolean(activeTask), async () => {
      const identity = await reverifyIdentity("update-apply");
      return {
        ok: identity.ok,
        activeAgentTasks: identity.health?.active_agent_tasks ?? 0,
      };
    });
  };

  const updateSurface = (
    <UpdateNotice
      notice={releaseUpdate}
      identity={buildIdentity}
      desktop={desktop}
      update={desktopUpdate}
      activeWork={updateHasActiveWork}
      expanded={updateExpanded}
      applying={updateApplying}
      error={updateError}
      onExpand={expandUpdate}
      onApply={() => void applyUpdate()}
      onDismiss={dismissUpdate}
    />
  );
  const desktopAccessSurface = pendingDesktopProject ? (
    <div className="modal-backdrop desktop-access-backdrop">
      <section
        className="desktop-access-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="desktop-access-title"
        aria-describedby="desktop-access-warning"
      >
        <header>
          <FolderLock size={19} aria-hidden="true" />
          <h2 id="desktop-access-title">Project folder access</h2>
        </header>
        <p id="desktop-access-warning">
          RCP accesses only project folders you choose. macOS may ask for access when a chosen
          project is in Documents, Desktop, or iCloud Drive.
        </p>
        {desktopAccessError && (
          <div className="desktop-access-error" role="alert">
            {desktopAccessError}
          </div>
        )}
        <footer>
          <button className="button secondary" type="button" onClick={dismissDesktopProjectOpen}>
            Not now
          </button>
          <button
            className="button primary"
            type="button"
            autoFocus
            onClick={continueDesktopProjectOpen}
          >
            Continue
          </button>
        </footer>
      </section>
    </div>
  ) : null;
  const actorNameSurface = actorNamePromptOpen ? (
    <div className="modal-backdrop identity-name-backdrop">
      <form
        className="identity-name-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="identity-name-title"
        onSubmit={(event) => {
          event.preventDefault();
          void saveActorName();
        }}
      >
        <header>
          <h2 id="identity-name-title">Choose your name</h2>
        </header>
        <div className="identity-name-body">
          <p>Your chosen name is copied into permanent project history.</p>
          <label>
            Display name
            <input
              autoFocus
              autoComplete="off"
              maxLength={DISPLAY_NAME_MAX_LENGTH}
              value={actorNameDraft}
              onChange={(event) => updateActorNameDraft(event.target.value)}
            />
          </label>
        </div>
        {actorNameError && (
          <div className="identity-name-error" role="alert">
            {actorNameError}
          </div>
        )}
        <footer>
          <button
            className="button secondary"
            type="button"
            disabled={actorNameSaving}
            onClick={() => settleActorNamePrompt(false)}
          >
            Cancel
          </button>
          <button
            className="button primary"
            type="submit"
            disabled={!actorNameDraft.trim() || actorNameSaving}
          >
            {actorNameSaving ? <LoaderCircle className="spin" size={14} /> : null}
            {actorNameSaving ? "Saving" : "Save and continue"}
          </button>
        </footer>
      </form>
    </div>
  ) : null;
  const acceptanceAgentSurface = (
    <AcceptanceAgentIndicator agentMode={verifiedHealth?.agent_mode} />
  );
  const setupRoute: ProjectSetupRoute = setupOpen
    ? parseProjectSetupRoute(window.location.hash)
    : { kind: "none" };

  if (!identityReady)
    return (
      <div className="app-loading">
        <LoaderCircle className="spin" />
        <span>Verifying the RCP backend</span>
        {acceptanceAgentSurface}
      </div>
    );
  if (identityIssue)
    return (
      <div className="fatal-state reconnect-state">
        <AlertTriangle />
        <h1>Reconnect to RCP</h1>
        <p>{identityIssue}</p>
        <button
          className="button secondary"
          disabled={reconnecting}
          onClick={() => void reconnectBackend()}
        >
          {reconnecting ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}{" "}
          {backendReconnectLabel(desktop)}
        </button>
        {updateSurface}
        {acceptanceAgentSurface}
      </div>
    );
  if (!actorIdentityChecked)
    return (
      <div className="app-loading">
        <LoaderCircle className="spin" />
        <span>Verifying your identity</span>
        {acceptanceAgentSurface}
      </div>
    );
  if (teamSessionRequired)
    return (
      <>
        <TeamLoginBoundary
          spaceName={verifiedHealth?.space_name ?? null}
          onAuthenticate={authenticateTeamSession}
          onPair={pairTeamDevice}
        />
        {acceptanceAgentSurface}
      </>
    );
  if (loading)
    return (
      <div className="app-loading">
        <LoaderCircle className="spin" />
        <span>{projectId ? "Opening project" : "Reading the project index"}</span>
        {updateSurface}
        {desktopAccessSurface}
        {actorNameSurface}
        {acceptanceAgentSurface}
      </div>
    );
  if (setupOpen)
    return (
      <>
        <ProjectSetup
          key={projectSetupRouteKey(setupRoute)}
          projectCreation={verifiedHealth!.project_creation}
          onCancel={returnToProjects}
          onCreated={openProject}
          setupRoute={setupRoute}
        />
        {updateSurface}
        {desktopAccessSurface}
        {actorNameSurface}
        {acceptanceAgentSurface}
      </>
    );
  if (!projectId)
    return (
      <>
        <ProjectLanding
          themeChoice={appearance.theme}
          colorModeChoice={appearance.mode}
          onThemeChoiceChange={appearance.setTheme}
          onColorModeChoiceChange={appearance.setMode}
          palette={appearance.palette}
          projects={projects}
          invitations={projectInvitations}
          onAnswerInvitation={answerProjectInvitation}
          spaceRuns={spaceRuns}
          onOpen={openProject}
          onOpenExperiment={openProject}
          onArchiveEpisode={requestEpisodeArchive}
          onCreate={openSetup}
          projectCreation={verifiedHealth!.project_creation}
          onMovePersonalProjectToTeam={movePersonalProjectToTeam}
          onDelete={deleteProject}
          openProjectTabs={openProjectTabs}
          onActivateProjectTab={activateProjectTab}
          onCloseProjectTab={closeDockedProject}
          identity={actorIdentity}
          identityError={actorIdentityError}
          onRequestIdentityName={requestActorName}
          onExitTeamSpace={desktop ? exitTeamSpace : undefined}
        />
        {notice && (
          <button className={`toast ${notice.kind}`} onClick={() => setNotice(null)}>
            {notice.text}
          </button>
        )}
        {updateSurface}
        {desktopAccessSurface}
        {actorNameSurface}
        {acceptanceAgentSurface}
      </>
    );
  if (project?.id && project.id !== projectId)
    return (
      <div className="app-loading">
        <LoaderCircle className="spin" />
        <span>Opening project</span>
        {updateSurface}
        {desktopAccessSurface}
        {actorNameSurface}
        {acceptanceAgentSurface}
      </div>
    );
  if (!project || !paper)
    return (
      <div className="fatal-state">
        <AlertTriangle />
        <h1>Project could not be opened</h1>
        <p>{notice?.text || "The API returned no project state."}</p>
        <button className="button secondary" onClick={returnToProjects}>
          <ArrowLeft size={15} /> All projects
        </button>
        {updateSurface}
        {desktopAccessSurface}
        {actorNameSurface}
        {acceptanceAgentSurface}
      </div>
    );

  const attentionCount = pendingProposals.length + attentionDecisions.length + openBlockers.length;
  const showTrustFilter = view === "scientific" || view === "dag";
  const runKind = project.last_refresh_at ? "refresh" : "seed";
  const replayWarning = projectGraphMutationFailureLabel(project);
  const selectedExperimentExecution = projectExperimentExecution(
    Object.values(presentedGraph.nodes),
    tasks,
    watchers,
    presentedExperimentControl,
    selectedExperimentRoute,
    selectedBranchExperiment,
  );
  const selectedMainRouteIsStale = selectedExperimentExecution.staleMainRoute !== null;
  const selectedExperimentNode = selectedExperimentRunId
    ? selectedExperimentUsesBranch
      ? (selectedBranchExperiment?.node ?? null)
      : selectedMainRouteIsStale
        ? null
        : (presentedGraph.nodes[selectedExperimentRunId] ?? null)
    : null;
  const selectedExperimentControl = selectedExperimentRunId
    ? selectedExperimentUsesBranch
      ? (selectedBranchExperiment?.control ?? null)
      : selectedMainRouteIsStale
        ? null
        : (presentedExperimentControl[selectedExperimentRunId] ?? null)
    : null;
  const selectedExperimentNodes = Object.fromEntries(
    selectedExperimentExecution.nodes.map((node) => [node.id, node]),
  );
  const selectedExperimentConversation =
    selectedExperimentChatId && selectedExperimentNode?.type === "experiment" ? (
      <Suspense
        fallback={
          <div className="project-view-loading" aria-label="Loading run conversation">
            <LoaderCircle className="spin" />
          </div>
        }
      >
        <NodeChat
          key={selectedExperimentChatId}
          project={project}
          node={selectedExperimentNode}
          nodes={selectedExperimentNodes}
          glossaryIndex={glossaryIndex}
          runScope={selectedExperimentControl?.operational?.session?.run_truth_scope ?? runScope}
          tasks={selectedExperimentExecution.tasks}
          watchers={selectedExperimentExecution.watchers}
          historyMessages={chatTranscripts.get(selectedExperimentChatId)?.messages}
          chatId={selectedExperimentChatId}
          presentation="workspace"
          fixedConversation
          readOnly={selectedExperimentUsesBranch}
          graphChangesDisabled={mutationsDisabled}
          onStartTask={startAgentTask}
          onResumeTask={(task) => void operateTask(task, "resume")}
          onRetryTask={requestRetry}
          onRefreshTask={refreshAgentTask}
          onInspectTask={selectTaskInspector}
          onOpenInbox={() => changeView("attention")}
          onRepairGraphUpdate={repairGraphUpdate}
          onOpenNode={openNodeById}
          onStopWatcher={(watcherId) => void stopWatcher(watcherId)}
          onNewSession={() => undefined}
          onClose={() => undefined}
        />
      </Suspense>
    ) : undefined;

  const graphEditingProps: GraphEditingProps = {
    projectId: project.id,
    mutationsDisabled,
    onStageCustomNode: (node) => updateHumanDraft((draft) => stageCustomNode(draft, node)),
    onStageEdge: (edge) => updateHumanDraft((draft) => stageEdgeAddition(draft, graph, edge)),
    onRemoveEdge: (edgeId) => updateHumanDraft((draft) => stageEdgeRemoval(draft, graph, edgeId)),
    onUndoRemoveEdge: (edgeId) =>
      updateHumanDraft((draft) => unstageEdgeRemoval(draft, graph, edgeId)),
    draftAddedNodeIds: Object.keys(humanDraft?.custom_nodes ?? {}),
    draftAddedEdges: humanDraft?.added_edges,
    draftRemovedEdgeIds: humanDraft?.removed_edge_ids,
    draftRemovedNodeIds: humanDraft?.removed_node_ids,
    canonicalEdges: graph.edges,
  };

  return (
    <div className="app-shell overview-shell">
      {acceptanceAgentSurface}
      {!projectHeaderCollapsed && (
        <header className={`project-header${draftChangeCount > 0 ? " has-draft" : ""}`}>
          <div className="project-header-navigation">
            <button className="project-back" onClick={returnToProjects} aria-label="All projects">
              <ArrowLeft size={16} />
            </button>
            <ProjectDock
              tabs={openProjectTabs}
              activeProjectId={projectId}
              onActivate={activateProjectTab}
              onClose={closeDockedProject}
            />
            {projectReconciliation === "reconciling" && (
              <span
                className="project-reconciliation"
                role="status"
                aria-label="Refreshing project state"
              >
                <LoaderCircle className="spin" size={13} aria-hidden="true" />
              </span>
            )}
          </div>
          <div className="project-header-actions" id="project-header-actions">
            <div
              className="project-header-group project-action-group"
              role="group"
              aria-label="Project actions"
            >
              <div className="header-sync-side">
                {draftChangeCount > 0 && (
                  <button
                    className="icon-button draft-reset"
                    aria-label="Reset staged changes"
                    title="Reset staged changes"
                    disabled={projectReconciliation !== "authoritative" || syncingDraft}
                    onClick={resetHumanDraft}
                  >
                    <RotateCcw size={14} />
                  </button>
                )}
                <button
                  className={`button draft-sync${committableDraftCount > 0 ? " active" : ""}${ontologyDraftIsStale ? " stale" : ""}`}
                  disabled={
                    mutationsDisabled ||
                    committableDraftCount === 0 ||
                    syncingDraft ||
                    draftPreviewPending ||
                    Boolean(draftPreviewConflict) ||
                    ontologyDraftIsStale ||
                    !project.canonical_state.reachable
                  }
                  title={
                    draftPreviewConflict ||
                    (draftPreviewPending
                      ? "Preparing the staged transition preview"
                      : ontologyDraftIsStale
                        ? "Ontology draft base is stale"
                        : undefined)
                  }
                  aria-label={
                    syncingDraft
                      ? "Syncing staged changes"
                      : draftPreviewPending
                        ? "Preparing staged transition preview"
                        : draftPreviewConflict
                          ? "Resolve the staged transition conflict before Sync"
                          : ontologyDraftIsStale
                            ? `Ontology conflict, ${committableDraftCount} committable changes`
                            : behindDraftCount > 0
                              ? `Sync ${committableDraftCount} committable changes, ${behindDraftCount} behind`
                              : undefined
                  }
                  onClick={() => void syncHumanDraft()}
                >
                  {syncingDraft || draftPreviewPending ? (
                    <LoaderCircle className="spin" size={14} />
                  ) : ontologyDraftIsStale || draftPreviewConflict ? (
                    <AlertTriangle size={14} />
                  ) : (
                    <CloudUpload size={14} />
                  )}
                  <span>Sync</span>
                  {committableDraftCount > 0 && <small>{committableDraftCount}</small>}
                </button>
                {behindDraftCount > 0 && (
                  <span className="draft-behind-count" role="status">
                    Behind <small>{behindDraftCount}</small>
                  </span>
                )}
              </div>
              <button
                className="button secondary"
                disabled={projectReconciliation !== "authoritative"}
                onClick={() => {
                  const chatId =
                    unsentConversation(conversations, "project_chat")?.chatId ??
                    startConversation("project_chat", null, project.name);
                  openChats(chatId);
                }}
              >
                <MessageCircle size={14} /> Ask
              </button>
              <button
                className="button secondary auto-research-control"
                disabled={
                  mutationsDisabled ||
                  projectReconciliation !== "authoritative" ||
                  !project.canonical_state.reachable ||
                  taskStarting ||
                  Boolean(liveAutoResearchEpisode)
                }
                aria-label="Auto-research"
                title={
                  liveAutoResearchEpisode ? "An auto-research episode is already live." : undefined
                }
                onClick={() => {
                  openAutoResearchDialog();
                }}
              >
                <Telescope size={14} /> <span className="auto-research-label">Auto-research</span>
              </button>
            </div>
            <div
              className="project-header-group project-utility-group"
              role="group"
              aria-label="Project utilities"
            >
              <button
                className="icon-button task-history-control"
                aria-label={activeTask ? "Project history, task in progress" : "Project history"}
                onClick={openProjectHistory}
              >
                <History size={15} />
                {activeTask ? <span className="activity-pulse" /> : null}
              </button>
              <button
                className="icon-button primary refresh-control"
                disabled={
                  mutationsDisabled ||
                  projectReconciliation !== "authoritative" ||
                  !project.canonical_state.reachable ||
                  taskStarting
                }
                aria-label={runKind === "seed" ? "Seed project" : "Refresh project"}
                onClick={openRunDialog}
              >
                <RefreshCw className={activeTask && !activeTask.pausing ? "spin" : ""} size={15} />
              </button>
            </div>
          </div>
        </header>
      )}

      <nav className="project-tabs" aria-label="Project panels">
        {projectHeaderCollapsed && (
          <button
            className="project-tabs-back project-back"
            onClick={returnToProjects}
            aria-label="All projects"
          >
            <ArrowLeft size={16} />
          </button>
        )}
        {/* Folded, the expand control sits beside the back arrow it came from. */}
        <button
          aria-expanded={!projectHeaderCollapsed}
          aria-controls={!projectHeaderCollapsed ? "project-header-actions" : undefined}
          aria-label={projectHeaderCollapsed ? "Expand project header" : "Collapse project header"}
          className="project-tabs-toggle"
          title={projectHeaderCollapsed ? "Expand project header" : "Collapse project header"}
          onClick={toggleProjectHeader}
        >
          {projectHeaderCollapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
        </button>
        {projectHeaderCollapsed && (
          <ProjectDock
            className="project-tabs-project-dock"
            tabs={openProjectTabs}
            activeProjectId={projectId}
            onActivate={activateProjectTab}
            onClose={closeDockedProject}
          />
        )}
        {navItems.map((item) =>
          item.view === "terminals" ? (
            <TerminalTab
              key={`terminals-${project.id}`}
              projectId={project.id}
              refreshKey={JSON.stringify([project.machines, project.repositories])}
              active={view === "terminals"}
              onClick={() => changeView("terminals")}
              onError={reportErrorNotice}
            />
          ) : (
            <button
              key={item.view}
              className={navItemActive(item.view, view) ? "active" : ""}
              aria-current={navItemActive(item.view, view) ? "page" : undefined}
              onClick={() =>
                item.view === "chats"
                  ? openChats()
                  : item.view === "scientific"
                    ? openLastResearchView()
                    : changeView(item.view)
              }
            >
              {item.icon}
              <span>{item.label}</span>
              {item.view === "attention" && attentionCount > 0 && (
                <small className="inbox-count">{attentionCount}</small>
              )}
              {item.view === "artifacts" && paper.sync_state !== "synced" && <small>1</small>}
              {item.view === "chats" && chatsIndicator && (
                <small
                  className={`chats-indicator ${chatsIndicator}`}
                  aria-label={
                    chatsIndicator === "active" ? "Chat task active" : "Unread chat result"
                  }
                >
                  {chatsIndicator === "active" ? "•" : unreadChatTaskIds.size}
                </small>
              )}
            </button>
          ),
        )}
        {showTrustFilter && (
          <label className="trust-filter">
            <span>Show</span>
            <select
              value={trustView}
              onChange={(event) => changeTrustView(event.target.value as TrustView)}
            >
              <option value="working">Working graph</option>
              <option value="accepted">Accepted only</option>
              <option value="review">Everything</option>
            </select>
          </label>
        )}
      </nav>

      {graphTarget.kind === "branch" && (
        <section className="branch-graph-banner" aria-label="Active graph target">
          <span>
            <GitBranch size={16} />
            <strong>Episode branch</strong>
            <span className="mono">{graphTarget.branch_id.slice(0, 8)}</span>
            <span>Revision {graph.revision}</span>
            {activeBranchEpisode?.graph_branch && (
              <span>{branchMergeStateLabel(activeBranchEpisode.graph_branch.merge_state)}</span>
            )}
          </span>
          <div>
            <button
              type="button"
              className="button compact secondary"
              onClick={() => {
                if (activeBranchEpisode) {
                  window.location.hash = `${graphViewHash(project.id, graphTarget, "execution")}&mode=auto_research&episode=${encodeURIComponent(activeBranchEpisode.episode_id)}`;
                } else changeView("execution");
              }}
            >
              Episode & tasks
            </button>
            <a className="button compact secondary" href={graphViewHash(project.id, MAIN_GRAPH)}>
              Main graph
            </a>
          </div>
        </section>
      )}
      {dockedNodes.length > 0 && (
        <section className="node-window-dock" aria-label="Docked node windows">
          <div className="node-window-dock-label">
            <Network size={14} />
            <span>Docked nodes</span>
          </div>
          <div className="node-window-dock-items">
            {dockedNodes.map(({ nodeId, node }) => (
              <button
                className="node-window-dock-item"
                key={nodeId}
                type="button"
                aria-label={`Restore ${node.title} node window`}
                onClick={() => restoreDockedNode(nodeId)}
              >
                <span className={`node-window-dock-state ${node.standing}`} />
                <span>{node.title}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="project-notices">
        {updateSurface}
        {draftPreviewPending && (
          <div className="coverage-banner" role="status">
            <LoaderCircle className="spin" size={15} aria-hidden="true" />
            <span>
              <strong>Preparing staged transition preview.</strong>
            </span>
          </div>
        )}
        {draftPreviewConflict && (
          <div className="coverage-banner validation-rejected" role="alert">
            <AlertTriangle size={15} aria-hidden="true" />
            <span>
              <strong>Staged transition conflict.</strong> {draftPreviewConflict} Your staged input
              is kept;{" "}
              {draftTransitionProjection
                ? "the graph remains at the last valid staged projection."
                : "the graph remains at canonical state."}
            </span>
          </div>
        )}
        {!draftPreviewPending &&
          !draftPreviewConflict &&
          draftTransitionProjection &&
          draftTransitionProjection.head.revision !== graph.revision && (
            <div className="coverage-banner" role="status">
              <GitBranch size={15} aria-hidden="true" />
              <span>
                <strong>Staged transition preview.</strong> Candidate revision{" "}
                {draftTransitionProjection.head.revision}; canonical state remains revision{" "}
                {graph.revision} until Sync.
              </span>
            </div>
          )}
        {episodeRefreshError && (
          <div className="coverage-banner replay-degraded" role="alert">
            <AlertTriangle size={15} />
            <span>{episodeRefreshError}</span>
          </div>
        )}
        {!project.canonical_state.reachable && (
          <div className="coverage-banner state-offline">
            <AlertTriangle size={15} />
            <span>
              <strong>Canonical state is offline.</strong> Sync is unavailable.
            </span>
          </div>
        )}
        {replayWarning && (
          <div className="coverage-banner replay-degraded" role="alert">
            <AlertTriangle size={15} />
            <span>
              <strong>Replay degraded.</strong> {replayWarning}
            </span>
          </div>
        )}
        {rejectedPatches.length > 0 && view === "attention" && (
          <div className="coverage-banner validation-rejected" role="status">
            <AlertTriangle size={15} />
            <span>
              <strong>
                History note: {rejectedPatches.length} operation
                {rejectedPatches.length === 1 ? "" : "s"} rejected and not applied.
              </strong>{" "}
              RCP kept the attempted patch for audit, so the graph was unchanged. This is not an
              Inbox decision. Reason: {rejectedPatches.at(-1)?.message}
            </span>
            <button
              type="button"
              className="icon-button compact"
              aria-label="Dismiss history note"
              onClick={() => dismissHistoryNotices(rejectedPatches)}
            >
              <X size={14} />
            </button>
          </div>
        )}
      </div>

      <main
        className={view === "paper" ? "project-panel paper" : "project-panel"}
        ref={panelRef}
        inert={projectReconciliation !== "authoritative"}
        aria-busy={projectReconciliation !== "authoritative"}
      >
        <Suspense
          fallback={
            <div className="project-view-loading" aria-label="Loading view">
              <LoaderCircle className="spin" />
            </div>
          }
        >
          {(view === "scientific" || view === "dag") && (
            <div className="research-subpanel" role="tablist" aria-label="Research panels">
              <button
                type="button"
                role="tab"
                aria-selected={view === "scientific"}
                className={view === "scientific" ? "active" : ""}
                onClick={() => changeView("scientific")}
              >
                <GitBranch size={13} /> Research
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "dag"}
                className={view === "dag" ? "active" : ""}
                onClick={() => changeView("dag")}
              >
                <Network size={13} /> DAG
              </button>
            </div>
          )}
          {view === "overview" && (
            <ProjectOverview
              project={projectWithTransitionProjection(
                project,
                presentedGraph,
                presentedExperimentControl,
                presentedAttention,
                presentedTransitionProjection?.primary_question ?? project.primary_question ?? null,
                presentedTransitionProjection?.counts ?? project.counts,
              )}
              graph={presentedGraph}
              pendingProposals={pendingProposals}
              decisionsAwaitingChoice={attentionDecisions}
              latestRevisionSummary={
                latestRevisionSummary?.to_revision === graph.revision ? latestRevisionSummary : null
              }
              onNavigate={changeView}
            />
          )}
          {view === "attention" && (
            <div className="attention-page">
              <div className="attention-main">
                <AttentionOverview
                  proposals={pendingProposals}
                  decisions={attentionDecisions}
                  blockers={openBlockers}
                  onSelectNode={openNode}
                />
                <ProposalJudgmentSection
                  proposals={pendingProposals}
                  graph={attentionGraph}
                  proposalActions={presentedAttention.proposal_actions}
                  glossaryIndex={glossaryIndex}
                  draft={mutationsDisabled ? null : humanDraft}
                  mutationsDisabled={mutationsDisabled}
                  onDecision={(proposal, decision) =>
                    updateHumanDraft((draft) =>
                      stageProposalDecision(draft, graph, proposal.id, decision),
                    )
                  }
                />
              </div>
              <AttentionRail
                decisions={attentionDecisions}
                blockers={openBlockers}
                onSelectNode={openNodeById}
              />
            </div>
          )}
          {view === "scientific" && (
            <ScientificView
              {...graphEditingProps}
              graph={presentedGraph}
              trustView={trustView}
              onSelectNode={openNode}
            />
          )}
          {view === "dag" && (
            <DagView
              key={graphSessionKey(project.id, graphTarget)}
              graphTarget={graphTarget}
              branchChanges={project.graph_changes}
              onInspectTask={selectTaskInspector}
              {...graphEditingProps}
              graph={presentedGraph}
              trustView={trustView}
              viewportRef={activeDagViewportRef!}
              relationFocusNodeId={dagRelationFocusId}
              onClearRelationFocus={clearDagRelationFocus}
              onSelectNode={openNode}
            />
          )}
          {view === "artifacts" && (
            <div className="artifacts-shell">
              <ArtifactsSubnav
                view={view}
                paperUnsynced={paper.sync_state !== "synced"}
                onChange={changeView}
              />
              <Artifacts key={project.id} projectId={project.id} />
            </div>
          )}
          {view === "terminals" && <Terminals key={project.id} projectId={project.id} />}
          {view === "execution" && (
            <div className="combined-runs-view">
              <ExecutionView
                providerLogins={runsProviderLogins}
                onProviderLoginVerified={() => void refreshProviderLogins()}
                machines={project.machines}
                computeApiBase={apiBase}
                onOpenSettings={() => changeView("settings")}
                graph={presentedGraph}
                episodes={episodes}
                episodeAction={episodeAction}
                tasks={projectTasks}
                watchers={watchers}
                experimentControl={presentedExperimentControl}
                experimentEntries={experimentLoops.filter(
                  (entry) => entry.project_id === project.id,
                )}
                exactExperimentRoute={selectedExperimentRoute}
                exactExperimentEntry={selectedBranchExperiment}
                selectedExperimentId={selectedExperimentRunId}
                focusExperimentId={focusExperimentRunId}
                selectedAutoResearchEpisodeId={selectedAutoResearchEpisodeId}
                runBusy={taskStarting}
                stopBusyId={experimentStopId}
                watcherCheckBusyId={watcherCheckId}
                taskActionId={taskActionId}
                selectedExperimentConversation={selectedExperimentConversation}
                providerLabels={Object.fromEntries(
                  Object.entries(project.providers).map(([id, provider]) => [
                    id,
                    provider.label || id,
                  ]),
                )}
                mutationsDisabled={mutationsDisabled}
                experimentStartsDisabled={experimentStartRequiresSync}
                onInspectTask={selectTaskInspector}
                onStopEpisode={requestEpisodeStop}
                onArchiveEpisode={requestEpisodeArchive}
                onMergeEpisode={requestEpisodeMerge}
                onContinueEpisode={requestEpisodeContinuation}
                onSendEpisodeMessage={messageEpisodeOrchestrator}
                onOperateEpisodeTask={operateEpisodeOrchestratorTask}
                onSwitchEpisodeProvider={chooseRetryTask}
                onSelectExperiment={selectExperiment}
                onOpenExperimentEntry={(entry) =>
                  commitProjectOpen(project.id, experimentBoardRouteToken(entry))
                }
                onDetailFocused={clearExperimentFocus}
                onOpenHistory={openProjectHistory}
                onRunExperiment={(node, invocationCeiling) =>
                  void runExperiment(node, invocationCeiling)
                }
                onStopExperiment={(nodeId, episodeId) =>
                  void stopExperimentLoop(nodeId, episodeId ?? null)
                }
                onCheckExperimentWatcher={(watcherId) => void checkExperimentWatcher(watcherId)}
                onStopExperimentWatcher={(watcherId) => void stopWatcher(watcherId)}
                onRecoverExperiment={(task, action) => void operateTask(task, action, false)}
                onSwitchExperimentProvider={chooseRetryTask}
                episodeReportHref={(episodeId) => episodeReportPreviewUrl(project.id, episodeId)}
              />
            </div>
          )}
          {view === "paper" && (
            <div className="artifacts-shell">
              <ArtifactsSubnav
                view={view}
                paperUnsynced={paper.sync_state !== "synced"}
                onChange={changeView}
              />
              <PaperWorkspace
                key={project.id}
                apiBase={apiBase}
                project={project}
                initialPaper={paper}
                tasks={projectTasks}
                onStartTask={startAgentTask}
                onPaperChange={updatePaper}
              />
            </div>
          )}
          {view === "settings" && (
            <ProjectSettings
              updateNotice={releaseUpdate}
              apiBase={apiBase}
              project={project}
              identity={actorIdentity}
              onLeftProject={() => {
                closeProjectRoute(project.id);
                removeProject(project.id);
                forgetProjectViewport(project.id);
                setNotice({ kind: "info", text: "You left this project." });
              }}
              usage={usage}
              onRefreshUsage={refreshUsage}
              cacheClearDisabled={Boolean(activeTask)}
              writesDisabled={mutationsDisabled}
              showTextScale={desktop}
              spaceKind={verifiedHealth?.space_kind ?? "personal"}
              textScale={textScale}
              onTextScaleChange={changeAppTextScale}
              onRefreshReadiness={refreshReadiness}
              readinessRequest={providerReadinessRequests[project.id]}
              onMovePersonalProjectToTeam={movePersonalProjectToTeam}
              onCacheMetricsChange={(cacheMetrics) => {
                updateProject((current) =>
                  current ? { ...current, cache_metrics: cacheMetrics } : current,
                );
              }}
              onSaved={(saved, retention = RETAIN_ALL_PROJECT_READINESS) => {
                invalidateProjectReadinessGenerations(
                  projectReadinessGenerations.current,
                  saved.id,
                  retention,
                );
                beginProjectSnapshotRequest(saved.id);
                if (graphTarget.kind === "main")
                  updateProject((current) =>
                    projectSettingsSavedProject(saved, current, retention),
                  );
                else void reload();
                // The saved snapshot carries the new default; the session may still
                // hold the pre-save branch snapshot while its reload is in flight.
                replaceRunScope(saved.default_run_truth_scope);
                setNotice({ kind: "info", text: "Project defaults synced." });
              }}
            />
          )}
          {view === "chats" && (
            <ChatsWorkspace
              project={project}
              conversations={conversations}
              selectedChatId={selectedChatId}
              nodes={presentedGraph.nodes}
              glossaryIndex={glossaryIndex}
              runScope={runScope}
              tasks={tasks}
              watchers={watchers}
              graphChangesDisabled={mutationsDisabled}
              unreadTaskIds={unreadChatTaskIds}
              chatTranscripts={chatTranscripts}
              hasMore={chatSummaryNextOffset < chatSummaryTotal}
              loadingMore={chatSummariesLoading}
              onSelect={selectListedConversation}
              onOpenNode={openNodeById}
              onLoadMore={() => void loadMoreChatSummaries()}
              onStartTask={startAgentTask}
              onResumeTask={(task) => void operateTask(task, "resume")}
              onRetryTask={requestRetry}
              onRefreshTask={refreshAgentTask}
              onInspectTask={selectTaskInspector}
              onOpenInbox={() => changeView("attention")}
              onRepairGraphUpdate={repairGraphUpdate}
              onStopWatcher={(watcherId) => void stopWatcher(watcherId)}
              onRemoveDraft={discardDraft}
              onContinueImported={(result) => {
                recordStartedTask(result.task);
                selectListedConversation(result.chat_id);
                setNotice(null);
              }}
              onNewSession={(conversation) => {
                const node = conversation.nodeId
                  ? (presentedGraph.nodes[conversation.nodeId] ?? null)
                  : null;
                selectChat(
                  unsentConversation(conversations, conversation.kind, conversation.nodeId)
                    ?.chatId ?? startConversation(conversation.kind, node, project.name),
                );
              }}
            />
          )}
        </Suspense>
      </main>

      {(
        [
          { slot: "original" as const, selected: selectedNode },
          { slot: "companion" as const, selected: companionNode },
        ] satisfies Array<{ slot: DetailWindowSlot; selected: GraphNode | null }>
      ).map(({ slot, selected }) => {
        if (!selected) return null;
        const node = presentedGraph.nodes[selected.id] ?? selected;
        const historical =
          !presentedGraph.nodes[node.id] &&
          project.graph_changes?.nodes.some(
            (change) => change.node_id === node.id && change.change === "removed",
          ) === true;
        const experimentControl = historical ? null : experimentControlForNode(node);
        return (
          <DetailDrawer
            key={`${slot}:${node.id}`}
            node={node}
            historical={historical}
            branchChange={project.graph_changes?.nodes.find((change) => change.node_id === node.id)}
            onInspectTask={selectTaskInspector}
            edges={Object.values(presentedGraph.edges)}
            allNodes={presentedGraph.nodes}
            glossaryIndex={glossaryIndex}
            beliefTransitions={graph.belief_transitions}
            validationMessages={graph.validation_messages}
            ontology={presentedGraph.ontology}
            priorChoiceOffBallot={presentedAttention.decision_prior_choices[node.id] ?? null}
            sizeStorageKey={nodeDetailSizeStorageKey(graphSessionKey(project.id, graphTarget))}
            detailSlot={slot}
            focusRequestToken={detailFocusTokens[slot]}
            mutationsDisabled={mutationsDisabled}
            stagedNewNode={Boolean(humanDraft?.custom_nodes[node.id])}
            stagedForRemoval={Boolean(humanDraft?.removed_node_ids.includes(node.id))}
            hasStagedNodeChange={Boolean(humanDraft?.nodes[node.id])}
            draftNodeChange={humanDraft?.nodes[node.id]}
            canonicalNode={graph.nodes[node.id]}
            behind={draftNodeIsBehind(humanDraft?.nodes[node.id], graph.nodes[node.id])}
            canonicalStanding={graph.nodes[node.id]?.standing ?? node.standing}
            experimentControl={experimentControl}
            experimentRunDisabled={experimentStartRequiresSync}
            experimentRunBusy={taskStarting}
            decisionChoiceStaged={Boolean(
              humanDraft?.nodes[node.id]?.changes.selected_option !== undefined ||
              humanDraft?.nodes[node.id]?.changes.status === "decided",
            )}
            onUnstage={() => {
              updateHumanDraft((draft) => unstageCustomNode(draft, graph, node.id));
              closeDetailSlot(slot);
            }}
            onRemove={() =>
              updateHumanDraft((draft) =>
                stageNodeRemoval(draft, graph, node.id, Boolean(experimentControl?.active)),
              )
            }
            onUndoRemoval={() => updateHumanDraft((draft) => unstageNodeRemoval(draft, node.id))}
            onClose={() => closeDetailSlot(slot)}
            onDock={() => dockNode(node.id, slot)}
            onBeginEdit={() =>
              updateHumanDraft((draft) => stageNodeEditStart(draft, graph, node.id))
            }
            onStanding={(standing) =>
              updateHumanDraft((draft) => stageNodeStanding(draft, graph, node.id, standing))
            }
            onStage={(changes) =>
              updateHumanDraft((draft) => stageNodeEdit(draft, graph, node.id, changes))
            }
            onApplyField={(changes, fieldKey) =>
              updateHumanDraft((draft) => stageNodeEdit(draft, graph, node.id, changes, [fieldKey]))
            }
            onDecisionChoice={(selectedOption) =>
              updateHumanDraft((draft) =>
                stageDecisionChoice(draft, graph, node.id, selectedOption),
              )
            }
            onRunExperiment={() => void runExperiment(node)}
            onOpenChat={() => {
              const chatId = ensureConversation(conversations, "node_chat", node, project.name);
              selectChat(chatId);
              setFloatingChat({ chatId, nodeId: node.id });
            }}
            onOpenRelatedNode={(nodeId) => openRelatedNode(slot, nodeId)}
            onSelectNode={openNodeById}
          />
        );
      })}
      {floatingChat && floatingChat.chatId !== selectedExperimentChatId && (
        <DraggableWindow className="node-chat-window" kind="chat" resizable>
          <Suspense
            fallback={
              <div className="project-view-loading" aria-label="Loading chat">
                <LoaderCircle className="spin" />
              </div>
            }
          >
            <NodeChat
              key={floatingChat.chatId}
              project={project}
              node={presentedGraph.nodes[floatingChat.nodeId] ?? null}
              nodes={presentedGraph.nodes}
              glossaryIndex={glossaryIndex}
              conversationTitle={
                conversations.find((conversation) => conversation.chatId === floatingChat.chatId)
                  ?.title
              }
              runScope={runScope}
              tasks={tasks}
              watchers={watchers}
              historyMessages={chatTranscripts.get(floatingChat.chatId)?.messages}
              chatId={floatingChat.chatId}
              presentation="floating"
              graphChangesDisabled={mutationsDisabled}
              onStartTask={startAgentTask}
              onResumeTask={(task) => void operateTask(task, "resume")}
              onRetryTask={requestRetry}
              onRefreshTask={refreshAgentTask}
              onInspectTask={selectTaskInspector}
              onOpenInbox={() => {
                setFloatingChat(null);
                changeView("attention");
              }}
              onRepairGraphUpdate={repairGraphUpdate}
              onOpenNode={openNodeById}
              onStopWatcher={(watcherId) => void stopWatcher(watcherId)}
              onNewSession={() => {
                const node = presentedGraph.nodes[floatingChat.nodeId] ?? null;
                const chatId =
                  unsentConversation(conversations, "node_chat", floatingChat.nodeId)?.chatId ??
                  startConversation("node_chat", node, project.name);
                selectChat(chatId);
                setFloatingChat({ chatId, nodeId: floatingChat.nodeId });
              }}
              onClose={() => setFloatingChat(null)}
            />
          </Suspense>
        </DraggableWindow>
      )}
      <RunDialog
        open={runDialogOpen}
        kind={runKind}
        project={project}
        initialScope={runScope}
        busy={taskStarting}
        onClose={closeRunDialog}
        onRun={(config, scope, message) => void runAgent(config, scope, message)}
      />
      <AutoResearchDialog
        open={autoResearchDialogOpen}
        busy={episodeAction === "start"}
        error={autoResearchStartError}
        initialInvocationCeiling={project.default_auto_research_invocation_ceiling}
        onClose={closeAutoResearchDialog}
        onAuthorize={(invocationCeiling, startingInstruction) =>
          void authorizeAutoResearch(invocationCeiling, startingInstruction)
        }
      />
      {retryTask && retryConfig && (
        <RunDialog
          open
          mode="retry"
          kind={retryProfileKind(retryTask)}
          project={project}
          initialScope={retryTask.request.run_truth_scope || project.default_run_truth_scope}
          initialConfig={retryConfig}
          runOnLocked={retryTask.episode_id !== null}
          busy={taskActionId === retryTask.operation_id}
          onClose={closeRetryTask}
          onRun={(config) => void retryAgentTask(retryTask, config)}
        />
      )}
      {projectHistoryOpen && (
        <ProjectHistoryDrawer
          projectId={project.id}
          summaries={historyRevisionSummaries}
          tasks={projectTasks}
          loading={historySummariesRevision !== graph.revision}
          error={historySummariesError}
          onInspectTask={(taskId) => {
            closeProjectHistory();
            selectTaskInspector(taskId);
          }}
          episodeReportHref={(episodeId) => episodeReportPreviewUrl(project.id, episodeId)}
          onClose={closeProjectHistory}
        />
      )}
      {taskInspectorId && (
        <AgentTaskInspector
          tasks={projectTasks}
          task={inspectedTask}
          loading={taskInspectorLoading}
          actionBusy={Boolean(
            taskActionId || (activeTask && activeTask.operation_id !== taskInspectorId),
          )}
          mutatingActionsDisabled={Boolean(
            mutationsDisabled && inspectedTask && taskMayMutateGraph(inspectedTask),
          )}
          onSelect={selectTaskInspector}
          onPause={() => inspectedTask && void operateTask(inspectedTask, "pause")}
          onResume={() => inspectedTask && void operateTask(inspectedTask, "resume")}
          onRetry={() => inspectedTask && requestRetry(inspectedTask)}
          onClose={() => selectTaskInspector(null)}
        />
      )}
      {notice && (
        <button className={`toast ${notice.kind}`} onClick={() => setNotice(null)}>
          {notice.text}
        </button>
      )}
      {webMcpArtifactViewerUrl && (
        <section className="webmcp-artifact-overlay" aria-label="RCP artifact viewer">
          <header>
            <strong>Artifact viewer</strong>
            <button
              className="icon-button"
              type="button"
              aria-label="Close artifact viewer"
              onClick={() => setWebMcpArtifactViewerUrl(null)}
            >
              <X size={16} />
            </button>
          </header>
          <iframe title="RCP artifact viewer" src={webMcpArtifactViewerUrl} />
        </section>
      )}
      {desktopAccessSurface}
      {actorNameSurface}
    </div>
  );
}

function readTextScale(): number {
  try {
    return normalizeTextScale(localStorage.getItem(TEXT_SCALE_STORAGE_KEY));
  } catch {
    return normalizeTextScale(null);
  }
}

export function projectWithGraph(
  project: ProjectSnapshot,
  graph: GraphState,
  attention: GraphAttentionProjection = projectAttentionForPresentation(project, null),
  primaryQuestion: GraphNode | null = project.primary_question ?? null,
  counts = project.counts,
): ProjectSnapshot {
  return {
    ...project,
    graph,
    revision: graph.revision,
    primary_question: primaryQuestion,
    attention,
    counts,
  };
}

function projectWithTransitionProjection(
  project: ProjectSnapshot,
  graph: GraphState,
  experimentControl: Record<string, ExperimentControlState>,
  attention: GraphAttentionProjection,
  primaryQuestion: GraphNode | null,
  counts: ProjectSnapshot["counts"],
): ProjectSnapshot {
  return {
    ...projectWithGraph(project, graph, attention, primaryQuestion, counts),
    experiment_control: experimentControl,
  };
}

function localDraftTransitionProjection(
  graph: GraphState,
  experimentControl: Record<string, ExperimentControlState>,
  attention: GraphAttentionProjection,
  primaryQuestion: GraphNode | null,
  counts: ProjectSnapshot["counts"],
  head: GraphHeadRef,
  rulesetTag: string | null,
): BrowserTransitionProjection {
  return {
    head,
    graph,
    attention,
    primary_question: primaryQuestion,
    counts,
    experiment_control: experimentControl,
    ruleset_tag: rulesetTag,
    transition_id: head.transition_id,
    canonical: false,
    base_head: head,
  };
}

function emptyProjectCounts(): ProjectSnapshot["counts"] {
  return {
    pending_proposals: 0,
    decisions_awaiting_choice: 0,
    open_blockers: 0,
    asserted: 0,
    accepted: 0,
    contested: 0,
  };
}

function previewTraceMismatch(
  response: TransitionPreviewResponse,
  projection: ProjectTransitionResponse,
): string | null {
  if (projection.canonical) return "Staged transition preview was marked canonical.";
  if (!projection.base_head) return "Staged transition preview omitted its canonical base head.";
  if (!transitionHeadsEqual(projection.base_head, response.transition.pre_head)) {
    return "Staged transition preview base head did not match its transition trace.";
  }
  if (projection.transition_id !== response.transition.transition_id) {
    return "Staged transition preview id did not match its transition trace.";
  }
  if (projection.ruleset_tag !== response.transition.ruleset_tag) {
    return "Staged transition preview ruleset did not match its transition trace.";
  }
  return null;
}

function taskRetryConfig(task: AgentTask, project: ProjectSnapshot): AgentRunConfig {
  const profile = project.agent_profiles[retryProfileKind(task)];
  return {
    provider: task.request.provider || profile.provider,
    model: task.request.model ?? profile.model,
    reasoning: task.request.reasoning || profile.reasoning,
    run_on: task.request.run_on || profile.run_on,
  };
}

/** The profile whose defaults fill a retry the task's own request left unset. */
export function retryProfileKind(task: AgentTask): AgentExecutionProfile {
  if (task.kind === "seed" || task.kind === "refresh") return task.kind;
  if (task.kind === "auto_research") return "orchestrator";
  if (isExperimentLoopRecovery(task)) return "node_chat";
  return task.kind === "project_chat" || task.kind === "paper_coach" ? task.kind : "node_chat";
}

function isExperimentLoopRecovery(task: AgentTask): boolean {
  return task.request.patch_kind === "experiment_loop";
}

/**
 * A turn bound to an episode keeps the machine its watchers and stage live on;
 * a standalone turn may move to a reachable one. Everything else is rebindable
 * on every recovery.
 */
export function taskRetryRequestBody(
  task: AgentTask,
  config: AgentRunConfig,
): AgentRunConfig | Omit<AgentRunConfig, "run_on"> {
  const rebound = {
    provider: config.provider,
    model: config.model,
    reasoning: config.reasoning,
  };
  return task.episode_id ? rebound : { ...rebound, run_on: config.run_on };
}

function isSetupRoute(): boolean {
  return isSetupHash(window.location.hash);
}

function isSetupHash(hash: string): boolean {
  return parseProjectSetupRoute(hash).kind !== "none";
}

function projectSetupRouteKey(route: ProjectSetupRoute): string {
  if (route.kind === "move") {
    return [
      route.kind,
      route.sourceProjectId,
      route.sourceRequestId ?? "",
      route.targetRequestId ?? "",
    ].join(":");
  }
  if (route.kind === "create") return `${route.kind}:${route.requestId ?? ""}`;
  return route.kind;
}
