import { useHiddenWatchers } from "../hooks/useHiddenWatchers";
import { hideResolvedCodexHandoffErrors } from "../providerHistoryPresentation";
import { ExternalJobRow } from "./ExternalJobRow";
import {
  AlertTriangle,
  ChevronUp,
  Cpu,
  Download,
  ExternalLink,
  File,
  History,
  Inbox,
  LoaderCircle,
  MessageCircle,
  MessageCirclePlus,
  Mic,
  MicOff,
  Play,
  Plus,
  RadioTower,
  RotateCcw,
  Send,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  decideArtifactRevision,
  removeChatAttachment,
  steerChatTurn,
  uploadChatAttachment,
} from "../api";
import {
  artifactRevisionContentUrl,
  artifactUrl,
  chatTasksMissingFromHistory,
  isActiveTask,
  latestNativeSessionId,
  orderTranscriptLines,
  reconcileChatHistoryArtifacts,
  reconstructTaskTranscript,
  relatedChatTasks,
  resumablePausedChatTask,
  taskKindLabel,
  versionedArtifactContentUrl,
} from "../agentTasks";
import {
  chatDraftStorageKey,
  chatModeStorageKey,
  isConversationModeShortcut,
  latestPersistedChatConfig,
  latestPersistedConversationMode,
  parseConversationMode,
  startConversationTurn,
  toggleConversationMode,
} from "../chatWorkspace";
import { MarkdownAnswer } from "../chatMarkdown";
import {
  assembleChatTurn,
  chatAnnotationComposerPosition,
  chatAnnotationTextControlSelection,
  chatAnnotationViewportMetrics,
  MAX_CHAT_ANNOTATIONS,
  MAX_CHAT_ANNOTATION_COMMENT_LENGTH,
  MAX_CHAT_ANNOTATION_TEXT_LENGTH,
  annotatableAnswerSelectionRange,
  parseStagedChatAnnotations,
  replaceTextSpan,
  stagedChatAnnotationsAreComplete,
  type ChatAnnotationAnchor,
  type ChatAnnotationComposerPosition,
  type ChatAnnotationViewportMetrics,
  type StagedChatAnnotation,
} from "../chatInput";
import {
  computeProbePresentation,
  latestPersistedComputeIds,
  reconcileActiveComputeIds,
} from "../compute";
import type { GlossaryIndex } from "../glossary";
import {
  graphConditionLabel,
  isExternalWatcherRecord,
  visibleChatWatchers,
  watcherLastObservedAt,
} from "../runProjection";
import {
  downloadDesktopArtifact,
  type DictationResultEvent,
  type DictationStateEvent,
  isDesktopRuntime,
  listenDesktopEvent,
  openDesktopArtifactPreview,
  openDesktopRepositoryFilePreview,
  startDesktopDictation,
  stopDesktopDictation,
} from "../desktopRuntime";
import {
  repositoryFilePreviewUrl,
  resolveRepositoryFileHref,
  turnArtifactName,
} from "../repositoryFileLinks";
import type {
  AgentArtifactDescriptor,
  ArtifactContextRequest,
  ArtifactSelection,
  AgentTask,
  ChatMessage,
  ChatAttachmentDescriptor,
  ConversationMode,
  GraphNode,
  GraphUpdateResult,
  ProjectSnapshot,
  StartAgentTask,
  WatcherRecord,
  WorktreeIntegrationOption,
} from "../types";
import {
  CHAT_SCROLL_BOTTOM_TOLERANCE_PX,
  CHAT_USER_MESSAGE_COLLAPSE_THRESHOLD,
} from "../uiConstants";
import { profileRunConfig } from "./AgentConfigControls";
import {
  handleAutoResearchDialogKeyDown,
  makeAutoResearchDialogBackgroundInert,
  restoreAutoResearchDialogFocus,
} from "./AutoResearchDialog";
import { SkillPicker, useSkillPicker } from "./SkillPicker";
import { RepositoryScope } from "./RepositoryScope";
import { WorktreeControls, useConversationWorktree } from "./WorktreeControls";
import { ImportedCodexContext } from "./ImportedCodexContext";

interface Props {
  project: ProjectSnapshot;
  node?: GraphNode | null;
  nodes?: Readonly<Record<string, GraphNode>>;
  glossaryIndex?: GlossaryIndex;
  conversationTitle?: string;
  /** Workspace title and status; shares one row with the chat controls. */
  header?: ReactNode;
  headerState?: string;
  runScope: string[];
  tasks: AgentTask[];
  watchers?: WatcherRecord[];
  historyMessages?: ChatMessage[];
  importedSessionId?: string;
  chatId: string;
  presentation?: "floating" | "workspace";
  fixedConversation?: boolean;
  readOnly?: boolean;
  reviewPending?: boolean;
  graphChangesDisabled?: boolean;
  onStartTask: StartAgentTask;
  onInspectTask: (taskId: string) => void;
  onOpenInbox: () => void;
  onRepairGraphUpdate: (taskId: string) => Promise<void>;
  onOpenNode?: (nodeId: string) => void;
  onStopWatcher?: (watcherId: string) => void;
  onNewSession: () => void;
  onClose: () => void;
  onResumeTask: (task: AgentTask) => void;
  onRetryTask: (task: AgentTask) => void;
  onRefreshTask: (taskId: string) => Promise<AgentTask>;
}

interface PendingChatTurn {
  clientId: string;
  text: string;
  timestamp: string;
  mode: ConversationMode;
  attachments: ChatAttachmentDescriptor[];
}

type AttachmentStatus = "preparing" | "ready" | "error";

interface ComposerAttachment {
  localId: string;
  file: File;
  status: AttachmentStatus;
  descriptor?: ChatAttachmentDescriptor;
  error?: string;
}

interface DictationSpan {
  sessionId: string;
  start: number;
  end: number;
}

interface ArtifactRevisionReview {
  taskId: string;
  artifactId: string;
}

interface SelectedChatAnnotationComposer {
  step: "comment";
  selectedText: string;
  anchor: ChatAnnotationAnchor;
  position: ChatAnnotationComposerPosition | null;
}

interface KeyboardChatAnnotationComposer {
  step: "select";
  answerText: string;
  selectedText: string;
  anchor: ChatAnnotationAnchor;
  position: ChatAnnotationComposerPosition | null;
}

type ChatAnnotationComposer = SelectedChatAnnotationComposer | KeyboardChatAnnotationComposer;

const EMPTY_WATCHERS: WatcherRecord[] = [];

const ARTIFACT_ID_PATTERN = /^[0-9a-f]{24}$/;
const INLINE_ARTIFACT_MAX_BYTES = 2 * 1024 * 1024;

interface ArtifactContextPayload {
  type: "rcp-artifact-context";
  version: 1;
  project_id: string;
  chat_id: string;
  operation_id: string;
  source?: "task" | "episode_report";
  episode_id?: string | null;
  artifact_id: string;
  artifact_name: string;
  media_type: string;
  selections: ArtifactSelection[];
}

function artifactContextStorageKey(projectId: string, chatId: string): string {
  return `rcp:artifact-context:${encodeURIComponent(projectId)}:${encodeURIComponent(chatId)}`;
}

export function reconcileChatRunScope(
  current: string[],
  requested: string[],
  projectTruthScope: string[],
  reset: boolean,
): string[] {
  const allowed = new Set(projectTruthScope);
  const candidate = reset ? requested : current;
  return candidate.filter(
    (repository, index) => allowed.has(repository) && candidate.indexOf(repository) === index,
  );
}

export function parseArtifactContextPayload(value: unknown): ArtifactContextPayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  const allowedKeys = new Set([
    "type",
    "version",
    "project_id",
    "chat_id",
    "operation_id",
    "source",
    "episode_id",
    "artifact_id",
    "artifact_name",
    "media_type",
    "selections",
  ]);
  if (
    Object.keys(candidate).some((key) => !allowedKeys.has(key)) ||
    candidate.type !== "rcp-artifact-context" ||
    candidate.version !== 1 ||
    !isBoundedArtifactText(candidate.project_id, 1, 512) ||
    !isBoundedArtifactText(candidate.chat_id, 1, 512) ||
    !isBoundedArtifactText(candidate.operation_id, 1, 512) ||
    (candidate.source !== undefined &&
      candidate.source !== "task" &&
      candidate.source !== "episode_report") ||
    (candidate.source === "episode_report" && typeof candidate.episode_id !== "string") ||
    (candidate.source !== "episode_report" &&
      candidate.episode_id !== undefined &&
      candidate.episode_id !== null) ||
    typeof candidate.artifact_id !== "string" ||
    !ARTIFACT_ID_PATTERN.test(candidate.artifact_id) ||
    !isBoundedArtifactText(candidate.artifact_name, 1, 255) ||
    !isBoundedArtifactText(candidate.media_type, 1, 64) ||
    !Array.isArray(candidate.selections) ||
    candidate.selections.length < 1 ||
    candidate.selections.length > 12
  )
    return null;
  const selections: ArtifactSelection[] = [];
  for (const raw of candidate.selections) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    const selection = raw as Record<string, unknown>;
    if (
      selection.kind === "text" &&
      isBoundedArtifactText(selection.text, 1, 4096) &&
      isBoundedArtifactText(selection.surrounding_text, 0, 6144) &&
      isBoundedArtifactText(selection.comment, 0, 2048)
    ) {
      selections.push({
        kind: "text",
        text: selection.text,
        surrounding_text: selection.surrounding_text,
        comment: selection.comment,
      });
      continue;
    }
    if (
      selection.kind === "box" &&
      isArtifactSelectionRect(selection.rect) &&
      isArtifactViewport(selection.viewport) &&
      isBoundedArtifactText(selection.labels, 0, 4096) &&
      isBoundedArtifactText(selection.comment, 0, 2048)
    ) {
      selections.push({
        kind: "box",
        rect: selection.rect,
        viewport: selection.viewport,
        labels: selection.labels,
        comment: selection.comment,
      });
      continue;
    }
    return null;
  }
  return { ...(candidate as unknown as ArtifactContextPayload), selections };
}

function isBoundedArtifactText(value: unknown, minimum: number, maximum: number): value is string {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum;
}

function isArtifactSelectionRect(
  value: unknown,
): value is { x: number; y: number; width: number; height: number } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const rect = value as Record<string, unknown>;
  if (
    Object.keys(rect).some((key) => !["x", "y", "width", "height"].includes(key)) ||
    ![rect.x, rect.y, rect.width, rect.height].every(
      (part) => typeof part === "number" && Number.isFinite(part),
    )
  )
    return false;
  const x = rect.x as number;
  const y = rect.y as number;
  const width = rect.width as number;
  const height = rect.height as number;
  return x >= 0 && y >= 0 && width > 0 && height > 0 && x + width <= 1 && y + height <= 1;
}

function isArtifactViewport(value: unknown): value is { width: number; height: number } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const viewport = value as Record<string, unknown>;
  return (
    Object.keys(viewport).every((key) => key === "width" || key === "height") &&
    [viewport.width, viewport.height].every(
      (part) => typeof part === "number" && Number.isInteger(part) && part >= 1 && part <= 32768,
    )
  );
}

export function artifactContextDraft(payload: ArtifactContextPayload): string {
  return payload.selections
    .map((selection, index) => {
      const selected =
        selection.kind === "text"
          ? `Selected text: ${selection.text}`
          : `Boxed region: ${selection.labels || `${Math.round(selection.rect.x * 100)}%, ${Math.round(selection.rect.y * 100)}%`}`;
      const comment = selection.comment.trim() ? `\n${selection.comment.trim()}` : "";
      return `${selected}${comment}\n:rcp-artifact-selection{index="${index + 1}"}`;
    })
    .join("\n\n");
}

