import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import {
  cancelEvaluationJob,
  compareDocuments,
  getConversationMessages,
  getDocumentJob,
  getEvaluationJob,
  listDocuments,
  runEvaluation,
  sendChatMessage,
  summariseDocument,
  uploadDocuments,
} from "../api/client";
import { ChatMessage } from "../types";


const POLL_MS = 3000;

/* ------------------------------------------------------------ upload */

type UploadPhase = "idle" | "uploading" | "processing";

interface UploadState {
  phase: UploadPhase;
  progress: number;
  fileCount: number;
  error: string;
  completedAt: number;
  startUpload: (files: File[]) => void;
}

const UploadContext = createContext<UploadState | undefined>(undefined);

export function useUpload() {
  const ctx = useContext(UploadContext);
  if (!ctx) throw new Error("useUpload must be used within JobsProvider");
  return ctx;
}

function useUploadState(): UploadState {
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [progress, setProgress] = useState(0);
  const [fileCount, setFileCount] = useState(0);
  const [error, setError] = useState("");
  const [completedAt, setCompletedAt] = useState(0);
  const pollRef = useRef<number | null>(null);

  const stopPolling = () => {
  if (pollRef.current !== null) {
    window.clearTimeout(pollRef.current);
    pollRef.current = null;
  }
};

  useEffect(() => stopPolling, []);

  const startUpload = (files: File[]) => {
    if (files.length === 0) return;
    setError("");
    setFileCount(files.length);
    setProgress(0);
    setPhase("uploading");

    uploadDocuments(files, (pct) => {
      setProgress(pct);
    })
      .then((res) => {
       
        const ids: string[] = (res.data?.documents ?? []).map((d: any) => d.id);
        setPhase("processing");
        if (ids.length === 0) {
          setPhase("idle");
          setCompletedAt(Date.now());
          return;
        }
        const pollDocuments = async () => {
          try {
            const list = await listDocuments();
            const relevant = (list.data as any[]).filter((d) =>
              ids.includes(d.id)
            );

            const stillProcessing = relevant.some(
              (d) => d.status === "processing");

            if (!stillProcessing) {
              stopPolling();
              setPhase("idle");
              setProgress(0);
              setCompletedAt(Date.now());
              return;
            }
          } catch {
    // transient failure — retry after delay
        }

        pollRef.current = window.setTimeout(
          pollDocuments,
          POLL_MS
        );
      };

pollDocuments();
      })
      .catch((e: any) => {
        setError(e?.response?.data?.detail ?? "Upload failed — please try again.");
        setPhase("idle");
        setProgress(0);
        setCompletedAt(Date.now());
      });
  };

  return { phase, progress, fileCount, error, completedAt, startUpload };
}

/* ------------------------------------------------- summarise / compare */

interface SummaryState {
  summaryDocId: string | null;
  summaryText: string | null;
  summaryLoading: boolean;
  summaryError: string;
  comparisonIds: string[];
  comparisonText: string | null;
  comparisonLoading: boolean;
  comparisonError: string;
  startSummarise: (documentId: string) => void;
  startCompare: (documentIds: string[], aspect?: string) => void;
  clearSummary: () => void;
  clearComparison: () => void;
}

const SummaryContext = createContext<SummaryState | undefined>(undefined);

export function useSummaryJobs() {
  const ctx = useContext(SummaryContext);
  if (!ctx) throw new Error("useSummaryJobs must be used within JobsProvider");
  return ctx;
}

type PollableJob = { status: string; result: any; error: string | null };

