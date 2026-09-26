import { ReleaseCheckRow } from "../components/UpdateNotice";
import type { UpdateNotice } from "../types";
import {
  BookOpen,
  Check,
  Cpu,
  GitBranch,
  HardDrive,
  LoaderCircle,
  Minus,
  Plus,
  RotateCcw,
  ScanSearch,
  Save,
  Server,
  Sparkles,
  Trash2,
  TriangleAlert,
  Type,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, clearAllProjectCaches, clearProjectCaches } from "../api";
import { computeProbePresentation } from "../compute";
import { ProjectMembers } from "../components/ProjectMembers";
import { ProviderLogins } from "../components/ProviderLogins";
import { ServerSettings } from "../components/ServerSettings";
import { EMPTY_SKILL_SELECTION } from "../skillPicker";
import { AgentConfigControls, profileRunConfig } from "../components/AgentConfigControls";
import { AgentUsageWidgets } from "../components/AgentUsageWidgets";
import { SkillPackageInspector } from "../components/SkillPackageInspector";
import {
  computeConnectionNeedsSave,
  computeProbeConfigurationChanged,
  deserializeSettingsDraft,
  machineComputeFrom,
  machineComputeUpdates,
  type MachineComputeSettings,
  machineProviderPathUpdates,
  machineProviderPathsFrom,
  mergeAgentProfiles,
  mergeMachineProviderPaths,
  serializeSettingsDraft,
  settingsDraftStorageKey,
  settingsFingerprint,
  type MachineProviderPaths,
} from "../settingsDraft";
import { TEXT_SCALE_MAX, TEXT_SCALE_MIN } from "../textScale";
import type { ProjectReadinessRetention } from "../hooks/projectSession";
import type {
  AgentExecutionProfile,
  AgentProfileSettings,
  AgentUsageSnapshot,
  CacheMetric,
  ComputeConnection,
  MachineComputeConfig,
  ProjectCacheMetrics,
  ProjectSettingsRequest,
  IdentityResponse,
  ProjectSnapshot,
  ProviderId,
  ProviderPathResolution,
  ProviderReadiness,
  SkillDefaults,
} from "../types";

interface Props {
  updateNotice?: UpdateNotice | null;
  apiBase: string;
  project: ProjectSnapshot;
  identity: IdentityResponse | null;
  onLeftProject: () => void;
  usage: AgentUsageSnapshot | null;
  onRefreshUsage: () => Promise<void>;
  cacheClearDisabled: boolean;
  writesDisabled?: boolean;
  onSaved: (project: ProjectSnapshot, retention?: ProjectReadinessRetention) => void;
  onCacheMetricsChange: (metrics: ProjectCacheMetrics) => void;
  onRefreshReadiness: () => Promise<void>;
  readinessRequest?: {
    pending: boolean;
    providerError: string | null;
    computeError: string | null;
  };
  /** Text size is a desktop webview zoom. */
  showTextScale: boolean;
  spaceKind: "personal" | "team";
  onMovePersonalProjectToTeam?: (sourceProjectId: string) => void;
  textScale: number;
  onTextScaleChange: (action: "decrease" | "increase" | "reset") => void;
}

export function publishCacheMetrics(
  metrics: ProjectCacheMetrics,
  setVisibleMetrics: (metrics: ProjectCacheMetrics) => void,
  onCacheMetricsChange: (metrics: ProjectCacheMetrics) => void,
) {
  setVisibleMetrics(metrics);
  onCacheMetricsChange(metrics);
}

export function showClearAllCachesWarning(clearStatus: () => void, openWarning: () => void) {
  clearStatus();
  openWarning();
}

const executionProfiles: Array<{ id: AgentExecutionProfile; label: string }> = [
  { id: "seed", label: "Seed" },
  { id: "refresh", label: "Refresh" },
  { id: "node_chat", label: "Node chat" },
  { id: "project_chat", label: "Project chat" },
  { id: "paper_coach", label: "Paper coach" },
  { id: "orchestrator", label: "Orchestrator" },
];

function profilesFrom(
  project: ProjectSnapshot,
): Record<AgentExecutionProfile, AgentProfileSettings> {
  const canonicalMachine =
    project.repositories.find((repository) => repository.alias === project.state_repository)
      ?.machine ?? project.run_on;
  return Object.fromEntries(
    executionProfiles.map(({ id }) => {
      const storedProfile =
        id === "orchestrator"
          ? (project.agent_profiles.orchestrator ?? project.agent_profiles.refresh)
          : project.agent_profiles[id];
      const settings = { ...profileRunConfig(storedProfile), runtime: storedProfile.runtime };
      return [id, id === "paper_coach" ? settings : { ...settings, run_on: canonicalMachine }];
    }),
  ) as Record<AgentExecutionProfile, AgentProfileSettings>;
}

type SkillCatalogEntry = ProjectSnapshot["skill_catalog"][number];

function skillDefaultsFrom(project: ProjectSnapshot): SkillDefaults {
  return project.skill_defaults ?? EMPTY_SKILL_SELECTION;
}

function skillCatalogFrom(project: ProjectSnapshot): SkillCatalogEntry[] {
  return project.skill_catalog ?? [];
}

