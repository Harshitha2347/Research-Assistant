import { FormEvent, Fragment, KeyboardEvent, useEffect, useRef, useState } from "react";
import { listConversations, listDocuments } from "../api/client";
import { ChatMessage, ConversationSummary, DocumentRecord } from "../types";
import { useVoice } from "../hooks/useVoice";
import { useChatSession } from "../context/JobsContext";

type WebMode = "auto" | "docs" | "web";


function renderInline(text: string, keyPrefix: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>;
    }
    return <Fragment key={`${keyPrefix}-${i}`}>{part}</Fragment>;
  });
}

function AnswerBody({ content }: { content: string }) {
  const blocks = content.trim().split(/\n\s*\n/);

  return (
    <div className="prose-answer">
      {blocks.map((block, bi) => {
        const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
        const isBulleted = lines.length > 0 && lines.every((l) => /^[-*]\s+/.test(l));
        const isNumbered = lines.length > 0 && lines.every((l) => /^\d+[.)]\s+/.test(l));

        if (isBulleted) {
          return (
            <ul key={bi}>
              {lines.map((l, li) => (
                <li key={li}>{renderInline(l.replace(/^[-*]\s+/, ""), `${bi}-${li}`)}</li>
              ))}
            </ul>
          );
        }
        if (isNumbered) {
          return (
            <ol key={bi}>
              {lines.map((l, li) => (
                <li key={li}>{renderInline(l.replace(/^\d+[.)]\s+/, ""), `${bi}-${li}`)}</li>
              ))}
            </ol>
          );
        }
        return <p key={bi}>{renderInline(lines.join(" "), `${bi}`)}</p>;
      })}
    </div>
  );
}