function usePollJob(
  jobId: string | null,
  fetchJob: (jobId: string) => Promise<{ data: PollableJob }>,
  onDone: (result: any) => void,
  onError: (msg: string) => void,
  onCancelled?: () => void
) {
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const interval = window.setInterval(async () => {
      try {
        const res = await fetchJob(jobId);
        if (cancelled) return;
        if (res.data.status === "done") {
          window.clearInterval(interval);
          onDone(res.data.result);
        } else if (res.data.status === "cancelled") {
          window.clearInterval(interval);
          (onCancelled ?? (() => onError("Stopped.")))();
        } else if (res.data.status === "error") {
          window.clearInterval(interval);
          onError(res.data.error || "Job failed.");
        }
      } catch {
        // transient poll failure — try again on the next tick
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);
}

function useSummaryState(): SummaryState {
  const [summaryDocId, setSummaryDocId] = useState<string | null>(null);
  const [summaryJobId, setSummaryJobId] = useState<string | null>(null);
  const [summaryText, setSummaryText] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");

  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [comparisonJobId, setComparisonJobId] = useState<string | null>(null);
  const [comparisonText, setComparisonText] = useState<string | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");

  usePollJob(
    summaryJobId,
    getDocumentJob,
    (result) => {
      setSummaryText(result?.summary ?? "");
      setSummaryLoading(false);
      setSummaryJobId(null);
    },
    (msg) => {
      setSummaryError(msg);
      setSummaryLoading(false);
      setSummaryJobId(null);
    }
  );

  usePollJob(
    comparisonJobId,
    getDocumentJob,
    (result) => {
      setComparisonText(result?.comparison ?? "");
      setComparisonLoading(false);
      setComparisonJobId(null);
    },
    (msg) => {
      setComparisonError(msg);
      setComparisonLoading(false);
      setComparisonJobId(null);
    }
  );

  const startSummarise = (documentId: string) => {
    setSummaryDocId(documentId);
    setSummaryText(null);
    setSummaryError("");
    setSummaryLoading(true);
    summariseDocument(documentId)
      .then((res) => setSummaryJobId(res.data.job_id))
      .catch((e: any) => {
        setSummaryError(e?.response?.data?.detail ?? "Couldn't start summarisation.");
        setSummaryLoading(false);
      });
  };

  const startCompare = (documentIds: string[], aspect?: string) => {
    setComparisonIds(documentIds);
    setComparisonText(null);
    setComparisonError("");
    setComparisonLoading(true);
    compareDocuments(documentIds, aspect)
      .then((res) => setComparisonJobId(res.data.job_id))
      .catch((e: any) => {
        setComparisonError(e?.response?.data?.detail ?? "Couldn't start comparison.");
        setComparisonLoading(false);
      });
  };

  return {
    summaryDocId,
    summaryText,
    summaryLoading,
    summaryError,
    comparisonIds,
    comparisonText,
    comparisonLoading,
    comparisonError,
    startSummarise,
    startCompare,
    clearSummary: () => {
      setSummaryDocId(null);
      setSummaryText(null);
      setSummaryError("");
    },
    clearComparison: () => {
      setComparisonIds([]);
      setComparisonText(null);
      setComparisonError("");
    },
  };
}

/* -------------------------------------------------------- evaluation */

type EvalStatus = "idle" | "running" | "done" | "cancelled" | "error";

interface EvaluationJobState {
  evalRunning: boolean;
  evalStatus: EvalStatus;
  evalMessage: string;
  evalCompletedAt: number;
  startEvaluation: (conversationId: string, pairIndices: number[]) => void;
  stopEvaluation: () => void;
}

const EvaluationJobContext = createContext<EvaluationJobState | undefined>(undefined);

export function useEvaluationJob() {
  const ctx = useContext(EvaluationJobContext);
  if (!ctx) throw new Error("useEvaluationJob must be used within JobsProvider");
  return ctx;
}

function useEvaluationJobState(): EvaluationJobState {
  const [evalStatus, setEvalStatus] = useState<EvalStatus>("idle");
  const [evalMessage, setEvalMessage] = useState("");
  const [evalCompletedAt, setEvalCompletedAt] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);

  usePollJob(
    jobId,
    getEvaluationJob,
    () => {
      setEvalStatus("done");
      setEvalMessage("");
      setJobId(null);
      setEvalCompletedAt(Date.now());
    },
    (msg) => {
      setEvalStatus("error");
      setEvalMessage(msg);
      setJobId(null);
    },
    () => {
      // Stopped by the user (see stopEvaluation) — not an error. Any
      // pairs that finished before the stop request took effect were
      // still saved server-side, so refresh history to pick them up.
      setEvalStatus("cancelled");
      setEvalMessage("Evaluation stopped.");
      setJobId(null);
      setEvalCompletedAt(Date.now());
    }
  );

  const startEvaluation = (conversationId: string, pairIndices: number[]) => {
    setEvalStatus("running");
    setEvalMessage("");
    runEvaluation(conversationId, pairIndices)
      .then((res) => setJobId(res.data.job_id))
      .catch((e: any) => {
        setEvalStatus("error");
        setEvalMessage(e?.response?.data?.detail ?? "Evaluation failed to start.");
      });
  };

  const stopEvaluation = () => {
    if (!jobId) return;
    cancelEvaluationJob(jobId).catch(() => {
      // best-effort — if this fails the job just keeps running and the
      // user can try again
    });
  };

  return {
    evalRunning: evalStatus === "running",
    evalStatus,
    evalMessage,
    evalCompletedAt,
    startEvaluation,
    stopEvaluation,
  };
}

/* --------------------------------------------------------------- chat */

interface ChatSessionState {
  activeConv: string | undefined;
  messages: ChatMessage[];
  sending: boolean;
  conversationsVersion: number;
  openConversation: (id: string) => Promise<void>;
  newConversation: () => void;
  sendMessage: (
    message: string,
    documentIds?: string[],
    useWebSearch?: boolean | null
  ) => Promise<{ conversation_id: string; answer: string } | undefined>;
}

const ChatSessionContext = createContext<ChatSessionState | undefined>(undefined);

export function useChatSession() {
  const ctx = useContext(ChatSessionContext);
  if (!ctx) throw new Error("useChatSession must be used within JobsProvider");
  return ctx;
}

function useChatSessionState(): ChatSessionState {
  const [activeConv, setActiveConv] = useState<string | undefined>(undefined);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
 
  const [conversationsVersion, setConversationsVersion] = useState(0);

  const openConversation = async (id: string) => {
    setActiveConv(id);
    const res = await getConversationMessages(id);
    setMessages(res.data.map((m: any) => ({ role: m.role, content: m.content })));
  };

  const newConversation = () => {
    setActiveConv(undefined);
    setMessages([]);
  };

  const sendMessage = async (
    message: string,
    documentIds?: string[],
    useWebSearch?: boolean | null
  ) => {
    const userMsg: ChatMessage = { role: "user", content: message };
    setMessages((prev) => [...prev, userMsg]);
    setSending(true);
    try {
     
      const res = await sendChatMessage(message, activeConv, documentIds, useWebSearch);
      setActiveConv(res.data.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: res.data.answer,
          used_web_search: res.data.used_web_search,
          used_image_analysis: res.data.used_image_analysis,
        },
      ]);
      setConversationsVersion((v) => v + 1);
      return res.data;
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: err?.response?.data?.detail ?? "Something went wrong answering that — please try again.",
        },
      ]);
      return undefined;
    } finally {
      setSending(false);
    }
  };

  return { activeConv, messages, sending, conversationsVersion, openConversation, newConversation, sendMessage };
}

/* --------------------------------------------------------- provider */

export function JobsProvider({ children }: { children: ReactNode }) {
  const upload = useUploadState();
  const summary = useSummaryState();
  const evaluation = useEvaluationJobState();
  const chat = useChatSessionState();

  return (
    <UploadContext.Provider value={upload}>
      <SummaryContext.Provider value={summary}>
        <EvaluationJobContext.Provider value={evaluation}>
          <ChatSessionContext.Provider value={chat}>{children}</ChatSessionContext.Provider>
        </EvaluationJobContext.Provider>
      </SummaryContext.Provider>
    </UploadContext.Provider>
  );
}