/** The staged edits for this project, or the manifest's values when none exist. */
function stagedOrSaved(project: ProjectSnapshot) {
  const saved = {
    scope: project.default_run_truth_scope,
    autoResearchInvocationCeiling: project.default_auto_research_invocation_ceiling,
    profiles: profilesFrom(project),
    providerPaths: machineProviderPathsFrom(project.machines),
    machineComputeEdits: {} as MachineComputeSettings,
    skillDefaults: skillDefaultsFrom(project),
    computeConnections: project.compute_connections ?? [],
  };
  let staged: ReturnType<typeof deserializeSettingsDraft> = null;
  try {
    staged = deserializeSettingsDraft(localStorage.getItem(settingsDraftStorageKey(project.id)));
  } catch {
    // A staged draft is a convenience; storage failures fall back to the manifest.
  }
  if (!staged) return saved;
  // Merge over the manifest's profiles so a surface added since the draft was
  // written is still present.
  return {
    scope: staged.scope,
    autoResearchInvocationCeiling:
      staged.autoResearchInvocationCeiling ?? saved.autoResearchInvocationCeiling,
    profiles: mergeAgentProfiles(saved.profiles, staged.profiles),
    providerPaths: mergeMachineProviderPaths(saved.providerPaths, staged.providerPaths),
    machineComputeEdits: staged.machineComputeEdits ?? {},
    skillDefaults: staged.skillDefaults ?? saved.skillDefaults,
    computeConnections: saved.computeConnections,
  };
}

