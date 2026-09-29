import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ChatsWorkspace } from "../../src/views/ChatsWorkspace";
import { buildGlossaryIndex } from "../../src/glossary";
import type { ChatConversation } from "../../src/chatWorkspace";
import type { AgentTask, ChatTranscript, ProjectSnapshot } from "../../src/types";
import "../../src/styles.css";

const profile = {
  provider: "codex",
  model: "",
  reasoning: "medium",
  run_on: "local",
  permissions: {},
};
const project = {
  id: "project",
  name: "Project",
  agent_profiles: { node_chat: profile, project_chat: profile },
  provider_readiness: {
    local: {
      codex: {
        provider: "codex",
        label: "Codex",
        installed: true,
        authenticated: true,
        models: [],
      },
    },
  },
  repositories: [],
  project_truth_scope: [],
  machines: [{ alias: "local", host: null }],
} as unknown as ProjectSnapshot;

const conversations: ChatConversation[] = ["First chat", "Second chat"].map((title) => ({
  chatId: title,
  title,
  kind: "project_chat",
  nodeId: null,
  tasks: [],
  updatedAt: new Date().toISOString(),
}));
const chatTranscripts = new Map<string, ChatTranscript>(
  conversations.map((conversation) => [
    conversation.chatId,
    {
      chat_id: conversation.chatId,
      kind: conversation.kind,
      node_id: null,
      title: conversation.title,
      updated_at: conversation.updatedAt,
      message_count: 0,
      last_message_preview: "",
      messages: [],
    },
  ]),
);

function Fixture() {
  const [selected, setSelected] = useState(conversations[0].chatId);
  const [continued, setContinued] = useState("");
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  return (
    <main style={{ height: "100vh" }}>
      <output data-testid="continued-chat">{continued}</output>
      <ChatsWorkspace
        project={project}
        conversations={conversations}
        selectedChatId={selected}
        nodes={{}}
        glossaryIndex={buildGlossaryIndex({})}
        runScope={[]}
        tasks={tasks}
        watchers={[]}
        graphChangesDisabled={false}
        unreadTaskIds={new Set()}
        chatTranscripts={chatTranscripts}
        hasMore={false}
        loadingMore={false}
        onSelect={setSelected}
        onLoadMore={() => {}}
        onStartTask={async () => {}}
        onResumeTask={() => {}}
        onRetryTask={() => {}}
        onRefreshTask={async () => {
          throw new Error("No task in this fixture");
        }}
        onInspectTask={() => {}}
        onOpenInbox={() => {}}
        onRepairGraphUpdate={async () => {}}
        onContinueImported={(result) => {
          setContinued(result.chat_id);
          setTasks([
            {
              ...result.task,
              native_session_id: "11111111-1111-4111-8111-111111111111",
              kind: "project_chat",
              history_only: false,
              request: { chat_id: result.chat_id, run_truth_scope: ["repo"] },
            } as AgentTask,
          ]);
        }}
        onNewSession={() => {}}
      />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