interface ArtifactDraftSpan {
  signature: string;
  message: string;
  start: number;
  end: number;
}

function readArtifactDraftSpan(raw: string | null): ArtifactDraftSpan | null {
  try {
    const span = JSON.parse(raw ?? "null");
    return span &&
      typeof span.signature === "string" &&
      typeof span.message === "string" &&
      Number.isInteger(span.start) &&
      Number.isInteger(span.end) &&
      span.start >= 0 &&
      span.end >= span.start &&
      span.end <= span.message.length
      ? span
      : null;
  } catch {
    return null;
  }
}

export function moveArtifactDraftSpan(span: ArtifactDraftSpan, message: string): ArtifactDraftSpan {
  const block = span.message.slice(span.start, span.end);
  const retained = block ? message.indexOf(block) : -1;
  if (retained >= 0) return { ...span, message, start: retained, end: retained + block.length };
  let prefix = 0;
  while (
    prefix < span.message.length &&
    prefix < message.length &&
    span.message[prefix] === message[prefix]
  )
    prefix++;
  let suffix = 0;
  while (
    suffix < span.message.length - prefix &&
    suffix < message.length - prefix &&
    span.message[span.message.length - suffix - 1] === message[message.length - suffix - 1]
  )
    suffix++;
  const oldEnd = span.message.length - suffix;
  const delta = message.length - span.message.length;
  return {
    ...span,
    message,
    start: span.start <= prefix ? span.start : span.start >= oldEnd ? span.start + delta : prefix,
    end:
      span.end < prefix
        ? span.end
        : span.end >= oldEnd
          ? span.end + delta
          : message.length - suffix,
  };
}

export function updateArtifactContextDraft(
  message: string,
  payload: ArtifactContextPayload,
  previousDraft: string | null,
): ArtifactDraftSpan {
  const addition = artifactContextDraft(payload);
  const previous = readArtifactDraftSpan(previousDraft);
  const span = previous ? moveArtifactDraftSpan(previous, message) : null;
  const prefix = span
    ? message.slice(0, span.start)
    : message.trimEnd()
      ? `${message.trimEnd()}\n\n`
      : "";
  const suffix = span ? message.slice(span.end) : "";
  return {
    signature: JSON.stringify(payload),
    message: prefix + addition + suffix,
    start: prefix.length,
    end: prefix.length + addition.length,
  };
}

