import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { api } from "../api";
import { MarkdownAnswer } from "../chatMarkdown";
import { isInjectedCodexContext } from "../providerHistoryPresentation";
import type { ImportedHistoryPage } from "../types";

const PAGE_SIZE = 100;

export function ImportedCodexContext({
  apiBase,
  sessionId,
  chatId,
  scrollContainerRef,
  onInitialLoad,
}: {
  apiBase: string;
  sessionId: string;
  chatId: string;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  onInitialLoad: () => void;
}) {
  const [page, setPage] = useState<ImportedHistoryPage | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const initialLoaded = useRef(false);
  const scrollAnchor = useRef<{ top: number; height: number } | null>(null);
  const url = `${apiBase}/provider-history/codex/${encodeURIComponent(sessionId)}?chat_id=${encodeURIComponent(chatId)}`;

  useEffect(() => {
    let current = true;
    void api<ImportedHistoryPage>(`${url}&limit=${PAGE_SIZE}`)
      .then((loaded) => {
        if (current) setPage(loaded);
      })
      .catch((failure) => {
        if (current) setError(failure instanceof Error ? failure.message : String(failure));
      })
      .finally(() => {
        if (current) setBusy(false);
      });
    return () => {
      current = false;
    };
  }, [url]);

  useLayoutEffect(() => {
    if (!page) return;
    const element = scrollContainerRef.current;
    const anchor = scrollAnchor.current;
    if (element && anchor) {
      element.scrollTop = anchor.top + element.scrollHeight - anchor.height;
      scrollAnchor.current = null;
    } else if (!initialLoaded.current) {
      initialLoaded.current = true;
      onInitialLoad();
    }
  }, [page, onInitialLoad, scrollContainerRef]);

  async function loadEarlier() {
    if (!page || busy || page.offset === 0) return;
    setBusy(true);
    setError(null);
    try {
      const offset = Math.max(0, page.offset - PAGE_SIZE);
      const earlier = await api<ImportedHistoryPage>(
        `${url}&offset=${offset}&limit=${page.offset - offset}`,
      );
      const element = scrollContainerRef.current;
      if (element) scrollAnchor.current = { top: element.scrollTop, height: element.scrollHeight };
      setPage({ ...earlier, messages: [...earlier.messages, ...page.messages] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  const messages = page?.messages.filter((message) => !isInjectedCodexContext(message)) ?? [];
  return (
    <section className="imported-codex-context" aria-label="Imported Codex context">
      <header className="imported-codex-context-heading">
        <strong>Imported Codex context</strong>
        {page && <span>{messages.length} messages shown</span>}
        {page && page.offset > 0 && (
          <button
            className="button secondary compact"
            disabled={busy}
            onClick={() => void loadEarlier()}
            type="button"
          >
            {busy ? "Loading…" : "Load earlier messages"}
          </button>
        )}
      </header>
      {busy && !page && (
        <p className="node-chat-line meta" role="status">
          Loading imported context…
        </p>
      )}
      {error && (
        <p className="node-chat-line error" role="alert">
          Imported context unavailable: {error}
        </p>
      )}
      {messages.map((message) => (
        <article
          className={`node-chat-line ${message.role === "user" ? "human" : "agent"}`}
          data-provider-message-id={message.message_id}
          key={message.message_id}
        >
          <header className="imported-codex-message-meta">
            <span>
              {message.role === "user" ? "You" : "Codex"}
              {message.phase === "commentary" ? " · Commentary" : ""}
            </span>
            <time dateTime={message.timestamp}>{new Date(message.timestamp).toLocaleString()}</time>
          </header>
          {message.role === "assistant" ? (
            <div className="chat-markdown">
              <MarkdownAnswer text={message.text} />
            </div>
          ) : (
            <span className="node-chat-text">{message.text}</span>
          )}
        </article>
      ))}
      <p className="imported-codex-context-heading">RCP chat</p>
    </section>
  );
}
