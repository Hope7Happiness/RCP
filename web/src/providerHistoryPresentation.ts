import type { AgentTask, ImportedHistoryMessage } from "./types";
import type { TaskTranscriptLine } from "./agentTasks";

/** Hide complete provider-injected records, never snippets inside human messages. */
export function isInjectedCodexContext(message: ImportedHistoryMessage): boolean {
  if (message.role !== "user") return false;
  let remaining = message.text.trim();
  let matched = false;
  while (remaining) {
    const block = remaining.match(
      /^(?:<environment_context>[\s\S]*?<\/environment_context>|# AGENTS\.md instructions(?: for [^\r\n]+)?\r?\n\s*<INSTRUCTIONS>[\s\S]*?<\/INSTRUCTIONS>)/,
    );
    if (!block) return false;
    matched = true;
    remaining = remaining.slice(block[0].length).trim();
  }
  return matched;
}

/** Retire a repaired handoff diagnostic in chat; keep the original task untouched. */
export function hideResolvedCodexHandoffErrors(
  lines: TaskTranscriptLine[],
  tasks: AgentTask[],
): TaskTranscriptLine[] {
  const byId = new Map(tasks.map((task) => [task.operation_id, task]));
  return lines.filter((line) => {
    if (
      line.role !== "error" ||
      line.text !== "The continued native transcript changed source identity."
    )
      return true;
    const failed = byId.get(line.taskId);
    if (!failed?.failed || !failed.native_session_id || !failed.request.chat_id) return true;
    return !tasks.some(
      (later) =>
        later.settled &&
        later.project_id === failed.project_id &&
        later.request.chat_id === failed.request.chat_id &&
        later.native_session_id === failed.native_session_id &&
        Date.parse(later.created_at) > Date.parse(failed.created_at),
    );
  });
}