export function NodeChat({
  project,
  node,
  nodes = {},
  glossaryIndex,
  conversationTitle,
  header,
  headerState,
  runScope,
  tasks,
  watchers = EMPTY_WATCHERS,
  historyMessages = [],
  importedSessionId,
  chatId,
  presentation = "floating",
  fixedConversation = false,
  readOnly = false,
  reviewPending = false,
  graphChangesDisabled = false,
  onStartTask,
  onInspectTask,
  onOpenInbox,
  onRepairGraphUpdate,
  onOpenNode,
  onStopWatcher,
  onNewSession,
  onClose,
  onResumeTask,
  onRetryTask,
  onRefreshTask,
}: Props) {
  const surface = node ? "node_chat" : "project_chat";
  const computeConnections = useMemo(
    () => project.compute_connections ?? [],
    [project.compute_connections],
  );
  const skillCatalog = project.skill_catalog ?? [];
  const skillDefaults = project.skill_defaults ?? { workflow_ids: [], skill_ids: [] };
  const relatedTasks = useMemo(
    () => relatedChatTasks(tasks, surface, node?.id, chatId),
    [chatId, node?.id, surface, tasks],
  );
  const [steeringMessages, setSteeringMessages] = useState<{
    chatId: string;
    messages: ChatMessage[];
  }>({ chatId, messages: [] });
  useEffect(() => {
    setSteeringMessages({ chatId, messages: [] });
  }, [chatId]);
  const displayedMessages = useMemo(() => {
    const messages = new Map(historyMessages.map((message) => [message.message_id, message]));
    if (steeringMessages.chatId === chatId) {
      steeringMessages.messages.forEach((message) => messages.set(message.message_id, message));
    }
    return [...messages.values()];
  }, [chatId, historyMessages, steeringMessages]);
  const [pendingTurn, setPendingTurn] = useState<PendingChatTurn | null>(null);
  const transcript = useMemo(
    () =>
      hideResolvedCodexHandoffErrors(
        orderTranscriptLines([
          ...reconcileChatHistoryArtifacts(displayedMessages, relatedTasks),
          ...reconstructTaskTranscript(
            chatTasksMissingFromHistory(relatedTasks, displayedMessages),
          ),
          ...(pendingTurn
            ? [
                {
                  lineId: `pending:${pendingTurn.clientId}`,
                  role: "human" as const,
                  text: pendingTurn.text,
                  taskId: pendingTurn.clientId,
                  timestamp: pendingTurn.timestamp,
                  mode: pendingTurn.mode,
                  attachments: pendingTurn.attachments,
                  trigger: "human" as const,
                },
              ]
            : []),
        ]),
        relatedTasks,
      ),
    [displayedMessages, pendingTurn, relatedTasks],
  );
  const config = useMemo(
    () =>
      latestPersistedChatConfig(
        historyMessages,
        relatedTasks,
        profileRunConfig(project.agent_profiles[surface]),
      ),
    [historyMessages, project.agent_profiles, relatedTasks, surface],
  );
  const [scope, setScope] = useState(() =>
    reconcileChatRunScope([], runScope, project.project_truth_scope, true),
  );
  const worktree = useConversationWorktree(
    project.id,
    chatId,
    node ? "node" : "project",
    node?.id ?? null,
    config.run_on,
    scope,
    relatedTasks.map((task) => `${task.operation_id}:${task.updated_at}`).join("\0"),
    !readOnly,
    project.graph_target,
  );
  const scopeIdentityRef = useRef(`${project.id}\0${chatId}`);
  const requestedScopeKey = runScope.join("\0");
  const projectTruthScopeKey = project.project_truth_scope.join("\0");
  const draftKey = chatDraftStorageKey(project.id, chatId);
  const modeKey = chatModeStorageKey(project.id, chatId);
  const artifactContextKey = artifactContextStorageKey(project.id, chatId);
  const appliedArtifactContextKey = `${artifactContextKey}:applied`;
  const annotationsKey = chatAnnotationsStorageKey(project.id, chatId);
  const annotationPanelId = useId();
  const derivedMode = useMemo(
    () => latestPersistedConversationMode(historyMessages, relatedTasks),
    [historyMessages, relatedTasks],
  );
  const derivedComputeIds = useMemo(
    () => latestPersistedComputeIds(historyMessages, relatedTasks, computeConnections),
    [computeConnections, historyMessages, relatedTasks],
  );
  const [message, setMessageState] = useState(() => readStorage(draftKey) ?? "");
  const setMessage = useCallback(
    (value: string | ((current: string) => string)) => {
      setMessageState((current) => {
        const next = typeof value === "function" ? value(current) : value;
        const span = readArtifactDraftSpan(readStorage(appliedArtifactContextKey));
        if (span)
          writeStorage(
            appliedArtifactContextKey,
            JSON.stringify(moveArtifactDraftSpan(span, next)),
          );
        return next;
      });
    },
    [appliedArtifactContextKey],
  );
  const [artifactContext, setArtifactContext] = useState<ArtifactContextRequest | null>(null);
  const [annotations, setAnnotations] = useState<StagedChatAnnotation[]>(() =>
    readStagedChatAnnotations(annotationsKey),
  );
  const [annotationComposer, setAnnotationComposer] = useState<ChatAnnotationComposer | null>(null);
  const [annotationComment, setAnnotationComment] = useState("");
  const [annotationViewport, setAnnotationViewport] =
    useState<ChatAnnotationViewportMetrics | null>(null);
  const [annotationsOpen, setAnnotationsOpen] = useState(false);
  const lastArtifactContextRef = useRef<string | null>(null);
  const [modeState, setModeState] = useState<{ value: ConversationMode; pinned: boolean }>(() => {
    const storedMode = parseConversationMode(readStorage(modeKey));
    return { value: storedMode ?? derivedMode, pinned: Boolean(storedMode) };
  });
  const [computeState, setComputeState] = useState<{ ids: string[]; pinned: boolean }>(() => ({
    ids: derivedComputeIds,
    pinned: false,
  }));
  const computeIdentityRef = useRef(`${project.id}\0${chatId}`);
  const [computeMenuOpen, setComputeMenuOpen] = useState(false);
  const modeRef = useRef(modeState.value);
  const [submitting, setSubmitting] = useState(false);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [attachmentSetId, setAttachmentSetId] = useState<string | null>(null);
  const [draggingFiles, setDraggingFiles] = useState(false);
  const [dictationState, setDictationState] = useState<
    "idle" | "starting" | "recording" | "stopping" | "error"
  >("idle");
  const [dictationError, setDictationError] = useState<string | null>(null);
  const [expiryClock, setExpiryClock] = useState(() => Date.now());
  const [expandedHumanMessageIds, setExpandedHumanMessageIds] = useState<Set<string>>(
    () => new Set(),
  );
  const chatLinesRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const annotationCommentRef = useRef<HTMLTextAreaElement | null>(null);
  const annotationSelectionRef = useRef<HTMLTextAreaElement | null>(null);
  const annotationComposerRef = useRef<HTMLFormElement | null>(null);
  const annotationOriginRef = useRef<HTMLElement | null>(null);
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const revisionDialogRef = useRef<HTMLElement | null>(null);
  const revisionCloseRef = useRef<HTMLButtonElement | null>(null);
  const attachmentSetIdRef = useRef<string | null>(null);
  const attachmentUploadBusyRef = useRef(false);
  const cancelledAttachmentIdsRef = useRef<Set<string>>(new Set());
  const dictationSpanRef = useRef<DictationSpan | null>(null);
  const dictationTimerRef = useRef<number | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const handleImportedContextLoaded = useCallback(() => {
    const element = chatLinesRef.current;
    if (element && shouldStickToBottomRef.current) element.scrollTop = element.scrollHeight;
  }, []);
  const lastChatIdRef = useRef(chatId);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [repairingTaskId, setRepairingTaskId] = useState<string | null>(null);
  const [repairErrors, setRepairErrors] = useState<Map<string, string>>(() => new Map());
  const [unavailableArtifacts, setUnavailableArtifacts] = useState<Set<string>>(() => new Set());
  const [artifactShellErrors, setArtifactShellErrors] = useState<Map<string, string>>(
    () => new Map(),
  );
  const [revisionReview, setRevisionReview] = useState<ArtifactRevisionReview | null>(null);
  const [revisionDecision, setRevisionDecision] = useState<"accept" | "reject" | null>(null);
  const [revisionDecisionError, setRevisionDecisionError] = useState<string | null>(null);
  const [repositoryFileErrors, setRepositoryFileErrors] = useState<Map<string, string>>(
    () => new Map(),
  );
  const [watchersOpen, setWatchersOpen] = useState(false);
  const readiness = project.provider_readiness[config.run_on]?.[config.provider];
  const skills = useSkillPicker({
    catalog: skillCatalog,
    defaults: skillDefaults,
    provider: config.provider,
    providerLabel: readiness?.label || config.provider,
    machine: config.run_on,
    inventory: project.provider_skill_inventories?.[config.run_on]?.[config.provider],
    message,
    onComplete: (next) => {
      setMessage(next);
      setSubmitError(null);
      window.requestAnimationFrame(() => {
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(next.length, next.length);
      });
    },
  });
  const desktop = useMemo(() => isDesktopRuntime(), []);
  const relatedActive = relatedTasks.some(isActiveTask);
  // While the watched turn can take live input, the ordinary composer addresses
  // that exact attempt instead of starting a new turn. There is no separate
  // steering control; a runtime without an input channel leaves the composer
  // unavailable exactly as any other running turn does.
  const steeringTask = [...relatedTasks]
    .reverse()
    .find((task) => task.active && task.steer_visible && task.can_steer && task.steer_turn_id);
  const composerHint = steeringTask
    ? steeringTask.steer_action_label
    : [...relatedTasks].reverse().find((task) => task.active)?.steer_unavailable_reason;
  const awaitingSteerReceipt = Boolean(steeringTask) && submitting;
  const revisionReviewTask = revisionReview
    ? (relatedTasks.find((task) => task.operation_id === revisionReview.taskId) ?? null)
    : null;
  const revisionReviewArtifact = revisionReviewTask?.result?.artifacts?.find(
    (artifact) => artifact.artifact_id === revisionReview?.artifactId,
  );
  const revisionReviewCandidate = revisionReviewArtifact?.revision_candidate ?? null;

  useEffect(() => {
    if (!revisionReview || !revisionReviewCandidate) return;
    const returnFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const restoreBackground = revisionDialogRef.current
      ? makeAutoResearchDialogBackgroundInert(revisionDialogRef.current)
      : () => undefined;
    const frame = window.requestAnimationFrame(() => revisionCloseRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      restoreBackground();
      restoreAutoResearchDialogFocus(returnFocus);
    };
  }, [revisionReview, revisionReviewCandidate?.candidate_id]);

  useEffect(() => {
    if (!revisionReview || !revisionReviewCandidate) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!revisionDialogRef.current) return;
      handleAutoResearchDialogKeyDown(
        event,
        revisionDialogRef.current,
        document.activeElement,
        Boolean(revisionDecision),
        () => setRevisionReview(null),
      );
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [revisionDecision, revisionReview, revisionReviewCandidate?.candidate_id]);

  useEffect(() => {
    const accept = (raw: unknown, restoring = false) => {
      const payload = parseArtifactContextPayload(raw);
      if (!payload || payload.project_id !== project.id || payload.chat_id !== chatId) return;
      const source = relatedTasks.find((task) => task.operation_id === payload.operation_id);
      const sourceKind = payload.source ?? "task";
      const sourceArtifact = source?.result?.artifacts?.find(
        (artifact) => artifact.artifact_id === payload.artifact_id,
      );
      if (!source || (sourceKind === "task" && (!sourceArtifact || !sourceArtifact.can_discuss)))
        return;
      const signature = JSON.stringify(payload);
      if (lastArtifactContextRef.current === signature) return;
      lastArtifactContextRef.current = signature;
      setArtifactContext({
        source: sourceKind,
        operation_id: payload.operation_id,
        artifact_id: payload.artifact_id,
        ...(sourceKind === "episode_report" && payload.episode_id
          ? { episode_id: payload.episode_id }
          : {}),
        selections: payload.selections,
      });
      // The preview can bring a different window or chat surface forward. Keep
      // the attachment with its draft without appending its text again on mount.
      window.requestAnimationFrame(() => textareaRef.current?.focus());
      setMessageState((current) => {
        const previousDraft = readStorage(appliedArtifactContextKey);
        const previous = readArtifactDraftSpan(previousDraft);
        if (restoring && previous?.signature === signature && previous.message === current)
          return current;
        const next = updateArtifactContextDraft(current, payload, previousDraft);
        writeStorage(draftKey, next.message);
        writeStorage(appliedArtifactContextKey, JSON.stringify(next));
        return next.message;
      });
    };
    const stored = readStorage(artifactContextKey);
    if (stored) {
      try {
        accept(JSON.parse(stored), true);
      } catch {
        removeStorage(artifactContextKey);
      }
    }
    const storage = (event: StorageEvent) => {
      if (event.key !== artifactContextKey || !event.newValue) return;
      try {
        accept(JSON.parse(event.newValue));
      } catch {
        removeStorage(artifactContextKey);
      }
    };
    window.addEventListener("storage", storage);
    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel("rcp-artifact-context");
      channel.addEventListener("message", (event) => accept(event.data));
    } catch {
      // Storage events remain the cross-window path where BroadcastChannel is unavailable.
    }
    return () => {
      window.removeEventListener("storage", storage);
      channel?.close();
    };
  }, [artifactContextKey, appliedArtifactContextKey, chatId, draftKey, project.id, relatedTasks]);
  const apiBase = `/api/projects/${encodeURIComponent(project.id)}`;
  const watcherVisibility = useHiddenWatchers(apiBase);
  const watcherRows = useMemo(
    () => visibleChatWatchers(watchers, chatId, node),
    [chatId, node, watchers],
  );
  const visibleWatcherRows = watcherRows.filter((watcher) => !watcherVisibility.isHidden(watcher));
  const hiddenWatchers = watcherRows.filter(watcherVisibility.isHidden);
  const continuedTaskIds = useMemo(
    () =>
      new Set(
        relatedTasks.flatMap((task) =>
          task.parent_operation_id ? [task.parent_operation_id] : [],
        ),
      ),
    [relatedTasks],
  );
  const pausedAttempt = resumablePausedChatTask(relatedTasks);
  const providerReady =
    readiness === undefined || Boolean(readiness.installed && readiness.authenticated);
  const sessionId =
    latestNativeSessionId(relatedTasks) ??
    [...historyMessages].reverse().find((message) => message.native_session_id)
      ?.native_session_id ??
    null;
  const mode = modeState.value;
  modeRef.current = mode;
  const chatTitle = node?.title || conversationTitle || project.name;
  const attachmentClientId = useMemo(() => chatAttachmentClientId(), []);
  const readyAttachments = attachments.flatMap((item) =>
    item.status === "ready" && item.descriptor ? [item.descriptor] : [],
  );
  const attachmentsPreparing = attachments.some((item) => item.status === "preparing");
  const attachmentsUnready = attachments.some((item) => item.status !== "ready");
  const annotationComposerOpen = annotationComposer !== null;
  const annotationsComplete = stagedChatAnnotationsAreComplete(annotations);
  const dictating = dictationState !== "idle" && dictationState !== "error";
  useEffect(() => {
    const identity = `${project.id}\0${chatId}`;
    const reset = scopeIdentityRef.current !== identity;
    scopeIdentityRef.current = identity;
    setScope((current) =>
      reconcileChatRunScope(current, runScope, project.project_truth_scope, reset),
    );
  }, [chatId, project.id, projectTruthScopeKey, requestedScopeKey]);

  useEffect(() => {
    setModeState((current) =>
      current.pinned || current.value === derivedMode
        ? current
        : { ...current, value: derivedMode },
    );
  }, [derivedMode]);

  useEffect(() => {
    const identity = `${project.id}\0${chatId}`;
    const reset = computeIdentityRef.current !== identity;
    computeIdentityRef.current = identity;
    setComputeState((current) => {
      if (reset) return { ids: derivedComputeIds, pinned: false };
      const reconciled = reconcileActiveComputeIds(current.ids, computeConnections);
      if (current.pinned) return { ...current, ids: reconciled };
      return { ids: derivedComputeIds, pinned: false };
    });
    if (reset) setComputeMenuOpen(false);
  }, [chatId, computeConnections, derivedComputeIds, project.id]);

  useEffect(() => {
    skills.reset();
    // Settings supplies fresh conversation defaults; an open turn keeps its own.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, project.id]);

  useEffect(() => {
    if (message) writeStorage(draftKey, message);
    else removeStorage(draftKey);
  }, [draftKey, message]);

  useEffect(() => {
    if (annotations.length) writeSessionStorage(annotationsKey, JSON.stringify(annotations));
    else removeSessionStorage(annotationsKey);
  }, [annotations, annotationsKey]);

  useEffect(() => {
    if (!annotationComposerOpen) {
      setAnnotationViewport(null);
      return;
    }
    const viewport = window.visualViewport;
    const update = () => {
      setAnnotationViewport(
        chatAnnotationViewportMetrics(
          { width: window.innerWidth, height: window.innerHeight },
          viewport,
        ),
      );
    };
    update();
    viewport?.addEventListener("resize", update);
    viewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      viewport?.removeEventListener("resize", update);
      viewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [annotationComposerOpen]);

  useLayoutEffect(() => {
    const composer = annotationComposerRef.current;
    if (!composer || !annotationComposer || !annotationViewport) return;
    const update = () => {
      const rect = composer.getBoundingClientRect();
      const position = chatAnnotationComposerPosition(
        annotationComposer.anchor,
        annotationViewport,
        rect,
      );
      setAnnotationComposer((current) => {
        if (
          !current ||
          current.anchor !== annotationComposer.anchor ||
          (current.position?.left === position.left && current.position.top === position.top)
        )
          return current;
        return { ...current, position };
      });
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(composer);
    return () => observer.disconnect();
  }, [annotationComposer, annotationViewport]);

  useEffect(() => {
    if (lastChatIdRef.current !== chatId) {
      lastChatIdRef.current = chatId;
      shouldStickToBottomRef.current = true;
      setRepositoryFileErrors(new Map());
    }
    const element = chatLinesRef.current;
    if (!element || !shouldStickToBottomRef.current) return;
    element.scrollTop = element.scrollHeight;
  }, [chatId, transcript]);

  useEffect(() => {
    attachmentSetIdRef.current = attachmentSetId;
  }, [attachmentSetId]);

  useEffect(() => {
    if (!transcript.some((line) => line.attachments?.length)) return;
    const timer = window.setInterval(() => setExpiryClock(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [transcript]);

  useEffect(() => {
    if (!desktop) return;
    let disposed = false;
    const unlisten: Array<() => void> = [];
    void listenDesktopEvent<DictationResultEvent>("rcp://dictation-result", (payload) => {
      const span = dictationSpanRef.current;
      if (!span || span.sessionId !== payload.session_id) return;
      setMessage((current) => {
        const next = replaceTextSpan(current, span, payload.text);
        span.end = next.end;
        skills.readMessage(next.value);
        return next.value;
      });
      window.requestAnimationFrame(() => {
        const active = dictationSpanRef.current;
        if (!active || active.sessionId !== payload.session_id) return;
        textareaRef.current?.setSelectionRange(active.end, active.end);
      });
    }).then((dispose) => (disposed ? dispose() : unlisten.push(dispose)));
    void listenDesktopEvent<DictationStateEvent>("rcp://dictation-state", (payload) => {
      if (dictationSpanRef.current?.sessionId !== payload.session_id) return;
      if (payload.state === "recording") setDictationState("recording");
      if (payload.state === "error") {
        clearDictationTimer(dictationTimerRef);
        dictationSpanRef.current = null;
        setDictationState("error");
        setDictationError(payload.error || "Dictation stopped unexpectedly.");
      }
      if (payload.state === "stopped") {
        clearDictationTimer(dictationTimerRef);
        dictationSpanRef.current = null;
        setDictationState("idle");
      }
    }).then((dispose) => (disposed ? dispose() : unlisten.push(dispose)));
    return () => {
      disposed = true;
      unlisten.forEach((dispose) => dispose());
      clearDictationTimer(dictationTimerRef);
      const sessionId = dictationSpanRef.current?.sessionId;
      dictationSpanRef.current = null;
      if (sessionId) void stopDesktopDictation(sessionId);
    };
    // The event bridge belongs to the native shell lifetime, not each draft render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop]);

  const selectMode = useCallback(
    (next: ConversationMode) => {
      modeRef.current = next;
      writeStorage(modeKey, next);
      setModeState({ value: next, pinned: true });
    },
    [modeKey],
  );

  const toggleMode = useCallback(() => {
    // A follow-up inherits the running turn's capability, so the toggle would
    // describe something it cannot change. While a turn merely runs unsteerable,
    // the choice still belongs to the next turn and stays available.
    if (steeringTask) return;
    selectMode(toggleConversationMode(modeRef.current));
  }, [steeringTask, selectMode]);

  useEffect(() => {
    if (presentation !== "workspace" || readOnly) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      if (!isConversationModeShortcut(event.key, event.shiftKey)) return;
      event.preventDefault();
      toggleMode();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [presentation, readOnly, toggleMode]);

  const updateMessage = (next: string) => {
    if (readOnly) return;
    if (next && !modeState.pinned) {
      writeStorage(modeKey, mode);
      setModeState({ value: mode, pinned: true });
    }
    setMessage(next);
    skills.readMessage(next);
    setSubmitError(null);
  };

  const stopDictation = (invalidate = false) => {
    const sessionId = dictationSpanRef.current?.sessionId;
    if (!sessionId) return;
    clearDictationTimer(dictationTimerRef);
    setDictationState("stopping");
    if (invalidate) {
      dictationSpanRef.current = null;
      setDictationState("idle");
    }
    void stopDesktopDictation(sessionId).catch((error) => {
      dictationSpanRef.current = null;
      setDictationState("error");
      setDictationError(error instanceof Error ? error.message : String(error));
    });
  };

  const toggleDictation = async () => {
    if (readOnly) return;
    if (dictating) {
      stopDictation();
      return;
    }
    const textarea = textareaRef.current;
    const start = textarea?.selectionStart ?? message.length;
    const sessionId = crypto.randomUUID();
    dictationSpanRef.current = { sessionId, start, end: start };
    writeStorage(modeKey, mode);
    setModeState({ value: mode, pinned: true });
    setSubmitError(null);
    setDictationError(null);
    setDictationState("starting");
    try {
      await startDesktopDictation(sessionId);
      if (dictationSpanRef.current?.sessionId !== sessionId) return;
      setDictationState("recording");
      dictationTimerRef.current = window.setTimeout(() => stopDictation(), 55_000);
    } catch (error) {
      dictationSpanRef.current = null;
      setDictationState("error");
      setDictationError(error instanceof Error ? error.message : String(error));
    }
  };

  const addFiles = async (incoming: File[]) => {
    if (readOnly) return;
    setDraggingFiles(false);
    if (attachmentUploadBusyRef.current) {
      setSubmitError("Wait for the current files to finish preparing before adding more.");
      return;
    }
    attachmentUploadBusyRef.current = true;
    setSubmitError(null);
    const available = Math.max(0, MAX_CHAT_ATTACHMENTS - attachments.length);
    if (incoming.length > available) {
      setSubmitError(`A turn can include at most ${MAX_CHAT_ATTACHMENTS} files.`);
    }
    const candidates = incoming.slice(0, available).map<ComposerAttachment>((file) => ({
      localId: crypto.randomUUID(),
      file,
      status: "preparing",
    }));
    let total = attachments.reduce(
      (sum, item) => (item.status === "error" ? sum : sum + item.file.size),
      0,
    );
    for (const item of candidates) {
      const validation = validateChatAttachment(item.file, total);
      if (validation) {
        item.status = "error";
        item.error = validation;
      } else {
        total += item.file.size;
      }
    }
    setAttachments((current) => [...current, ...candidates]);

    const uploadCandidates = candidates.filter((candidate) => candidate.status === "preparing");
    for (const [index, item] of uploadCandidates.entries()) {
      try {
        const result = await uploadChatAttachment(
          apiBase,
          chatId,
          item.file,
          attachmentClientId,
          attachmentSetIdRef.current,
        );
        attachmentSetIdRef.current = result.attachment_set_id;
        setAttachmentSetId(result.attachment_set_id);
        if (cancelledAttachmentIdsRef.current.delete(item.localId)) {
          await removeChatAttachment(
            apiBase,
            chatId,
            result.attachment_set_id,
            result.attachment.attachment_id,
            attachmentClientId,
          );
          continue;
        }
        setAttachments((current) =>
          current.map((candidate) =>
            candidate.localId === item.localId
              ? { ...candidate, status: "ready", descriptor: result.attachment }
              : candidate,
          ),
        );
      } catch (error) {
        const cancelled = cancelledAttachmentIdsRef.current.delete(item.localId);
        const detail = error instanceof Error ? error.message : String(error);
        if (!cancelled) {
          setAttachments((current) =>
            current.map((candidate) =>
              candidate.localId === item.localId
                ? {
                    ...candidate,
                    status: "error",
                    error: detail,
                  }
                : candidate,
            ),
          );
        }
        if (!attachmentSetIdRef.current) {
          const remaining = new Set(
            uploadCandidates.slice(index + 1).map((candidate) => candidate.localId),
          );
          setAttachments((current) =>
            current.map((candidate) =>
              remaining.has(candidate.localId)
                ? { ...candidate, status: "error", error: "Attachment set could not be created" }
                : candidate,
            ),
          );
          break;
        }
      }
    }
    attachmentUploadBusyRef.current = false;
  };

  const removeAttachment = (item: ComposerAttachment) => {
    if (item.status === "preparing") cancelledAttachmentIdsRef.current.add(item.localId);
    setAttachments((current) => current.filter((candidate) => candidate.localId !== item.localId));
    const setId = attachmentSetIdRef.current;
    if (setId && item.descriptor) {
      void removeChatAttachment(
        apiBase,
        chatId,
        setId,
        item.descriptor.attachment_id,
        attachmentClientId,
      ).catch((error) => setSubmitError(error instanceof Error ? error.message : String(error)));
    }
  };

  const toggleHumanMessage = (messageId: string) => {
    setExpandedHumanMessageIds((current) => {
      const next = new Set(current);
      if (next.has(messageId)) next.delete(messageId);
      else next.add(messageId);
      return next;
    });
  };

  const handleChatScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    shouldStickToBottomRef.current =
      element.scrollHeight - element.scrollTop - element.clientHeight <=
      CHAT_SCROLL_BOTTOM_TOLERANCE_PX;
  };

  const openAnnotationComposer = (range: Range) => {
    if (submitting) return;
    const selectedText = range.toString().trim();
    if (!selectedText) return;
    if (selectedText.length > MAX_CHAT_ANNOTATION_TEXT_LENGTH) {
      setSubmitError(
        `Select at most ${MAX_CHAT_ANNOTATION_TEXT_LENGTH.toLocaleString()} characters for one comment.`,
      );
      return;
    }
    if (annotations.length >= MAX_CHAT_ANNOTATIONS) {
      setSubmitError(`A turn can include at most ${MAX_CHAT_ANNOTATIONS} annotations.`);
      return;
    }
    // Show the reader the text that will be staged, not the overshoot.
    const selection = window.getSelection();
    if (selection) {
      selection.removeAllRanges();
      selection.addRange(range);
    }
    const rects = range.getClientRects();
    const rect = rects.item(rects.length - 1) ?? range.getBoundingClientRect();
    annotationOriginRef.current = null;
    setAnnotationComment("");
    setSubmitError(null);
    setAnnotationComposer({
      step: "comment",
      selectedText,
      anchor: { left: rect.left, right: rect.right, top: rect.top },
      position: null,
    });
    window.requestAnimationFrame(() => annotationCommentRef.current?.focus());
  };

  // The pointer often lifts outside the answer that was swept, so the release is
  // observed on the document and the answer is resolved from the selection itself.
  const openAnnotationComposerRef = useRef(openAnnotationComposer);
  openAnnotationComposerRef.current = openAnnotationComposer;
  useEffect(() => {
    if (readOnly) return;
    const onPointerUp = (event: PointerEvent) => {
      // Clicks inside the open composer must not restart it over the same selection.
      if (event.target instanceof Node && annotationComposerRef.current?.contains(event.target))
        return;
      const range = annotatableAnswerSelectionRange(window.getSelection(), chatLinesRef.current);
      if (range) openAnnotationComposerRef.current(range);
    };
    // Capture phase: a release over a window resize corner stops propagation.
    document.addEventListener("pointerup", onPointerUp, { capture: true });
    return () => document.removeEventListener("pointerup", onPointerUp, { capture: true });
  }, [readOnly]);

  const openKeyboardAnnotationComposer = (answer: HTMLElement, origin: HTMLElement) => {
    if (submitting) return;
    if (annotations.length >= MAX_CHAT_ANNOTATIONS) {
      setSubmitError(`A turn can include at most ${MAX_CHAT_ANNOTATIONS} annotations.`);
      return;
    }
    const answerText = answer.innerText.trim();
    if (!answerText) return;
    const rect = origin.getBoundingClientRect();
    annotationOriginRef.current = origin;
    setAnnotationComment("");
    setSubmitError(null);
    setAnnotationComposer({
      step: "select",
      answerText,
      selectedText: "",
      anchor: { left: rect.left, right: rect.right, top: rect.top },
      position: null,
    });
    window.requestAnimationFrame(() => {
      annotationSelectionRef.current?.focus();
      annotationSelectionRef.current?.setSelectionRange(0, 0);
    });
  };

  const updateKeyboardAnnotationSelection = (control: HTMLTextAreaElement) => {
    const selectedText = chatAnnotationTextControlSelection(control);
    setAnnotationComposer((current) =>
      current?.step === "select" ? { ...current, selectedText } : current,
    );
  };

  const continueKeyboardAnnotation = () => {
    if (submitting) return;
    if (annotationComposer?.step !== "select") return;
    const selectedText = annotationComposer.selectedText;
    if (!selectedText || selectedText.length > MAX_CHAT_ANNOTATION_TEXT_LENGTH) return;
    setAnnotationComposer({
      step: "comment",
      selectedText,
      anchor: annotationComposer.anchor,
      position: null,
    });
    window.requestAnimationFrame(() => annotationCommentRef.current?.focus());
  };

  const dismissAnnotationComposer = (returnFocus: boolean) => {
    const origin = annotationOriginRef.current;
    annotationOriginRef.current = null;
    setAnnotationComposer(null);
    setAnnotationComment("");
    if (returnFocus) {
      window.requestAnimationFrame(() => (origin ?? textareaRef.current)?.focus());
    }
  };

  const stageAnnotation = () => {
    if (submitting) return;
    if (!annotationComposer) return;
    if (annotationComposer.step !== "comment") return;
    const comment = annotationComment.trim();
    if (!comment) return;
    setAnnotations((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        selectedText: annotationComposer.selectedText,
        comment,
      },
    ]);
    setAnnotationsOpen(false);
    dismissAnnotationComposer(false);
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const updateAnnotation = (id: string, comment: string) => {
    if (submitting) return;
    setAnnotations((current) =>
      current.map((annotation) => (annotation.id === id ? { ...annotation, comment } : annotation)),
    );
    setSubmitError(null);
  };

  const removeAnnotation = (id: string) => {
    if (submitting) return;
    setAnnotations((current) => {
      const next = current.filter((annotation) => annotation.id !== id);
      if (next.length === 0) setAnnotationsOpen(false);
      return next;
    });
  };

  const steer = async (task: AgentTask) => {
    const draftMessage = message;
    const draftAnnotations = annotations;
    const draftArtifactContext = artifactContext;
    const text = assembleChatTurn(message, annotations);
    if (!annotationsComplete) {
      setAnnotationsOpen(true);
      setSubmitError("Each staged annotation needs a comment.");
      return;
    }
    if (!text || attachments.length || submitting || !task.steer_turn_id) return;
    if (dictating) stopDictation(true);
    shouldStickToBottomRef.current = true;
    const request = {
      message_id: crypto.randomUUID(),
      attempt: task.attempt,
      expected_turn_id: task.steer_turn_id,
      message: text,
    };
    setSubmitError(null);
    setSubmitting(true);
    try {
      const receipt = await steerChatTurn(project.id, task.operation_id, request);
      setSteeringMessages((current) =>
        current.chatId !== chatId
          ? current
          : {
              chatId,
              messages: [
                ...current.messages.filter((entry) => entry.message_id !== receipt.message_id),
                receipt,
              ],
            },
      );
      // Typing and skill selection are fenced while the receipt is awaited, so
      // the delivered draft is exactly what is consumed. Artifact context can
      // still arrive from another view meanwhile; it and the text it appended
      // survive, while selections that described the delivered message are
      // reset so they cannot attach themselves to the next ordinary turn.
      setMessage((current) => (current === draftMessage ? "" : current));
      setAnnotations((current) => (current === draftAnnotations ? [] : current));
      setArtifactContext((current) => {
        if (current !== draftArtifactContext) return current;
        removeStorage(artifactContextKey);
        removeStorage(appliedArtifactContextKey);
        return null;
      });
      setAnnotationsOpen(false);
      skills.reset();
      lastArtifactContextRef.current = null;
    } catch (error) {
      setSubmitError(
        `Steering receipt could not be read. Nothing was resent. ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setSubmitting(false);
    }
  };

  const send = async () => {
    if (readOnly) return;
    if (steeringTask) return steer(steeringTask);
    if (mode === "work" && worktree.chosen && !worktree.state?.can_choose) {
      setSubmitError(
        worktree.error ??
          worktree.state?.unavailable_reason ??
          "Worktree eligibility has not been confirmed.",
      );
      return;
    }
    const draftMessage = message;
    const text = assembleChatTurn(message, annotations);
    if (!annotationsComplete) {
      setAnnotationsOpen(true);
      setSubmitError("Each staged annotation needs a comment.");
      return;
    }
    if (
      !text ||
      attachmentsUnready ||
      relatedActive ||
      pausedAttempt ||
      submitting ||
      repairingTaskId ||
      reviewPending
    )
      return;
    if (dictating) stopDictation(true);
    shouldStickToBottomRef.current = true;
    const clientId = `pending-${crypto.randomUUID()}`;
    setPendingTurn({
      clientId,
      text,
      timestamp: new Date().toISOString(),
      mode,
      attachments: readyAttachments,
    });
    setMessageState("");
    setSubmitError(null);
    setSubmitting(true);
    try {
      await startConversationTurn(onStartTask, {
        kind: surface,
        config,
        runTruthScope: scope,
        nodeId: node?.id ?? null,
        message: text,
        chatId,
        sessionId,
        mode,
        activeComputeIds: computeState.ids,
        artifactContext,
        attachmentSetId: readyAttachments.length ? attachmentSetId : null,
        attachmentClientId: readyAttachments.length ? attachmentClientId : null,
        skills: skills.selection,
        providerSkillNames: skills.providerSkillNames,
        worktree: mode === "work" && worktree.chosen,
      });
      worktree.refresh();
      setPendingTurn((current) => (current?.clientId === clientId ? null : current));
      skills.reset();
      setAttachments([]);
      setArtifactContext(null);
      removeStorage(artifactContextKey);
      removeStorage(appliedArtifactContextKey);
      setAnnotations([]);
      setAnnotationsOpen(false);
      removeSessionStorage(annotationsKey);
      lastArtifactContextRef.current = null;
      setAttachmentSetId(null);
      attachmentSetIdRef.current = null;
      selectMode(mode);
    } catch (error) {
      setPendingTurn((current) => (current?.clientId === clientId ? null : current));
      setMessage((current) => (current ? current : draftMessage));
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const integrateWorktree = async (option: WorktreeIntegrationOption) => {
    if (
      readOnly ||
      relatedActive ||
      pausedAttempt ||
      submitting ||
      reviewPending ||
      repairingTaskId
    )
      return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await startConversationTurn(onStartTask, {
        kind: surface,
        config,
        runTruthScope: scope,
        nodeId: node?.id ?? null,
        message: option.label,
        chatId,
        sessionId,
        mode: "work",
        activeComputeIds: computeState.ids,
        worktreeIntegration: option.id,
      });
      selectMode("work");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
      worktree.refresh();
    }
  };

  const repairGraphUpdate = async (taskId: string) => {
    if (readOnly || repairingTaskId) return;
    setRepairingTaskId(taskId);
    setRepairErrors((current) => withoutMapKey(current, taskId));
    try {
      await onRepairGraphUpdate(taskId);
    } catch (error) {
      setRepairErrors((current) =>
        withMapValue(current, taskId, error instanceof Error ? error.message : String(error)),
      );
    } finally {
      setRepairingTaskId(null);
    }
  };

  const markArtifactUnavailable = (taskId: string, artifactId: string) => {
    setUnavailableArtifacts((current) => {
      const next = new Set(current);
      next.add(`${taskId}:${artifactId}`);
      return next;
    });
  };

  const openArtifact = async (
    taskId: string,
    artifact: AgentArtifactDescriptor,
    reserved: Window | null = null,
  ) => {
    if (!artifact.can_open) return;
    if (desktop) {
      const key = `${taskId}:${artifact.artifact_id}`;
      setArtifactShellErrors((current) => withoutMapKey(current, key));
      try {
        await openDesktopArtifactPreview({
          projectId: project.id,
          taskId,
          artifactId: artifact.artifact_id,
        });
      } catch (error) {
        setArtifactShellErrors((current) =>
          withMapValue(
            current,
            key,
            `Open failed: ${error instanceof Error ? error.message : String(error)}`,
          ),
        );
      }
      return;
    }
    const target = reserved ?? window.open("about:blank", "_blank");
    if (!target) {
      markArtifactUnavailable(taskId, artifact.artifact_id);
      return;
    }
    target.opener = null;
    try {
      target.location.replace(artifactUrl(project.id, taskId, artifact.artifact_id, "viewer"));
    } catch {
      target.close();
      markArtifactUnavailable(taskId, artifact.artifact_id);
    }
  };

  const downloadArtifact = async (taskId: string, artifact: AgentArtifactDescriptor) => {
    if (!artifact.can_download) return;
    const key = `${taskId}:${artifact.artifact_id}`;
    setArtifactShellErrors((current) => withoutMapKey(current, key));
    try {
      await downloadDesktopArtifact({
        projectId: project.id,
        taskId,
        artifactId: artifact.artifact_id,
        suggestedName: artifact.name,
      });
    } catch (error) {
      setArtifactShellErrors((current) =>
        withMapValue(
          current,
          key,
          `Download failed: ${error instanceof Error ? error.message : String(error)}`,
        ),
      );
    }
  };

  const decideRevision = async (decision: "accept" | "reject") => {
    const review = revisionReview;
    const candidate = revisionReviewCandidate;
    if (!review || !candidate || revisionDecision) return;
    setRevisionDecision(decision);
    setRevisionDecisionError(null);
    let decisionError: string | null = null;
    try {
      await decideArtifactRevision(project.id, candidate.candidate_id, decision);
    } catch (error) {
      decisionError = error instanceof Error ? error.message : String(error);
    }
    try {
      const refreshed = await onRefreshTask(review.taskId);
      const refreshedArtifact = refreshed.result?.artifacts?.find(
        (artifact) => artifact.artifact_id === review.artifactId,
      );
      if (!refreshedArtifact?.revision_candidate) {
        setRevisionReview(null);
      } else if (refreshedArtifact.revision_candidate.diagnostic) {
        decisionError = null;
      }
      setRevisionDecisionError(decisionError);
    } catch (error) {
      const refreshError = error instanceof Error ? error.message : String(error);
      setRevisionDecisionError(
        decisionError
          ? `${decisionError} Refresh also failed: ${refreshError}`
          : `The decision was saved, but the artifact could not refresh: ${refreshError}`,
      );
    } finally {
      setRevisionDecision(null);
    }
  };

  const openRepositoryFile = async (messageId: string, taskId: string, href: string) => {
    const resolution = resolveRepositoryFileHref(href, project.repositories);
    if (resolution.kind === "error") {
      // An answer may cite a file the turn itself wrote. That path is outside every
      // repository, so the artifact the task already registered owns the preview.
      // Only when no root claims the path. Several matching roots stay a visible
      // error, because the reader must not be handed a guess about which one won.
      const name = resolution.reason === "no-match" ? turnArtifactName(href, taskId) : null;
      if (name) {
        const known = relatedTasks.find((candidate) => candidate.operation_id === taskId);
        // A popup is only granted during the click, so claim the window before any
        // await; the desktop shell opens its own and needs no reservation.
        const reserved = known || desktop ? null : window.open("about:blank", "_blank");
        // An older answer's task has aged out of the recent list, so fetch the exact
        // task rather than refusing a citation the transcript still displays.
        const task = known ?? (await onRefreshTask(taskId).catch(() => null));
        const artifact = task?.result?.artifacts?.find((candidate) => candidate.name === name);
        if (artifact?.can_open) {
          setRepositoryFileErrors((current) => withoutMapKey(current, messageId));
          await openArtifact(taskId, artifact, reserved);
          return;
        }
        reserved?.close();
      }
      setRepositoryFileErrors((current) => withMapValue(current, messageId, resolution.message));
      return;
    }

    setRepositoryFileErrors((current) => withoutMapKey(current, messageId));
    const target = resolution.target;
    if (desktop) {
      try {
        await openDesktopRepositoryFilePreview({ projectId: project.id, ...target });
      } catch (error) {
        setRepositoryFileErrors((current) =>
          withMapValue(
            current,
            messageId,
            `Open failed: ${error instanceof Error ? error.message : String(error)}`,
          ),
        );
      }
      return;
    }

    const preview = window.open("about:blank", "_blank");
    if (!preview) {
      setRepositoryFileErrors((current) =>
        withMapValue(current, messageId, "Repository file preview could not be opened."),
      );
      return;
    }
    preview.opener = null;
    const url = repositoryFilePreviewUrl(project.id, target);
    if (!(await resourceIsAvailable(url))) {
      preview.close();
      setRepositoryFileErrors((current) =>
        withMapValue(current, messageId, "Repository file preview is unavailable."),
      );
      return;
    }
    try {
      preview.location.replace(url);
    } catch {
      preview.close();
      setRepositoryFileErrors((current) =>
        withMapValue(current, messageId, "Repository file preview could not be opened."),
      );
    }
  };

  const watcherToggle = watcherRows.length > 0 && (
    <button
      className={`chat-watcher-count${watchersOpen ? " is-open" : ""}`}
      type="button"
      aria-expanded={watchersOpen}
      aria-label={`${visibleWatcherRows.length} watcher${visibleWatcherRows.length === 1 ? "" : "s"}${hiddenWatchers.length ? `, ${hiddenWatchers.length} hidden` : ""}`}
      onClick={() => setWatchersOpen((open) => !open)}
    >
      <RadioTower size={12} /> {visibleWatcherRows.length || `${hiddenWatchers.length} hidden`}
    </button>
  );

  const contextControls = (showProvider: boolean) => (
    <div className="chat-context-controls">
      {showProvider && (
        <div
          className="agent-provider-label"
          aria-busy={readiness === undefined}
          aria-label={`Chat provider: ${readiness?.label || config.provider}`}
        >
          {readiness?.label || config.provider}
          {readiness === undefined && (
            <LoaderCircle className="spin" size={12} aria-label="Checking provider" />
          )}
        </div>
      )}
      {!fixedConversation && !readOnly && (
        <button className="chat-new-session" type="button" onClick={onNewSession}>
          <MessageCirclePlus size={13} /> New session
        </button>
      )}
      {presentation === "workspace" && watcherToggle}
      {!readOnly && (
        <div className="chat-scope-control">
          <RepositoryScope
            repositories={project.repositories}
            projectScope={project.project_truth_scope}
            stateRepository={project.state_repository}
            selected={scope}
            onChange={relatedActive || reviewPending ? () => undefined : setScope}
          />
        </div>
      )}
    </div>
  );

  return (
    <div
      className={`chat-dock ${presentation}`}
      data-mode={mode}
      role={presentation === "floating" ? "dialog" : "region"}
      aria-modal="false"
      aria-label={node || conversationTitle ? `Chat about ${chatTitle}` : "Project chat"}
      aria-keyshortcuts={presentation === "workspace" && !readOnly ? "Shift+Tab" : undefined}
    >
      {presentation === "floating" && (
        <header data-drag-handle="true">
          <MessageCircle size={17} />
          <strong>{chatTitle}</strong>
          {watcherToggle}
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Minimize chat; background work will continue"
          >
            <X size={17} />
          </button>
        </header>
      )}
      {header ? (
        <header className="conversation-header" data-state={headerState}>
          <div className="conversation-heading">{header}</div>
          {contextControls(false)}
        </header>
      ) : (
        contextControls(true)
      )}
      {watcherRows.length > 0 && watchersOpen && (
        <section className="chat-watchers" aria-label="Watchers">
          {watcherVisibility.error && <p role="alert">{watcherVisibility.error}</p>}
          {hiddenWatchers.length > 0 && (
            <button
              type="button"
              className="button compact"
              onClick={() =>
                watcherVisibility.show(hiddenWatchers.map((watcher) => watcher.watcher_id))
              }
            >
              Show hidden watchers ({hiddenWatchers.length})
            </button>
          )}
          {visibleWatcherRows.map((watcher) => {
            const external = isExternalWatcherRecord(watcher);
            const observedAt = watcherLastObservedAt(watcher);
            return (
              <div className={`chat-watcher-row ${watcher.status}`} key={watcher.watcher_id}>
                {external ? (
                  <ExternalJobRow
                    apiBase={apiBase}
                    watcher={watcher}
                    onHide={() => watcherVisibility.hide(watcher.watcher_id)}
                  />
                ) : (
                  <>
                    <strong>{graphConditionLabel(watcher.condition)}</strong>
                    {watcher.status === "completed" && (
                      <button
                        type="button"
                        className="button compact watcher-action"
                        onClick={() => watcherVisibility.hide(watcher.watcher_id)}
                        aria-label={`Hide watcher ${graphConditionLabel(watcher.condition)}`}
                      >
                        Hide
                      </button>
                    )}
                    <time dateTime={observedAt ?? undefined}>
                      {observedAt
                        ? `Evaluated ${new Date(observedAt).toLocaleString()}`
                        : "Not evaluated yet"}
                    </time>
                  </>
                )}
                {!readOnly && onStopWatcher && watcher.can_stop_watching && (
                  <button
                    className="button compact"
                    type="button"
                    onClick={() => onStopWatcher(watcher.watcher_id)}
                  >
                    Stop watching
                  </button>
                )}
              </div>
            );
          })}
        </section>
      )}
      <div
        className="node-chat-lines"
        aria-live="polite"
        onScroll={handleChatScroll}
        ref={chatLinesRef}
      >
        {importedSessionId && (
          <ImportedCodexContext
            key={`${chatId}:${importedSessionId}`}
            apiBase={`/api/projects/${encodeURIComponent(project.id)}`}
            sessionId={importedSessionId}
            chatId={chatId}
            scrollContainerRef={chatLinesRef}
            onInitialLoad={handleImportedContextLoaded}
          />
        )}
        {transcript.map((line) => {
          const messageId = line.lineId;
          const task = relatedTasks.find((candidate) => candidate.operation_id === line.taskId);
          const activeLineTask = task && !line.steering && isActiveTask(task) ? task : null;
          const pausedLineTask =
            !line.steering &&
            task?.paused &&
            task.can_resume &&
            !continuedTaskIds.has(task.operation_id)
              ? task
              : null;
          const pendingLine = pendingTurn?.clientId === line.taskId;
          const collapsible =
            line.role === "human" && line.text.length > CHAT_USER_MESSAGE_COLLAPSE_THRESHOLD;
          const expanded = expandedHumanMessageIds.has(messageId);
          return (
            <div className={`node-chat-line ${line.role}`} key={line.lineId}>
              {line.role === "human" && line.mode && (
                <span className={`chat-turn-mode ${line.mode}`}>{modeLabel(line.mode)}</span>
              )}
              {line.trigger === "watcher" && (
                <span className="chat-turn-trigger watcher">Watcher</span>
              )}
              {line.role === "agent" ? (
                line.text && (
                  <>
                    <div className="chat-markdown chat-annotatable-answer">
                      <MarkdownAnswer
                        text={line.text}
                        nodes={nodes}
                        glossaryIndex={glossaryIndex}
                        onOpenNode={onOpenNode}
                        onOpenRepositoryFileLink={(href) =>
                          void openRepositoryFile(messageId, line.taskId, href)
                        }
                      />
                    </div>
                    {/* Outside the annotatable wrapper: a selection clamp or the
                        keyboard flow must never stage this diagnostic as answer text. */}
                    {repositoryFileErrors.get(messageId) && (
                      <strong className="chat-repository-file-error" role="alert">
                        {repositoryFileErrors.get(messageId)}
                      </strong>
                    )}
                    {!readOnly && (
                      <button
                        className="chat-answer-annotation-button"
                        type="button"
                        aria-label="Comment on this answer"
                        disabled={submitting}
                        onClick={(event) => {
                          const answer =
                            event.currentTarget.parentElement?.querySelector<HTMLElement>(
                              ".chat-annotatable-answer",
                            );
                          if (answer) openKeyboardAnnotationComposer(answer, event.currentTarget);
                        }}
                      >
                        <MessageCirclePlus size={12} /> Comment
                      </button>
                    )}
                  </>
                )
              ) : line.role === "human" ? (
                <>
                  <div
                    className={`chat-human-message${collapsible && !expanded ? " collapsed" : ""}`}
                  >
                    <span className="node-chat-text">{line.text}</span>
                  </div>
                  {collapsible && (
                    <button
                      type="button"
                      className="chat-message-toggle"
                      aria-expanded={expanded}
                      onClick={() => toggleHumanMessage(messageId)}
                    >
                      {expanded ? "See less" : "See more"}
                    </button>
                  )}
                  {line.steering && (
                    <div className="chat-steering-receipt" role="status">
                      <strong>{line.steering.label}</strong>
                      {line.steering.reason && <span>{line.steering.reason}</span>}
                    </div>
                  )}
                  {line.attachments?.map((attachment) => {
                    const expired = Date.parse(attachment.expires_at) <= expiryClock;
                    return (
                      <div
                        className={`chat-input-attachment${expired ? " expired" : ""}`}
                        key={attachment.attachment_id}
                      >
                        <File size={13} />
                        <span>
                          <strong>{attachment.name}</strong>
                          <small>
                            {attachment.media_type} · {formatBytes(attachment.size)}
                          </small>
                        </span>
                        {expired && <em>Expired</em>}
                      </div>
                    );
                  })}
                  {pausedLineTask ? (
                    <InlinePausedTask
                      task={pausedLineTask}
                      disabled={readOnly}
                      onResume={() => onResumeTask(pausedLineTask)}
                      onRetry={() => onRetryTask(pausedLineTask)}
                    />
                  ) : activeLineTask ? (
                    <InlineTaskProgress task={activeLineTask} />
                  ) : pendingLine ? (
                    <InlineTaskProgress task={null} />
                  ) : null}
                </>
              ) : pausedLineTask ? null : (
                <span className="node-chat-text">{line.text}</span>
              )}
              {line.artifacts?.map((artifact) => {
                const revisionCandidate = artifact.revision_candidate ?? null;
                const taskUpdatedAt =
                  relatedTasks.find((task) => task.operation_id === line.taskId)?.updated_at ?? "";
                const runtimeUnavailable = unavailableArtifacts.has(
                  `${line.taskId}:${artifact.artifact_id}`,
                );
                const unavailable = !artifact.available || runtimeUnavailable;
                const unavailableReason =
                  (!artifact.available && artifact.unavailable_reason) ||
                  (runtimeUnavailable ? "Preview unavailable" : null);
                const shellError = artifactShellErrors.get(
                  `${line.taskId}:${artifact.artifact_id}`,
                );
                return (
                  <div
                    className={`chat-artifact${unavailable ? " unavailable" : ""}`}
                    key={artifact.artifact_id}
                  >
                    {artifact.media_type !== "text/html" &&
                      artifact.size_bytes != null &&
                      artifact.size_bytes <= INLINE_ARTIFACT_MAX_BYTES &&
                      artifact.can_open &&
                      !unavailable && (
                        <button
                          className="chat-artifact-inline"
                          type="button"
                          aria-label={`Open ${artifact.name}`}
                          onClick={() => void openArtifact(line.taskId, artifact)}
                        >
                          <img
                            src={versionedArtifactContentUrl(
                              project.id,
                              line.taskId,
                              artifact.artifact_id,
                              taskUpdatedAt,
                            )}
                            alt={artifact.name}
                            onError={() =>
                              markArtifactUnavailable(line.taskId, artifact.artifact_id)
                            }
                          />
                        </button>
                      )}
                    <File size={14} />
                    <span>
                      {artifact.name}
                      {artifact.kept_filename && <em>Kept</em>}
                    </span>
                    {unavailable && <strong>{unavailableReason ?? "Preview unavailable"}</strong>}
                    {(!unavailable || revisionCandidate) && (
                      <div className="chat-artifact-actions">
                        {!unavailable && artifact.can_open && (
                          <button
                            type="button"
                            onClick={() => void openArtifact(line.taskId, artifact)}
                          >
                            <ExternalLink size={12} /> Open
                          </button>
                        )}
                        {!unavailable &&
                          artifact.can_download &&
                          (desktop ? (
                            <button
                              type="button"
                              onClick={() => void downloadArtifact(line.taskId, artifact)}
                            >
                              <Download size={12} /> Download
                            </button>
                          ) : (
                            <a
                              href={artifactUrl(
                                project.id,
                                line.taskId,
                                artifact.artifact_id,
                                "download",
                              )}
                              download={artifact.name}
                            >
                              <Download size={12} /> Download
                            </a>
                          ))}
                        {revisionCandidate && (
                          <button
                            type="button"
                            className="review-revision"
                            onClick={() => {
                              setRevisionDecisionError(null);
                              setRevisionReview({
                                taskId: line.taskId,
                                artifactId: artifact.artifact_id,
                              });
                            }}
                          >
                            Review revision
                          </button>
                        )}
                      </div>
                    )}
                    {shellError && (
                      <strong className="chat-artifact-shell-error" role="alert">
                        {shellError}
                      </strong>
                    )}
                  </div>
                );
              })}
              {line.role === "agent" && line.graphUpdate && (
                <GraphUpdateReceipt
                  update={line.graphUpdate}
                  taskId={line.taskId}
                  repairBusy={repairingTaskId === line.taskId}
                  repairDisabled={
                    readOnly || graphChangesDisabled || relatedActive || submitting || reviewPending
                  }
                  repairContinued={continuedTaskIds.has(line.taskId)}
                  repairError={repairErrors.get(line.taskId) ?? null}
                  onInspectTask={onInspectTask}
                  onOpenInbox={onOpenInbox}
                  onRepair={() => void repairGraphUpdate(line.taskId)}
                />
              )}
            </div>
          );
        })}
        {submitError && <div className="node-chat-line error">{submitError}</div>}
      </div>
      {!readOnly && (
        <div
          className={`chat-composer${draggingFiles ? " is-dragging-files" : ""}`}
          data-mode={mode}
          onDragEnter={(event) => {
            if (event.dataTransfer.types.includes("Files")) setDraggingFiles(true);
          }}
          onDragOver={(event) => {
            if (!event.dataTransfer.types.includes("Files")) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setDraggingFiles(false);
            }
          }}
          onDrop={(event) => {
            if (!event.dataTransfer.files.length) return;
            event.preventDefault();
            void addFiles(Array.from(event.dataTransfer.files));
          }}
        >
          <SkillPicker {...skills.props} />
          {composerHint && (
            <div className="chat-composer-hint" role="status">
              {composerHint}
            </div>
          )}
          {annotations.length > 0 && (
            <div className="chat-annotation-summary">
              <button
                className={`chat-annotation-count${annotationsOpen ? " is-open" : ""}`}
                type="button"
                aria-expanded={annotationsOpen}
                aria-controls={annotationPanelId}
                onClick={() => setAnnotationsOpen((open) => !open)}
              >
                <MessageCircle size={12} /> {annotations.length} annotation
                {annotations.length === 1 ? "" : "s"}
              </button>
            </div>
          )}
          {annotationsOpen && annotations.length > 0 && (
            <section
              className="chat-annotation-review"
              id={annotationPanelId}
              aria-label="Staged annotations"
            >
              <header>
                <strong>Annotations</strong>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Close annotations"
                  onClick={() => setAnnotationsOpen(false)}
                >
                  <X size={13} />
                </button>
              </header>
              <div className="chat-annotation-review-list">
                {annotations.map((annotation, index) => (
                  <article key={annotation.id}>
                    <blockquote>{annotation.selectedText}</blockquote>
                    <textarea
                      aria-label={`Comment for annotation ${index + 1}`}
                      disabled={submitting}
                      maxLength={MAX_CHAT_ANNOTATION_COMMENT_LENGTH}
                      value={annotation.comment}
                      onChange={(event) => updateAnnotation(annotation.id, event.target.value)}
                    />
                    <button
                      type="button"
                      aria-label={`Remove annotation ${index + 1}`}
                      disabled={submitting}
                      onClick={() => removeAnnotation(annotation.id)}
                    >
                      <X size={12} /> Remove
                    </button>
                  </article>
                ))}
              </div>
            </section>
          )}
          {artifactContext && (
            <div className="artifact-context-chip">
              <span>Artifact selections · {artifactContext.selections.length}</span>
              <button
                type="button"
                aria-label="Remove artifact selections"
                onClick={() => {
                  setArtifactContext(null);
                  removeStorage(artifactContextKey);
                  lastArtifactContextRef.current = null;
                }}
              >
                <X size={12} />
              </button>
            </div>
          )}
          {attachments.length > 0 && (
            <div className="chat-attachment-chips" aria-label="Files for this turn">
              {attachments.map((item) => (
                <div className={`chat-attachment-chip ${item.status}`} key={item.localId}>
                  {item.status === "preparing" ? (
                    <LoaderCircle className="spin" size={12} />
                  ) : (
                    <File size={12} />
                  )}
                  <span>
                    <strong>{item.file.name}</strong>
                    <small>
                      {item.status === "preparing"
                        ? "Preparing"
                        : item.status === "ready"
                          ? `Ready · ${formatBytes(item.file.size)}`
                          : item.error || "Could not prepare file"}
                    </small>
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove ${item.file.name}`}
                    onClick={() => removeAttachment(item)}
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
          <input
            ref={attachmentInputRef}
            className="visually-hidden"
            type="file"
            multiple
            accept={CHAT_ATTACHMENT_ACCEPT}
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? []);
              event.currentTarget.value = "";
              if (files.length) void addFiles(files);
            }}
          />
          <textarea
            ref={textareaRef}
            aria-label="Message"
            aria-keyshortcuts="Shift+Tab"
            disabled={awaitingSteerReceipt}
            value={message}
            onChange={(event) => {
              if (dictating) stopDictation(true);
              updateMessage(event.target.value);
            }}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files);
              if (!files.length) return;
              event.preventDefault();
              void addFiles(files);
            }}
            onKeyDown={(event) => {
              if (skills.handleKeyDown(event)) return;
              if (isConversationModeShortcut(event.key, event.shiftKey)) {
                if (presentation !== "workspace") {
                  event.preventDefault();
                  toggleMode();
                }
                return;
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <div className="chat-send">
            <div className="chat-composer-tools">
              <button
                className="icon-button chat-add-file"
                type="button"
                aria-label="Add files"
                disabled={
                  attachments.length >= MAX_CHAT_ATTACHMENTS ||
                  attachmentsPreparing ||
                  submitting ||
                  awaitingSteerReceipt
                }
                onClick={() => attachmentInputRef.current?.click()}
              >
                <Plus size={16} />
              </button>
              <div className="chat-mode-toggle" role="group" aria-label="Conversation mode">
                {(["discuss", "work"] as const).map((option) => (
                  <button
                    type="button"
                    className={option}
                    aria-pressed={mode === option}
                    title={MODE_HINTS[option]}
                    disabled={Boolean(steeringTask)}
                    onClick={() => selectMode(option)}
                    key={option}
                  >
                    {modeLabel(option)}
                  </button>
                ))}
              </div>
              <WorktreeControls
                key={`${project.id}:${chatId}`}
                state={worktree.state}
                error={worktree.error}
                chosen={worktree.chosen}
                disabled={Boolean(
                  relatedActive || pausedAttempt || submitting || reviewPending || repairingTaskId,
                )}
                onChoose={worktree.choose}
                onIntegrate={integrateWorktree}
                onRemove={worktree.remove}
                onPreviewRemove={worktree.previewRemoval}
                onRefresh={worktree.refresh}
              />
              {computeConnections.length > 0 && (
                <div className="chat-compute-picker">
                  <button
                    className="chat-compute-trigger"
                    type="button"
                    aria-expanded={computeMenuOpen}
                    onClick={() => setComputeMenuOpen((open) => !open)}
                  >
                    <Cpu size={13} />
                    Compute
                    {computeState.ids.length ? <strong>{computeState.ids.length}</strong> : null}
                    <ChevronUp size={12} />
                  </button>
                  {computeMenuOpen ? (
                    <fieldset className="chat-compute-menu" aria-label="Compute connections">
                      {computeConnections.map((connection) => {
                        const selected = computeState.ids.includes(connection.id);
                        const probe = project.compute_status?.[config.run_on]?.[connection.id];
                        const presentation = computeProbePresentation(probe);
                        return (
                          <label
                            aria-label={`${connection.name}, ${presentation.label}`}
                            key={connection.id}
                          >
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={() => {
                                setComputeState((current) => ({
                                  ids: selected
                                    ? current.ids.filter((id) => id !== connection.id)
                                    : [...current.ids, connection.id],
                                  pinned: true,
                                }));
                                setSubmitError(null);
                              }}
                            />
                            <span
                              className={`chat-compute-dot ${presentation.tone}`}
                              aria-hidden="true"
                            />
                            <strong>{connection.name}</strong>
                          </label>
                        );
                      })}
                    </fieldset>
                  ) : null}
                </div>
              )}
            </div>
            <div className="chat-send-actions">
              {desktop && (
                <button
                  className={`icon-button chat-dictation-button${dictating ? " recording" : ""}`}
                  type="button"
                  aria-label={dictating ? "Stop dictation" : "Start dictation"}
                  aria-pressed={dictating}
                  title={dictationError || (dictating ? "Stop dictation" : "Dictate")}
                  disabled={submitting}
                  onClick={() => void toggleDictation()}
                >
                  {dictating ? <MicOff size={15} /> : <Mic size={15} />}
                </button>
              )}
              <button
                className="icon-button primary chat-send-button"
                disabled={
                  !assembleChatTurn(message, annotations) ||
                  !annotationsComplete ||
                  submitting ||
                  (steeringTask
                    ? attachments.length > 0
                    : attachmentsUnready ||
                      relatedActive ||
                      Boolean(pausedAttempt) ||
                      Boolean(repairingTaskId) ||
                      reviewPending ||
                      scope.length === 0 ||
                      !providerReady)
                }
                onClick={() => void send()}
                aria-label={
                  steeringTask ? steeringTask.steer_action_label : `Start ${modeLabel(mode)} turn`
                }
              >
                <Send size={15} />
              </button>
            </div>
            {dictationError && (
              <span className="chat-dictation-error" role="alert">
                {dictationError}
              </span>
            )}
          </div>
        </div>
      )}
      {revisionReview &&
        revisionReviewTask &&
        revisionReviewArtifact &&
        revisionReviewCandidate && (
          <div
            className="artifact-revision-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget && !revisionDecision) {
                setRevisionReview(null);
              }
            }}
          >
            <section
              ref={revisionDialogRef}
              className="artifact-revision-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="artifact-revision-title"
              tabIndex={-1}
            >
              <header>
                <div>
                  <span>Pending revision</span>
                  <h2 id="artifact-revision-title">{revisionReviewArtifact.name}</h2>
                </div>
                <button
                  ref={revisionCloseRef}
                  type="button"
                  className="icon-button"
                  aria-label="Close revision review"
                  disabled={Boolean(revisionDecision)}
                  onClick={() => setRevisionReview(null)}
                >
                  <X size={16} />
                </button>
              </header>
              <div className="artifact-revision-compare">
                <figure>
                  <figcaption>Current</figcaption>
                  <iframe
                    title={`Current ${revisionReviewArtifact.name}`}
                    src={versionedArtifactContentUrl(
                      project.id,
                      revisionReview.taskId,
                      revisionReviewArtifact.artifact_id,
                      revisionReviewTask.updated_at,
                    )}
                    sandbox="allow-scripts"
                  />
                </figure>
                <figure>
                  <figcaption>Candidate</figcaption>
                  <iframe
                    title={`Candidate ${revisionReviewArtifact.name}`}
                    src={artifactRevisionContentUrl(
                      project.id,
                      revisionReviewCandidate.candidate_id,
                    )}
                    sandbox="allow-scripts"
                  />
                </figure>
              </div>
              {revisionReviewCandidate.diagnostic && (
                <strong className="artifact-revision-error" role="alert">
                  {revisionReviewCandidate.diagnostic}
                </strong>
              )}
              {revisionDecisionError && (
                <strong className="artifact-revision-error" role="alert">
                  {revisionDecisionError}
                </strong>
              )}
              <footer>
                <button
                  type="button"
                  className="button secondary"
                  disabled={Boolean(revisionDecision) || !revisionReviewCandidate.can_reject}
                  onClick={() => void decideRevision("reject")}
                >
                  {revisionDecision === "reject" ? "Rejecting…" : "Reject"}
                </button>
                <button
                  type="button"
                  className="button primary"
                  disabled={Boolean(revisionDecision) || !revisionReviewCandidate.can_accept}
                  onClick={() => void decideRevision("accept")}
                >
                  {revisionDecision === "accept" ? "Accepting…" : "Accept revision"}
                </button>
              </footer>
            </section>
          </div>
        )}
      {annotationComposer && typeof document !== "undefined"
        ? createPortal(
            <form
              ref={annotationComposerRef}
              className="chat-annotation-composer"
              aria-label={
                annotationComposer.step === "select" ? "Select answer text" : "Add annotation"
              }
              style={
                {
                  left: annotationComposer.position?.left,
                  top: annotationComposer.position?.top,
                  visibility: annotationComposer.position ? undefined : "hidden",
                  ...(annotationViewport
                    ? {
                        "--chat-annotation-viewport-left": `${annotationViewport.left}px`,
                        "--chat-annotation-viewport-top": `${annotationViewport.top}px`,
                        "--chat-annotation-viewport-width": `${annotationViewport.width}px`,
                        "--chat-annotation-viewport-height": `${annotationViewport.height}px`,
                        "--chat-annotation-viewport-right": `${annotationViewport.right}px`,
                        "--chat-annotation-viewport-bottom": `${annotationViewport.bottom}px`,
                      }
                    : {}),
                } as CSSProperties
              }
              onSubmit={(event) => {
                event.preventDefault();
                if (submitting) return;
                if (annotationComposer.step === "select") continueKeyboardAnnotation();
                else stageAnnotation();
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  dismissAnnotationComposer(true);
                }
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  if (annotationComposer.step === "select") continueKeyboardAnnotation();
                  else stageAnnotation();
                }
              }}
            >
              <header>
                <strong>
                  {annotationComposer.step === "select" ? "Select text" : "Add annotation"}
                </strong>
                <button
                  className="icon-button"
                  type="button"
                  aria-label="Cancel annotation"
                  disabled={submitting}
                  onClick={() => dismissAnnotationComposer(true)}
                >
                  <X size={14} />
                </button>
              </header>
              {annotationComposer.step === "select" ? (
                <>
                  <textarea
                    className="chat-annotation-source"
                    ref={annotationSelectionRef}
                    aria-label="Select answer text"
                    disabled={submitting}
                    readOnly
                    defaultValue={annotationComposer.answerText}
                    onSelect={(event) => updateKeyboardAnnotationSelection(event.currentTarget)}
                  />
                  {annotationComposer.selectedText.length > MAX_CHAT_ANNOTATION_TEXT_LENGTH && (
                    <strong className="chat-annotation-error" role="alert">
                      Select at most {MAX_CHAT_ANNOTATION_TEXT_LENGTH.toLocaleString()} characters.
                    </strong>
                  )}
                  <button
                    className="button compact primary"
                    type="submit"
                    disabled={
                      submitting ||
                      !annotationComposer.selectedText ||
                      annotationComposer.selectedText.length > MAX_CHAT_ANNOTATION_TEXT_LENGTH
                    }
                  >
                    Comment on selection
                  </button>
                </>
              ) : (
                <>
                  <blockquote>{annotationComposer.selectedText}</blockquote>
                  <textarea
                    ref={annotationCommentRef}
                    aria-label="Comment"
                    disabled={submitting}
                    maxLength={MAX_CHAT_ANNOTATION_COMMENT_LENGTH}
                    value={annotationComment}
                    onChange={(event) => setAnnotationComment(event.target.value)}
                    onKeyDown={(event) => {
                      // Plain Enter only: Shift+Enter inserts a newline and the
                      // form's own modifier+Enter shortcut stages the comment.
                      if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey)
                        return;
                      event.preventDefault();
                      if (submitting || !annotationComment.trim()) return;
                      event.currentTarget.form?.requestSubmit();
                    }}
                  />
                  <button
                    className="button compact primary"
                    type="submit"
                    disabled={submitting || !annotationComment.trim()}
                  >
                    Add comment
                  </button>
                </>
              )}
            </form>,
            document.body,
          )
        : null}
    </div>
  );
}