export function ProjectSettings({
  updateNotice = null,
  apiBase,
  project,
  identity,
  onLeftProject,
  usage,
  onRefreshUsage,
  cacheClearDisabled,
  writesDisabled = false,
  onSaved,
  onCacheMetricsChange,
  onRefreshReadiness,
  readinessRequest,
  showTextScale,
  spaceKind,
  onMovePersonalProjectToTeam,
  textScale,
  onTextScaleChange,
}: Props) {
  const skillCatalog = skillCatalogFrom(project);
  const savedSkillDefaults = skillDefaultsFrom(project);
  const restoredSettings = useMemo(() => stagedOrSaved(project), [project.id]);
  const [scope, setScope] = useState<string[]>(() => restoredSettings.scope);
  const [autoResearchInvocationCeiling, setAutoResearchInvocationCeiling] = useState(
    () => restoredSettings.autoResearchInvocationCeiling,
  );
  const [profiles, setProfiles] = useState<Record<AgentExecutionProfile, AgentProfileSettings>>(
    () => restoredSettings.profiles,
  );
  const [providerPaths, setProviderPaths] = useState<MachineProviderPaths>(
    () => restoredSettings.providerPaths,
  );
  const [machineComputeEdits, setMachineComputeEdits] = useState<MachineComputeSettings>(
    () => restoredSettings.machineComputeEdits,
  );
  const machineCompute = { ...machineComputeFrom(project.machines), ...machineComputeEdits };
  // A return to the same project is a new visit: requests from the previous
  // visit must not overwrite the restored form or publish into another view.
  const requestOwner = useMemo(() => ({ projectId: project.id }), [project.id]);
  const currentRequestOwner = useRef<typeof requestOwner | null>(requestOwner);
  currentRequestOwner.current = requestOwner;
  const requestIsCurrent = () => currentRequestOwner.current === requestOwner;
  const [skillDefaults, setSkillDefaults] = useState<SkillDefaults>(
    () => restoredSettings.skillDefaults,
  );
  const [computeConnections, setComputeConnections] = useState<ComputeConnection[]>(
    () => restoredSettings.computeConnections,
  );
  const [inspectedPackage, setInspectedPackage] = useState<SkillCatalogEntry | null>(null);
  const [saving, setSaving] = useState(false);
  const [clearingCaches, setClearingCaches] = useState(false);
  const [clearAllCachesOpen, setClearAllCachesOpen] = useState(false);
  const [clearingAllCaches, setClearingAllCaches] = useState(false);
  const [resolvingProvider, setResolvingProvider] = useState<string | null>(null);
  const [cacheMetrics, setCacheMetrics] = useState(project.cache_metrics);
  const [status, setStatus] = useState<{ kind: "saved" | "error"; text: string } | null>(null);

  useEffect(() => {
    currentRequestOwner.current = requestOwner;
    return () => {
      if (currentRequestOwner.current === requestOwner) currentRequestOwner.current = null;
    };
  }, [requestOwner]);

  // Reload the form only when the project itself changes. Keying this on the
  // whole snapshot discarded in-progress edits every time an unrelated refresh
  // — a finished background run, a cache clear — handed down a new object
  // carrying byte-identical settings.
  useEffect(() => {
    setScope(restoredSettings.scope);
    setAutoResearchInvocationCeiling(restoredSettings.autoResearchInvocationCeiling);
    setProfiles(restoredSettings.profiles);
    setProviderPaths(restoredSettings.providerPaths);
    setMachineComputeEdits(restoredSettings.machineComputeEdits);
    setSkillDefaults(restoredSettings.skillDefaults);
    setComputeConnections(restoredSettings.computeConnections);
    setSaving(false);
    setClearingCaches(false);
    setClearAllCachesOpen(false);
    setClearingAllCaches(false);
    setResolvingProvider(null);
    setInspectedPackage(null);
    setStatus(null);
  }, [restoredSettings]);

  // Cache metrics are server-owned, so they follow every snapshot.
  useEffect(() => {
    setCacheMetrics(project.cache_metrics);
  }, [project.cache_metrics]);

  useEffect(() => {
    void onRefreshUsage();
  }, [onRefreshUsage]);

  const baseline = useMemo(
    () =>
      settingsFingerprint({
        scope: project.default_run_truth_scope,
        autoResearchInvocationCeiling: project.default_auto_research_invocation_ceiling,
        profiles: profilesFrom(project),
        providerPaths: machineProviderPathsFrom(project.machines),
        machineCompute: machineComputeFrom(project.machines),
        skillDefaults: skillDefaultsFrom(project),
        computeConnections: project.compute_connections ?? [],
      }),
    [project],
  );
  const current = settingsFingerprint({
    scope,
    autoResearchInvocationCeiling,
    profiles,
    providerPaths,
    machineCompute,
    skillDefaults,
    computeConnections,
  });
  const dirty = current !== baseline;
  const autoResearchInvocationCeilingIsValid =
    Number.isSafeInteger(autoResearchInvocationCeiling) && autoResearchInvocationCeiling >= 1;

  // Stage machine settings alongside provider paths. Compute connection metadata
  // stays in memory until Save; clearing a clean form drops the staged copy.
  useEffect(() => {
    const key = settingsDraftStorageKey(project.id);
    try {
      if (dirty) {
        localStorage.setItem(
          key,
          serializeSettingsDraft({
            version: 4,
            scope,
            autoResearchInvocationCeiling,
            profiles,
            providerPaths,
            machineComputeEdits: machineComputeUpdates(
              machineComputeFrom(project.machines),
              machineComputeEdits,
            ),
            skillDefaults,
          }),
        );
      } else {
        localStorage.removeItem(key);
      }
    } catch {
      // Staging edits is a convenience; storage failures must not affect Settings.
    }
  }, [dirty, current, project.id]);
  const machineByAlias = Object.fromEntries(
    project.machines.map((machine) => [machine.alias, machine]),
  );
  const providerCatalog = Object.values(project.providers).sort((left, right) =>
    (left.label || left.provider).localeCompare(right.label || right.provider),
  );
  const workflowCatalog = skillCatalog.filter((entry) => entry.kind === "workflow");
  const directSkillCatalog = skillCatalog.filter((entry) => entry.kind === "skill");
  const executionMachines = Array.from(
    new Set(Object.values(profiles).map((profile) => profile.run_on)),
  );
  const computeConnectionsAreValid = computeConnections.every(
    (connection) =>
      connection.name.trim().length > 0 &&
      (connection.kind === "local" || connection.ssh_target.trim().length > 0),
  );
  const computeConfigurationIsDirty = computeProbeConfigurationChanged(
    {
      connections: project.compute_connections ?? [],
      executionMachines: Object.values(profilesFrom(project)).map((profile) => profile.run_on),
    },
    { connections: computeConnections, executionMachines },
  );

  const toggleRepository = (alias: string) => {
    setStatus(null);
    setScope((currentScope) => {
      if (!currentScope.includes(alias)) return [...currentScope, alias];
      if (currentScope.length === 1) {
        setStatus({ kind: "error", text: "Keep at least one repository in the default read set." });
        return currentScope;
      }
      return currentScope.filter((item) => item !== alias);
    });
  };

  const toggleSkillDefault = (entry: SkillCatalogEntry) => {
    setStatus(null);
    setSkillDefaults((currentDefaults) => {
      const field = entry.kind === "workflow" ? "workflow_ids" : "skill_ids";
      const selected = currentDefaults[field];
      return {
        ...currentDefaults,
        [field]: selected.includes(entry.id)
          ? selected.filter((id) => id !== entry.id)
          : [...selected, entry.id],
      };
    });
  };

  const renderSkillGroup = (title: string, entries: SkillCatalogEntry[], selectedIds: string[]) => (
    <div className="skill-card-group" role="group" aria-label={title}>
      <h3>{title}</h3>
      <div className="skill-card-grid">
        {entries.map((entry) => {
          const selected = selectedIds.includes(entry.id);
          return (
            <div
              className={selected ? "skill-card selected" : "skill-card"}
              key={`${entry.kind}:${entry.id}`}
            >
              <button
                type="button"
                className="skill-card-select"
                aria-pressed={selected}
                disabled={writesDisabled}
                onClick={() => toggleSkillDefault(entry)}
              >
                <span className="settings-check" aria-hidden="true">
                  {selected && <Check size={12} />}
                </span>
                <span>{entry.label}</span>
              </button>
              <button
                type="button"
                className="icon-button skill-card-inspect"
                aria-label={`Inspect ${entry.label}`}
                onClick={() => setInspectedPackage(entry)}
              >
                <BookOpen size={13} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );

  const reset = () => {
    setScope(project.default_run_truth_scope);
    setAutoResearchInvocationCeiling(project.default_auto_research_invocation_ceiling);
    setProfiles(profilesFrom(project));
    setProviderPaths(machineProviderPathsFrom(project.machines));
    setMachineComputeEdits({});
    setSkillDefaults(savedSkillDefaults);
    setComputeConnections(project.compute_connections ?? []);
    setStatus(null);
  };

  const save = async () => {
    if (
      !dirty ||
      saving ||
      writesDisabled ||
      !autoResearchInvocationCeilingIsValid ||
      !computeConnectionsAreValid
    )
      return;
    setSaving(true);
    setStatus(null);
    const body: ProjectSettingsRequest = {
      default_run_truth_scope: scope,
      default_auto_research_invocation_ceiling: autoResearchInvocationCeiling,
      agent_profiles: profiles,
      skill_defaults: skillDefaults,
      compute_connections: computeConnections,
    };
    const pathUpdates = machineProviderPathUpdates(
      machineProviderPathsFrom(project.machines),
      providerPaths,
    );
    if (pathUpdates) body.machine_provider_paths = pathUpdates;
    const computeUpdates = machineComputeUpdates(
      machineComputeFrom(project.machines),
      machineCompute,
    );
    if (computeUpdates) body.machine_compute = computeUpdates;
    try {
      const saved = await api<ProjectSnapshot>(`${apiBase}/settings`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (!requestIsCurrent()) return;
      setProviderPaths((currentPaths) =>
        currentPaths === providerPaths ? machineProviderPathsFrom(saved.machines) : currentPaths,
      );
      setMachineComputeEdits({});
      setComputeConnections((currentConnections) =>
        currentConnections === computeConnections ? saved.compute_connections : currentConnections,
      );
      // The save response intentionally carries no live probe. Preserve each
      // readiness slice whose own inputs this save left alone.
      onSaved(saved, {
        provider: pathUpdates === undefined,
        compute: !computeConfigurationIsDirty,
      });
      try {
        await onRefreshReadiness();
        if (!requestIsCurrent()) return;
        setStatus({ kind: "saved", text: "Saved." });
      } catch (readinessError) {
        if (!requestIsCurrent()) return;
        setStatus({
          kind: "error",
          text: `Saved, but readiness refresh failed: ${readinessError instanceof Error ? readinessError.message : String(readinessError)}`,
        });
      }
    } catch (caught) {
      if (!requestIsCurrent()) return;
      setStatus({ kind: "error", text: caught instanceof Error ? caught.message : String(caught) });
    } finally {
      if (requestIsCurrent()) setSaving(false);
    }
  };

  const updateMachineCompute = (alias: string, config: MachineComputeConfig | null) => {
    setMachineComputeEdits((currentEdits) => {
      const next = { ...currentEdits, [alias]: config };
      if (
        !machineComputeUpdates(
          { [alias]: machineByAlias[alias].compute ?? null },
          { [alias]: config },
        )
      )
        delete next[alias];
      return next;
    });
    setStatus(null);
  };

  const resolveProviderPath = async (machine: string, provider: ProviderId) => {
    const key = `${machine}:${provider}`;
    if (resolvingProvider || writesDisabled) return;
    setResolvingProvider(key);
    setStatus(null);
    try {
      const result = await api<ProviderPathResolution>(
        `${apiBase}/machines/${encodeURIComponent(machine)}/providers/${encodeURIComponent(provider)}/resolve`,
        { method: "POST" },
      );
      if (!requestIsCurrent()) return;
      setProviderPaths((currentPaths) =>
        currentPaths[machine]?.[provider] !== providerPaths[machine]?.[provider]
          ? currentPaths
          : {
              ...currentPaths,
              [result.machine]: {
                ...currentPaths[result.machine],
                [result.provider]: result.binary_path ?? "",
              },
            },
      );
      const coachMachine = project.agent_profiles.paper_coach.run_on;
      const resolvedProject: ProjectSnapshot = {
        ...result.project,
        provider_readiness: {
          ...project.provider_readiness,
          [result.machine]: {
            ...project.provider_readiness[result.machine],
            [result.provider]: result.readiness,
          },
        },
        providers:
          coachMachine === result.machine
            ? { ...project.providers, [result.provider]: result.readiness }
            : project.providers,
      };
      // A resolve invalidates provider readiness alone. Retaining the rendered
      // compute status keeps a compute probe that answers mid-resolve.
      onSaved(resolvedProject, { provider: false, compute: true });
      setStatus({
        kind: "saved",
        text: `${result.readiness.label || result.provider} resolved on ${result.machine}.`,
      });
    } catch (caught) {
      if (!requestIsCurrent()) return;
      setStatus({ kind: "error", text: caught instanceof Error ? caught.message : String(caught) });
    } finally {
      if (requestIsCurrent()) setResolvingProvider(null);
    }
  };

  const clearCaches = async () => {
    if (cacheClearDisabled || clearingCaches) return;
    setClearingCaches(true);
    setStatus(null);
    try {
      const metrics = await clearProjectCaches(apiBase);
      if (!requestIsCurrent()) return;
      publishCacheMetrics(metrics, setCacheMetrics, onCacheMetricsChange);
      setStatus({ kind: "saved", text: "Project cache cleared." });
    } catch (caught) {
      if (!requestIsCurrent()) return;
      setStatus({ kind: "error", text: caught instanceof Error ? caught.message : String(caught) });
    } finally {
      if (requestIsCurrent()) setClearingCaches(false);
    }
  };

  const clearEveryProjectCache = async () => {
    if (clearingAllCaches) return;
    setClearingAllCaches(true);
    setStatus(null);
    try {
      const metrics = await clearAllProjectCaches(project.id);
      if (!requestIsCurrent()) return;
      publishCacheMetrics(metrics, setCacheMetrics, onCacheMetricsChange);
      setClearAllCachesOpen(false);
      setStatus({ kind: "saved", text: "All project caches cleared." });
    } catch (caught) {
      if (!requestIsCurrent()) return;
      setStatus({ kind: "error", text: caught instanceof Error ? caught.message : String(caught) });
    } finally {
      if (requestIsCurrent()) setClearingAllCaches(false);
    }
  };

  return (
    <section className="settings-page">
      {spaceKind === "team" ? (
        <ServerSettings updateNotice={updateNotice} />
      ) : (
        <section className="settings-section">
          <ReleaseCheckRow notice={updateNotice} />
        </section>
      )}
      <AgentUsageWidgets usage={usage} providers={project.providers} />

      {showTextScale && (
        <section className="settings-section display-settings">
          <header>
            <span>
              <Type size={16} />
            </span>
            <h2>Display</h2>
            <div className="text-scale-controls" role="group" aria-label="Interface text size">
              <button
                className="icon-button"
                type="button"
                disabled={textScale <= TEXT_SCALE_MIN}
                onClick={() => onTextScaleChange("decrease")}
                aria-label="Decrease text size"
              >
                <Minus size={15} />
              </button>
              <button
                className="text-scale-value"
                type="button"
                onClick={() => onTextScaleChange("reset")}
                aria-label="Reset text size to 100 percent"
              >
                {textScale}%
              </button>
              <button
                className="icon-button"
                type="button"
                disabled={textScale >= TEXT_SCALE_MAX}
                onClick={() => onTextScaleChange("increase")}
                aria-label="Increase text size"
              >
                <Plus size={15} />
              </button>
            </div>
          </header>
        </section>
      )}
      {spaceKind === "personal" && onMovePersonalProjectToTeam ? (
        <section className="settings-section project-home-settings">
          <header>
            <span>
              <GitBranch size={16} />
            </span>
            <h2>Project home</h2>
          </header>
          <button
            className="button secondary"
            type="button"
            disabled={writesDisabled}
            onClick={() => onMovePersonalProjectToTeam(project.id)}
          >
            <Server size={14} /> Move to team space
          </button>
        </section>
      ) : null}
      <ProjectMembers
        key={project.id}
        projectId={project.id}
        identity={identity}
        api={api}
        onLeft={onLeftProject}
      />
      <article className="settings-section boundary-settings">
        <header>
          <span>
            <GitBranch size={16} />
          </span>
          <h2>Project boundary</h2>
        </header>
        <div className="settings-repositories">
          {project.repositories.map((repository) => {
            const machine = machineByAlias[repository.machine];
            const selected = scope.includes(repository.alias);
            const canonical = repository.alias === project.state_repository;
            return (
              <label
                className={selected ? "settings-repository selected" : "settings-repository"}
                key={repository.alias}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={writesDisabled}
                  onChange={() => toggleRepository(repository.alias)}
                />
                <span className="settings-check">{selected && <Check size={12} />}</span>
                <span className="settings-repository-copy">
                  <strong>{repository.alias}</strong>
                  <span className="settings-repository-path">
                    {machine?.host ? `${machine.host}:${repository.path}` : repository.path}
                  </span>
                </span>
                <span className="settings-repository-meta">
                  <Server size={12} /> {machine?.host ? repository.machine : "local"}
                  {canonical && <em>canonical state</em>}
                </span>
              </label>
            );
          })}
        </div>
      </article>

      <section className="settings-section provider-path-settings">
        <header>
          <span>
            <Server size={16} />
          </span>
          <h2>Machines</h2>
        </header>
        <div className="provider-machine-list">
          {project.machines.map((machine) => {
            const config = machineCompute[machine.alias] ?? {
              job_manager: null,
              jobs_root: "",
            };
            const needsSave = Boolean(
              machineComputeUpdates(
                { [machine.alias]: machine.compute ?? null },
                { [machine.alias]: machineCompute[machine.alias] ?? null },
              ),
            );
            const computeDisabled = writesDisabled || saving;
            return (
              <article className="provider-machine" key={machine.alias}>
                <header>
                  <strong>{machine.alias}</strong>
                  <span>
                    {machine.host || (spaceKind === "team" ? "Team server" : "Local machine")}
                  </span>
                </header>
                <div className="provider-path-list">
                  {providerCatalog.map((provider) => {
                    const recorded = machine.provider_paths[provider.provider] ?? "";
                    const value = providerPaths[machine.alias]?.[provider.provider] ?? "";
                    const readiness =
                      project.provider_readiness[machine.alias]?.[provider.provider];
                    const state = providerPathPresentation(readiness, value, recorded);
                    const resolveKey = `${machine.alias}:${provider.provider}`;
                    return (
                      <div className="provider-path-row" key={provider.provider}>
                        <strong>{provider.label || provider.provider}</strong>
                        <input
                          type="text"
                          aria-label={`${provider.label || provider.provider} executable on ${machine.alias}`}
                          value={value}
                          disabled={writesDisabled}
                          onChange={(event) => {
                            const path = event.target.value;
                            setProviderPaths((currentPaths) => ({
                              ...currentPaths,
                              [machine.alias]: {
                                ...currentPaths[machine.alias],
                                [provider.provider]: path,
                              },
                            }));
                            setStatus(null);
                          }}
                        />
                        <span className={`provider-path-state ${state.kind}`}>{state.label}</span>
                        <button
                          className="button secondary compact"
                          type="button"
                          disabled={writesDisabled || Boolean(resolvingProvider)}
                          onClick={() => void resolveProviderPath(machine.alias, provider.provider)}
                        >
                          {resolvingProvider === resolveKey ? (
                            <LoaderCircle className="spin" size={13} />
                          ) : (
                            <ScanSearch size={13} />
                          )}
                          Resolve
                        </button>
                      </div>
                    );
                  })}
                </div>
                <fieldset className="machine-compute" disabled={computeDisabled}>
                  <legend>Long-running jobs</legend>
                  <div className="compute-connection-fields">
                    <label>
                      <span>Use Slurm</span>
                      <input
                        type="checkbox"
                        checked={config.job_manager === "slurm"}
                        onChange={(event) =>
                          updateMachineCompute(machine.alias, {
                            ...config,
                            job_manager: event.target.checked ? "slurm" : null,
                          })
                        }
                      />
                    </label>
                    <label>
                      <span>Jobs root</span>
                      <input
                        value={config.jobs_root}
                        onChange={(event) =>
                          updateMachineCompute(machine.alias, {
                            ...config,
                            jobs_root: event.target.value,
                          })
                        }
                      />
                    </label>
                    <button
                      className="button secondary compact"
                      type="button"
                      onClick={() => updateMachineCompute(machine.alias, null)}
                    >
                      Reset compute
                    </button>
                  </div>
                  {(machine.compute?.job_manager
                    ? (["scheduler", "helper"] as const)
                    : (["helper"] as const)
                  ).map((route) => {
                    // RCP checks each route at startup and after a compute save.
                    const probe = needsSave ? null : (machine.compute_probes?.[route] ?? null);
                    const presentation = probe
                      ? computeProbePresentation(probe)
                      : {
                          label: needsSave ? "Checked after save" : "Not checked yet",
                          tone: "pending" as const,
                        };
                    return (
                      <div className={`compute-probe ${presentation.tone}`} key={route}>
                        <strong>{route === "scheduler" ? "Scheduler" : "Helper"}</strong>
                        <span className="compute-probe-dot" aria-hidden="true" />
                        <span>{presentation.label}</span>
                        {probe?.backend_id && <span>{probe.backend_id}</span>}
                        {probe?.diagnostic && <span>{probe.diagnostic}</span>}
                        {probe?.required_action && <em>{probe.required_action}</em>}
                      </div>
                    );
                  })}
                </fieldset>
              </article>
            );
          })}
        </div>
      </section>

      <ProviderLogins
        spaceKind={spaceKind}
        writesDisabled={writesDisabled}
        onLoginChanged={() => void onRefreshReadiness().catch(() => {})}
      />

      <section className="settings-section compute-settings">
        <header>
          <span>
            <Cpu size={16} />
          </span>
          <h2>Compute connections</h2>
          <div className="compute-settings-actions">
            <button
              className="button secondary compact"
              type="button"
              disabled={writesDisabled || readinessRequest?.pending || computeConfigurationIsDirty}
              title={
                computeConfigurationIsDirty
                  ? "Save compute changes before probing"
                  : "Probe compute connections"
              }
              onClick={() => void onRefreshReadiness().catch(() => {})}
            >
              {readinessRequest?.pending ? (
                <LoaderCircle className="spin" size={13} />
              ) : (
                <ScanSearch size={13} />
              )}
              {computeConfigurationIsDirty ? "Save first" : "Probe"}
            </button>
            <button
              className="button secondary compact"
              type="button"
              disabled={writesDisabled}
              onClick={() => {
                setComputeConnections((currentConnections) => [
                  ...currentConnections,
                  {
                    id: crypto.randomUUID(),
                    name: "Local compute",
                    kind: "local",
                    ssh_target: "",
                    access_hint: "",
                  },
                ]);
                setStatus(null);
              }}
            >
              <Plus size={13} /> Local
            </button>
            <button
              className="button secondary compact"
              type="button"
              disabled={writesDisabled}
              onClick={() => {
                setComputeConnections((currentConnections) => [
                  ...currentConnections,
                  {
                    id: crypto.randomUUID(),
                    name: "Remote compute",
                    kind: "ssh",
                    ssh_target: "",
                    access_hint: "",
                  },
                ]);
                setStatus(null);
              }}
            >
              <Plus size={13} /> SSH
            </button>
          </div>
        </header>
        <div className="compute-connection-list">
          {computeConnections.map((connection) => {
            const connectionNeedsSave = computeConnectionNeedsSave(
              project.compute_connections ?? [],
              connection,
            );
            return (
              <article className="compute-connection" key={connection.id}>
                <div className="compute-connection-fields">
                  <label>
                    <span>Name</span>
                    <input
                      type="text"
                      maxLength={80}
                      value={connection.name}
                      disabled={writesDisabled}
                      onChange={(event) => {
                        const name = event.target.value;
                        setComputeConnections((currentConnections) =>
                          currentConnections.map((item) =>
                            item.id === connection.id ? { ...item, name } : item,
                          ),
                        );
                        setStatus(null);
                      }}
                    />
                  </label>
                  <label>
                    <span>Type</span>
                    <select
                      value={connection.kind}
                      disabled={writesDisabled}
                      onChange={(event) => {
                        const kind = event.target.value as ComputeConnection["kind"];
                        setComputeConnections((currentConnections) =>
                          currentConnections.map((item) =>
                            item.id === connection.id
                              ? {
                                  ...item,
                                  kind,
                                  ssh_target: kind === "local" ? "" : item.ssh_target,
                                }
                              : item,
                          ),
                        );
                        setStatus(null);
                      }}
                    >
                      <option value="local">Local</option>
                      <option value="ssh">SSH</option>
                    </select>
                  </label>
                  {connection.kind === "ssh" ? (
                    <label>
                      <span>SSH target</span>
                      <input
                        type="text"
                        placeholder="user@host"
                        maxLength={255}
                        value={connection.ssh_target}
                        disabled={writesDisabled}
                        onChange={(event) => {
                          const ssh_target = event.target.value;
                          setComputeConnections((currentConnections) =>
                            currentConnections.map((item) =>
                              item.id === connection.id ? { ...item, ssh_target } : item,
                            ),
                          );
                          setStatus(null);
                        }}
                      />
                    </label>
                  ) : null}
                  <label className="compute-access-hint">
                    <span>Access hint (no credentials)</span>
                    <input
                      type="text"
                      maxLength={512}
                      placeholder="Optional path, scheduler, or environment"
                      value={connection.access_hint}
                      disabled={writesDisabled}
                      onChange={(event) => {
                        const access_hint = event.target.value;
                        setComputeConnections((currentConnections) =>
                          currentConnections.map((item) =>
                            item.id === connection.id ? { ...item, access_hint } : item,
                          ),
                        );
                        setStatus(null);
                      }}
                    />
                  </label>
                  <button
                    className="icon-button"
                    type="button"
                    aria-label={`Remove ${connection.name || "compute connection"}`}
                    disabled={writesDisabled}
                    onClick={() => {
                      setComputeConnections((currentConnections) =>
                        currentConnections.filter((item) => item.id !== connection.id),
                      );
                      setStatus(null);
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <div className="compute-probe-list">
                  {executionMachines.map((machine) => {
                    const probe = connectionNeedsSave
                      ? undefined
                      : project.compute_status?.[machine]?.[connection.id];
                    const presentation = connectionNeedsSave
                      ? { label: "Save before probing", tone: "pending" as const }
                      : computeProbePresentation(probe);
                    return (
                      <div className={`compute-probe ${presentation.tone}`} key={machine}>
                        <span className="compute-probe-dot" aria-hidden="true" />
                        <strong>{machine}</strong>
                        <span>{presentation.label}</span>
                        {probe?.required_action ? <em>{probe.required_action}</em> : null}
                        {probe && presentation.tone === "error" && !probe.required_action ? (
                          <em>{probe.diagnostic}</em>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </article>
            );
          })}
          {!computeConnections.length ? (
            <div className="settings-empty">No compute connections configured.</div>
          ) : null}
        </div>
        {readinessRequest?.computeError ? (
          <div className="settings-error">{readinessRequest.computeError}</div>
        ) : null}
      </section>

      <div className="settings-section agent-defaults">
        <header className="agent-defaults-heading">
          <div>
            <h2>Agent defaults</h2>
          </div>
          <label className="agent-auto-research-default">
            <span>
              Auto-research ceiling
              <small>Operational invocations per newly authorized episode</small>
            </span>
            <input
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={autoResearchInvocationCeiling}
              disabled={writesDisabled}
              onChange={(event) => {
                setAutoResearchInvocationCeiling(Number(event.target.value));
                setStatus(null);
              }}
            />
          </label>
        </header>
        <div className="settings-agent-list">
          {executionProfiles.map(({ id, label }) => (
            <article className="settings-agent" key={id}>
              <header>
                <span>
                  <strong>{label}</strong>
                </span>
                <span>
                  {id === "paper_coach"
                    ? "read-only coach"
                    : id === "orchestrator"
                      ? "auto-research"
                      : "graph patch only"}
                </span>
              </header>
              <AgentConfigControls
                project={project}
                value={profiles[id]}
                // The exported head describes the saved provider on the saved
                // machine; a draft that moved either shows blank until saved.
                effectiveModel={
                  profiles[id].provider === project.agent_profiles[id]?.provider &&
                  profiles[id].run_on === project.agent_profiles[id]?.run_on
                    ? project.agent_profiles[id]?.effective_model
                    : ""
                }
                locked={writesDisabled}
                runOnLocked={id !== "paper_coach"}
                workLikeCapable={project.agent_profiles[id]?.work_like_capable ?? true}
                onRefreshReadiness={onRefreshReadiness}
                readinessPending={readinessRequest?.pending ?? false}
                readinessError={readinessRequest?.providerError ?? null}
                runtime={{
                  value: profiles[id].runtime,
                  onChange: (runtime) => {
                    setProfiles((currentProfiles) => ({
                      ...currentProfiles,
                      [id]: { ...currentProfiles[id], runtime },
                    }));
                    setStatus(null);
                  },
                }}
                onChange={(value) => {
                  setProfiles((currentProfiles) => ({
                    ...currentProfiles,
                    [id]: { ...currentProfiles[id], ...value },
                  }));
                  setStatus(null);
                }}
              />
            </article>
          ))}
        </div>
      </div>

      <section className="settings-section skill-settings">
        <header>
          <span>
            <Sparkles size={16} />
          </span>
          <h2>Skills &amp; workflows</h2>
        </header>
        <div className="skill-card-groups">
          {renderSkillGroup("Workflows", workflowCatalog, skillDefaults.workflow_ids)}
          {renderSkillGroup("Skills", directSkillCatalog, skillDefaults.skill_ids)}
        </div>
      </section>

      <section className="settings-section cache-settings">
        <header>
          <span>
            <HardDrive size={16} />
          </span>
          <h2>Project cache</h2>
          <button
            className="button secondary compact"
            disabled={cacheClearDisabled || clearingCaches}
            aria-label="Clear project cache"
            onClick={() => void clearCaches()}
          >
            {clearingCaches ? <LoaderCircle className="spin" size={13} /> : <Trash2 size={13} />}
            {clearingCaches ? "Clearing" : "Clear project cache"}
          </button>
        </header>
        <div className="cache-meter-list">
          <CacheMeter label="Remote sources" metric={cacheMetrics.remote_sources} />
          <CacheMeter label="Session slices" metric={cacheMetrics.session_slices} />
        </div>
        {spaceKind === "personal" ? (
          <div className="app-cache-danger-row">
            <TriangleAlert size={16} aria-hidden="true" />
            <strong>Every project</strong>
            <button
              className="button danger compact"
              type="button"
              disabled={clearingAllCaches}
              onClick={() => {
                showClearAllCachesWarning(
                  () => setStatus(null),
                  () => setClearAllCachesOpen(true),
                );
              }}
            >
              <Trash2 size={13} /> Clear all project caches
            </button>
          </div>
        ) : null}
      </section>

      {spaceKind === "personal" && clearAllCachesOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !clearingAllCaches) {
              setClearAllCachesOpen(false);
            }
          }}
        >
          <section
            className="project-delete-dialog app-cache-clear-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="app-cache-clear-title"
            aria-describedby="app-cache-clear-warning"
          >
            <header>
              <TriangleAlert size={18} aria-hidden="true" />
              <h2 id="app-cache-clear-title">Clear caches for every project?</h2>
            </header>
            <p id="app-cache-clear-warning">
              Rebuildable remote-source copies and session slices for all projects will be removed.
              Canonical research and original provider data are not affected.
            </p>
            {status?.kind === "error" && (
              <div className="project-delete-error" role="alert">
                {status.text}
              </div>
            )}
            <footer>
              <button
                className="button secondary"
                type="button"
                autoFocus
                disabled={clearingAllCaches}
                onClick={() => setClearAllCachesOpen(false)}
              >
                Cancel
              </button>
              <button
                className="button danger"
                type="button"
                disabled={clearingAllCaches}
                onClick={() => void clearEveryProjectCache()}
              >
                {clearingAllCaches ? (
                  <LoaderCircle className="spin" size={13} />
                ) : (
                  <Trash2 size={13} />
                )}
                {clearingAllCaches ? "Clearing…" : "Clear all project caches"}
              </button>
            </footer>
          </section>
        </div>
      )}

      {inspectedPackage && (
        <SkillPackageInspector entry={inspectedPackage} onClose={() => setInspectedPackage(null)} />
      )}

      <footer className="settings-savebar">
        <div className={status ? `settings-save-status ${status.kind}` : "settings-save-status"}>
          {status?.kind === "error" && <TriangleAlert size={15} />}
          {status?.kind === "saved" && <Check size={15} />}
          <span>
            {status?.text ||
              (dirty ? "Unsaved manifest changes" : "Manifest matches these defaults")}
          </span>
        </div>
        <button className="button secondary" disabled={!dirty || saving} onClick={reset}>
          <RotateCcw size={14} /> Reset
        </button>
        <button
          className="button primary"
          disabled={
            writesDisabled ||
            !dirty ||
            saving ||
            !autoResearchInvocationCeilingIsValid ||
            !computeConnectionsAreValid
          }
          onClick={() => void save()}
        >
          {saving ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}
          {saving ? "Saving" : "Save"}
        </button>
      </footer>
    </section>
  );
}

export function providerPathPresentation(
  readiness: ProviderReadiness | undefined,
  value: string,
  recorded: string,
): { label: string; kind: "ready" | "warning" | "error" | "pending" } {
  if (value !== recorded) return { label: "Unsaved", kind: "pending" };
  if (readiness?.path_state === "unreachable")
    return { label: "Machine unreachable", kind: "error" };
  if (readiness?.path_state === "denied") return { label: "Recorded path unusable", kind: "error" };
  if (readiness?.path_state === "missing") {
    return { label: value ? "Recorded path missing" : "Executable missing", kind: "error" };
  }
  if (readiness?.path_state === "resolved") return { label: "Ready", kind: "ready" };
  return { label: "Not recorded", kind: "warning" };
}

function CacheMeter({ label, metric }: { label: string; metric: CacheMetric }) {
  const byteRatio = metric.limits.max_bytes > 0 ? metric.bytes / metric.limits.max_bytes : 0;
  const countRatio = metric.limits.max_count > 0 ? metric.count / metric.limits.max_count : 0;
  const ratio = Math.min(1, Math.max(byteRatio, countRatio));
  return (
    <div className="cache-meter">
      <div className="cache-meter-heading">
        <strong>{label}</strong>
        <span>
          {formatBytes(metric.bytes)} / {formatBytes(metric.limits.max_bytes)}
        </span>
      </div>
      <div
        className="cache-meter-track"
        role="progressbar"
        aria-label={`${label} cache usage`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(ratio * 100)}
      >
        <span style={{ width: `${ratio * 100}%` }} />
      </div>
      <div className="cache-meter-meta">
        <span>
          <em>Items</em>
          {metric.count} / {metric.limits.max_count}
        </span>
        <span>
          <em>TTL</em>
          {formatDuration(metric.limits.ttl_seconds)}
        </span>
        <span>
          <em>Reclaim</em>
          {metric.reclaimable_count} · {formatBytes(metric.reclaimable_bytes)}
        </span>
        <span>
          <em>Oldest</em>
          {metric.oldest_accessed_at
            ? new Date(metric.oldest_accessed_at).toLocaleDateString()
            : "—"}
        </span>
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function formatDuration(seconds: number): string {
  if (seconds % 86400 === 0) return `${seconds / 86400}d`;
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  return `${seconds}s`;
}
