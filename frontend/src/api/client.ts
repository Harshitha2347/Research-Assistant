import axios from "axios";
import { JobStatus } from "../types";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const api = axios.create({ baseURL });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---------------------------------------------------------------- auth ----
export const signup = (email: string, password: string) =>
  api.post("/auth/signup", { email, password });

export const login = (email: string, password: string) =>
  api.post("/auth/login", { email, password });

// ----------------------------------------------------------- documents ----
export const uploadDocuments = (
  files: File[],
  onProgress?: (percent: number) => void
) => {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  return api.post("/documents/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (evt) => {
      if (!onProgress) return;
      const total = evt.total ?? 0;
      const percent = total > 0 ? Math.round((evt.loaded * 100) / total) : 0;
      onProgress(percent);
    },
  });
};

export const listDocuments = () => api.get("/documents");
export const deleteDocument = (id: string) => api.delete(`/documents/${id}`);

export const summariseDocument = (document_id: string) =>
  api.post<{ job_id: string }>("/documents/summarise", { document_id });
export const compareDocuments = (document_ids: string[], aspect?: string) =>
  api.post<{ job_id: string }>("/documents/compare", { document_ids, aspect });
export const getDocumentJob = (jobId: string) =>
  api.get<JobStatus>(`/documents/jobs/${jobId}`);

// ---------------------------------------------------------------- chat ----
export const sendChatMessage = (
  message: string,
  conversation_id?: string,
  document_ids?: string[],
  use_web_search?: boolean | null
) => api.post("/chat", { message, conversation_id, document_ids, use_web_search });

export const listConversations = () => api.get("/chat/conversations");
export const getConversationMessages = (id: string) =>
  api.get(`/chat/conversations/${id}/messages`);

// --------------------------------------------------------- evaluation ----

export const getEvaluationPairs = (conversation_id: string) =>
  api.get(`/evaluation/pairs/${conversation_id}`);

export const runEvaluation = (
  conversation_id: string,
  pair_indices?: number[]
) =>
  api.post<{ job_id: string }>("/evaluation/run", {
    conversation_id,
    pair_indices,
  });

export const getEvaluationJob = (jobId: string) =>
  api.get<JobStatus>(`/evaluation/jobs/${jobId}`);


export const cancelEvaluationJob = (jobId: string) =>
  api.post<{ cancelled: boolean }>(`/evaluation/jobs/${jobId}/cancel`);

export const evaluationHistory = () =>
  api.get("/evaluation/history");