function InlineTaskProgress({ task }: { task: AgentTask | null }) {
  const label = task
    ? task.status_message || `${taskKindLabel(task.kind)} is running`
    : "Starting task";
  return (
    <>
      <span className="chat-task-live" role="status" aria-live="polite" aria-atomic="true">
        {label}
      </span>
      <details className="chat-task-activity">
        <summary>
          <LoaderCircle className="spin" size={12} />
          <span>Activity</span>
        </summary>
        <div className="chat-task-inline running">
          <span>{label}</span>
        </div>
      </details>
    </>
  );
}

function InlinePausedTask({
  task,
  disabled,
  onResume,
  onRetry,
}: {
  task: AgentTask;
  disabled: boolean;
  onResume: () => void;
  onRetry: () => void;
}) {
  return (
    <div className="chat-task-inline paused" role="status" aria-label="Agent task paused">
      <span>{task.status_message}</span>
      <button
        type="button"
        className="button compact primary"
        disabled={disabled}
        onClick={onResume}
      >
        <Play size={11} /> Resume
      </button>
      <button
        type="button"
        className="button compact secondary"
        disabled={disabled}
        onClick={onRetry}
      >
        <RotateCcw size={11} /> Retry
      </button>
    </div>
  );
}

function GraphUpdateReceipt({
  update,
  taskId,
  repairBusy,
  repairDisabled,
  repairContinued,
  repairError,
  onInspectTask,
  onOpenInbox,
  onRepair,
}: {
  update: GraphUpdateResult;
  taskId: string;
  repairBusy: boolean;
  repairDisabled: boolean;
  repairContinued: boolean;
  repairError: string | null;
  onInspectTask: (taskId: string) => void;
  onOpenInbox: () => void;
  onRepair: () => void;
}) {
  if (update.status === "none") return null;
  const proposalCount = update.proposal_ids.length;
  return (
    <div className={`chat-graph-receipt ${update.status}`}>
      <div className="chat-graph-receipt-actions">
        {update.status === "applied" && (
          <button type="button" onClick={() => onInspectTask(taskId)}>
            <History size={12} />
            {update.applied_revision === null
              ? "Graph updated"
              : `Graph updated · r${update.applied_revision}`}
          </button>
        )}
        {update.status === "rejected" && (
          <strong>
            <AlertTriangle size={12} /> Graph update rejected
          </strong>
        )}
        {update.status === "applied" && proposalCount > 0 && (
          <button type="button" onClick={onOpenInbox}>
            <Inbox size={12} />
            {proposalCount} proposal{proposalCount === 1 ? "" : "s"} sent to Inbox
          </button>
        )}
        {update.status === "rejected" && update.repairable && !repairContinued && (
          <button type="button" disabled={repairBusy || repairDisabled} onClick={onRepair}>
            <RotateCcw className={repairBusy ? "spin" : undefined} size={12} />
            Repair graph update
          </button>
        )}
      </div>
      {update.change_summary.length > 0 && (
        <ul className="chat-graph-change-summary">
          {update.change_summary.map((item, index) => (
            <li key={`${index}:${item}`}>{item}</li>
          ))}
        </ul>
      )}
      {update.status === "rejected" && update.validation_messages.length > 0 && (
        <ul className="chat-graph-validation">
          {update.validation_messages.map((item, index) => (
            <li key={`${index}:${item}`}>{item}</li>
          ))}
        </ul>
      )}
      {repairError && (
        <strong className="chat-graph-repair-error" role="alert">
          {repairError}
        </strong>
      )}
    </div>
  );
}