const icons = {
  send: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M17 3 9 11M17 3l-5.5 14-2.7-6.3L3 8.5 17 3Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  plus: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  globe: (
    <svg viewBox="0 0 20 20" fill="none" className="w-3.5 h-3.5">
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3 10h14M10 3c2.2 2 2.2 12 0 14M10 3c-2.2 2-2.2 12 0 14" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  image: (
    <svg viewBox="0 0 20 20" fill="none" className="w-3.5 h-3.5">
      <rect x="3" y="4" width="14" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="7.3" cy="8" r="1.1" stroke="currentColor" strokeWidth="1.1" />
      <path d="m4 14 4-4 3 3 2.5-2.5L17 14" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  ),
  chat: (
    <svg viewBox="0 0 20 20" fill="none" className="w-3.5 h-3.5 shrink-0">
      <path d="M3 5.5A2.5 2.5 0 0 1 5.5 3h9A2.5 2.5 0 0 1 17 5.5v6A2.5 2.5 0 0 1 14.5 14H8l-3.6 3V14h-.9A2.5 2.5 0 0 1 3 11.5v-6Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  ),
  mic: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <rect x="7.5" y="2.5" width="5" height="8.5" rx="2.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5 9.5a5 5 0 0 0 10 0M10 14.5v3M7 17.5h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  ),
  speaker: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M4 7.5h2.5L11 4v12L6.5 12.5H4v-5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M14 7.2a3.5 3.5 0 0 1 0 5.6M16.3 5.3a6.8 6.8 0 0 1 0 9.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  ),
  speakerMuted: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M4 7.5h2.5L11 4v12L6.5 12.5H4v-5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M14.5 7.5l4 5M18.5 7.5l-4 5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  ),
  copy: (
    <svg viewBox="0 0 20 20" fill="none" className="w-3.5 h-3.5">
      <rect x="7" y="7" width="9" height="10.5" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M13 7V4.5A1.5 1.5 0 0 0 11.5 3h-7A1.5 1.5 0 0 0 3 4.5v9A1.5 1.5 0 0 0 4.5 15H7" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  ),
  check: (
    <svg viewBox="0 0 20 20" fill="none" className="w-3.5 h-3.5">
      <path d="M4 10.5 8 14.5 16 5.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

const WEB_MODES: { key: WebMode; label: string; hint: string }[] = [
  { key: "auto", label: "Auto", hint: "Use the web only if your documents don't have a confident answer" },
  { key: "docs", label: "Docs only", hint: "Never search the web — answer strictly from your documents" },
  { key: "web", label: "Web", hint: "Strictly search the web only — your documents are not used" },
];

export default function Chat() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [input, setInput] = useState("");
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [scopedDocs, setScopedDocs] = useState<Set<string>>(new Set());
  const [webMode, setWebMode] = useState<WebMode>("auto");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  
  const { activeConv, messages, sending, conversationsVersion, openConversation, newConversation, sendMessage } =
    useChatSession();

  const {
    sttSupported,
    ttsSupported,
    listening,
    interimTranscript,
    speaking,
    autoSpeak,
    setAutoSpeak,
    voiceError,
    startListening,
    stopListening,
    speak,
    stopSpeaking,
  } = useVoice();

  const refreshConversations = () => listConversations().then((r) => setConversations(r.data));

  useEffect(() => {
    refreshConversations();
    listDocuments().then((r) => setDocs(r.data));
  }, []);

  // Refresh the sidebar whenever a message finishes elsewhere (e.g. a
  // brand-new conversation got its title, or a reply arrived while this
  // page wasn't mounted).
  useEffect(() => {
    if (conversationsVersion > 0) refreshConversations();
  }, [conversationsVersion]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const onSend = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending) return;
    const message = input;
    setInput("");
    const data = await sendMessage(
      message,
      scopedDocs.size > 0 ? Array.from(scopedDocs) : undefined,
      webMode === "auto" ? null : webMode === "web"
    );
    if (data && autoSpeak) speak(data.answer);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend(e as unknown as FormEvent);
    }
  };

  const toggleScope = (id: string) => {
    setScopedDocs((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const onMicToggle = () => {
    if (listening) {
      stopListening();
      return;
    }
    startListening((finalText) => {
     
      setInput((prev) => (prev.trim() ? `${prev.trim()} ${finalText}` : finalText));
    });
  };

  const copyMessage = async (index: number, text: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error("clipboard API unavailable");
      }
    } catch {
      
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        // Nothing more we can do here.
      }
      document.body.removeChild(ta);
    }
    setCopiedIndex(index);
    window.setTimeout(() => setCopiedIndex((cur) => (cur === index ? null : cur)), 1500);
  };

  const loadingLabel =
    webMode === "web" ? "Searching the web…" : webMode === "docs" ? "Reading your documents…" : "Thinking…";

  return (
    <div className="flex flex-1 min-h-0">
      {/* ---------------------------------------------------------- sidebar */}
      <aside className="w-72 shrink-0 border-r border-surface-200 bg-white/70 backdrop-blur-sm p-3 flex flex-col min-h-0">
        <button
          onClick={() => {
            newConversation();
            inputRef.current?.focus();
          }}
          className="btn-primary w-full mb-4 py-2.5 text-sm"
        >
          {icons.plus}
          New conversation
        </button>

        <div className="overflow-y-auto scroll-thin flex-1 space-y-0.5 -mx-1 px-1">
          {conversations.length === 0 && (
            <p className="text-xs text-surface-400 px-2 py-3">Your conversations will show up here.</p>
          )}
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => openConversation(c.id)}
              className={`group w-full flex items-center gap-2 text-left text-sm px-2.5 py-2.5 rounded-lg truncate transition-colors ${
                activeConv === c.id
                  ? "bg-brand-50 text-brand-700"
                  : "hover:bg-surface-100 text-surface-600"
              }`}
              title={c.title || "Untitled conversation"}
            >
              <span className={activeConv === c.id ? "text-brand-500" : "text-surface-400 group-hover:text-surface-500"}>
                {icons.chat}
              </span>
              <span className="truncate">{c.title || "New conversation"}</span>
            </button>
          ))}
        </div>

        {docs.length > 0 && (
          <div className="mt-3 border-t border-surface-200 pt-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-surface-400 mb-2 px-1">
              Scope to documents
            </p>
            <div className="space-y-0.5 max-h-40 overflow-y-auto scroll-thin">
              {docs.map((d) => (
                <label
                  key={d.id}
                  className="flex items-center gap-2 text-xs text-surface-600 px-2 py-1.5 rounded-md hover:bg-surface-100 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={scopedDocs.has(d.id)}
                    onChange={() => toggleScope(d.id)}
                    className="accent-brand-600"
                  />
                  <span className="truncate">{d.filename}</span>
                </label>
              ))}
            </div>
            {scopedDocs.size === 0 && (
              <p className="text-[11px] text-surface-400 px-1 mt-1.5">None selected — searches across all documents.</p>
            )}
          </div>
        )}
      </aside>

      {/* ------------------------------------------------------------ main */}
      <section className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 overflow-y-auto scroll-thin px-6 py-6">
          <div className="max-w-3xl mx-auto space-y-5">
            {messages.length === 0 && (
              <div className="text-center mt-24">
                <div className="w-12 h-12 mx-auto rounded-2xl bg-brand-gradient shadow-lift flex items-center justify-center mb-4">
                  <span className="text-white font-display font-bold">?</span>
                </div>
                <p className="text-surface-500 text-sm">
                  Ask anything about your uploaded documents.
                </p>
              </div>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                className={`group flex flex-col animate-fade-in-up ${
                  m.role === "user" ? "items-end" : "items-start"
                }`}
              >
                <div
                  className={`max-w-xl rounded-2xl px-4 py-3 text-sm ${
                    m.role === "user"
                      ? "bg-brand-gradient text-white shadow-lift"
                      : "card text-surface-800"
                  }`}
                >
                  {m.role === "assistant" ? (
                    <AnswerBody content={m.content} />
                  ) : (
                    <p className="whitespace-pre-wrap">{m.content}</p>
                  )}
                  {m.role === "assistant" && ttsSupported && (
                    <button
                      type="button"
                      onClick={() => (speaking ? stopSpeaking() : speak(m.content))}
                      title={speaking ? "Stop reading aloud" : "Read this answer aloud"}
                      className="mt-2 text-surface-400 hover:text-brand-600 transition-colors"
                    >
                      {speaking ? icons.speakerMuted : icons.speaker}
                    </button>
                  )}
                  {m.role === "assistant" && m.used_web_search && (
                    <div className="mt-2.5 flex gap-1.5 flex-wrap">
                      <span className="badge bg-accent-400/15 text-accent-600">
                        {icons.globe}
                        From the web
                      </span>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => copyMessage(i, m.content)}
                  title="Copy to clipboard"
                  className="mt-1 flex items-center gap-1 px-1 text-[11px] text-surface-400 hover:text-brand-600 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                >
                  {copiedIndex === i ? icons.check : icons.copy}
                  {copiedIndex === i ? "Copied" : "Copy"}
                </button>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start animate-fade-in">
                <div className="card px-4 py-3 text-sm text-surface-400 flex items-center gap-2">
                  <span className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse-soft" style={{ animationDelay: "0ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse-soft" style={{ animationDelay: "150ms" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse-soft" style={{ animationDelay: "300ms" }} />
                  </span>
                  {loadingLabel}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-surface-200 bg-white/80 backdrop-blur-sm px-6 py-4">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center gap-1.5 mb-2.5 flex-wrap">
              {WEB_MODES.map((mode) => (
                <button
                  key={mode.key}
                  type="button"
                  title={mode.hint}
                  onClick={() => setWebMode(mode.key)}
                  className={`text-xs font-medium px-2.5 py-1 rounded-full border transition-colors ${
                    webMode === mode.key
                      ? "bg-brand-600 border-brand-600 text-white"
                      : "bg-white border-surface-200 text-surface-500 hover:border-brand-300 hover:text-brand-600"
                  }`}
                >
                  {mode.label}
                </button>
              ))}
              {ttsSupported && (
                <button
                  type="button"
                  title={autoSpeak ? "Assistant replies are read aloud automatically" : "Read assistant replies aloud automatically"}
                  onClick={() => {
                    if (autoSpeak) stopSpeaking();
                    setAutoSpeak((v) => !v);
                  }}
                  className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border transition-colors ${
                    autoSpeak
                      ? "bg-accent-500 border-accent-500 text-white"
                      : "bg-white border-surface-200 text-surface-500 hover:border-brand-300 hover:text-brand-600"
                  }`}
                >
                  {autoSpeak ? icons.speaker : icons.speakerMuted}
                  Speak replies
                </button>
              )}
            </div>
            {voiceError && <p className="text-xs text-red-600 mb-2">{voiceError}</p>}
            {listening && (
              <p className="text-xs text-brand-600 mb-2 flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse-soft" />
                Listening… {interimTranscript && <span className="text-surface-400">"{interimTranscript}"</span>}
              </p>
            )}
            <form onSubmit={onSend} className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Ask a question about your documents..."
                className="input-field resize-none max-h-32"
              />
              {sttSupported && (
                <button
                  type="button"
                  onClick={onMicToggle}
                  title={listening ? "Stop listening" : "Speak your question"}
                  className={`px-3 py-2.5 rounded-lg shrink-0 border transition-colors ${
                    listening
                      ? "bg-red-50 border-red-200 text-red-600 animate-pulse-soft"
                      : "bg-white border-surface-200 text-surface-500 hover:border-brand-300 hover:text-brand-600"
                  }`}
                >
                  {icons.mic}
                </button>
              )}
              <button type="submit" disabled={sending || !input.trim()} className="btn-primary px-4 py-2.5 shrink-0">
                {icons.send}
                <span className="hidden sm:inline">Send</span>
              </button>
            </form>
          </div>
        </div>
      </section>
    </div>
  );
}