function modeLabel(mode: ConversationMode): "Discuss" | "Work" {
  return mode === "discuss" ? "Discuss" : "Work";
}

/** Say what each mode is allowed to do, where the human commits to one.
 *
 * Capability is fixed in code; this only describes it. Discuss holds no graph or
 * filesystem authority, so the difference is worth stating at the control rather
 * than leaving two bare verbs to be learned by consequence.
 */
const MODE_HINTS: Record<ConversationMode, string> = {
  discuss: "Discuss: reads and answers only. Nothing is written to the repository or the graph.",
  work: "Work: may edit files in the run's write roots and propose a graph patch.",
};

const MAX_CHAT_ATTACHMENTS = 8;
const MAX_CHAT_ATTACHMENT_BYTES = 16 * 1024 * 1024;
const MAX_CHAT_ATTACHMENT_TOTAL_BYTES = 32 * 1024 * 1024;
const CHAT_ATTACHMENT_CLIENT_KEY = "rcp:chat-attachment-client";
const CHAT_ATTACHMENT_EXTENSIONS = new Set([
  "c",
  "cc",
  "cpp",
  "cs",
  "css",
  "csv",
  "fish",
  "go",
  "h",
  "hpp",
  "htm",
  "html",
  "java",
  "js",
  "json",
  "jsx",
  "kt",
  "kts",
  "lua",
  "markdown",
  "md",
  "mjs",
  "mm",
  "php",
  "py",
  "r",
  "rb",
  "rs",
  "scala",
  "sh",
  "sql",
  "svg",
  "swift",
  "toml",
  "ts",
  "tsv",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
  "zsh",
]);
const CHAT_ATTACHMENT_BINARY_EXTENSIONS = new Set(["jpeg", "jpg", "pdf", "png", "webp"]);
const CHAT_ATTACHMENT_ACCEPT = [
  ".txt",
  ".md",
  ".csv",
  ".tsv",
  ".json",
  ".html",
  ".htm",
  ".svg",
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ...[...CHAT_ATTACHMENT_EXTENSIONS].map((extension) => `.${extension}`),
].join(",");

function validateChatAttachment(file: File, currentTotal: number): string | null {
  const extension = file.name.split(".").at(-1)?.toLowerCase() ?? "";
  if (
    !CHAT_ATTACHMENT_BINARY_EXTENSIONS.has(extension) &&
    !CHAT_ATTACHMENT_EXTENSIONS.has(extension)
  ) {
    return "Unsupported file type";
  }
  if (file.size > MAX_CHAT_ATTACHMENT_BYTES) return "File exceeds 16 MiB";
  if (currentTotal + file.size > MAX_CHAT_ATTACHMENT_TOTAL_BYTES) {
    return "Turn exceeds 32 MiB total";
  }
  return null;
}

function chatAttachmentClientId(): string {
  try {
    const current = sessionStorage.getItem(CHAT_ATTACHMENT_CLIENT_KEY);
    if (current) return current;
    const created = crypto.randomUUID();
    sessionStorage.setItem(CHAT_ATTACHMENT_CLIENT_KEY, created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MiB`;
}

function clearDictationTimer(ref: React.MutableRefObject<number | null>): void {
  if (ref.current !== null) window.clearTimeout(ref.current);
  ref.current = null;
}

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

function removeStorage(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {}
}

function chatAnnotationsStorageKey(projectId: string, chatId: string): string {
  return `rcp:chat-annotations:${encodeURIComponent(projectId)}:${encodeURIComponent(chatId)}`;
}

function readStagedChatAnnotations(key: string): StagedChatAnnotation[] {
  try {
    return parseStagedChatAnnotations(sessionStorage.getItem(key));
  } catch {
    return [];
  }
}

function writeSessionStorage(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {}
}

function removeSessionStorage(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {}
}

function withMapValue(map: Map<string, string>, key: string, value: string): Map<string, string> {
  const next = new Map(map);
  next.set(key, value);
  return next;
}

function withoutMapKey(map: Map<string, string>, key: string): Map<string, string> {
  if (!map.has(key)) return map;
  const next = new Map(map);
  next.delete(key);
  return next;
}

async function resourceIsAvailable(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { method: "HEAD" });
    return response.ok;
  } catch {
    return false;
  }
}
