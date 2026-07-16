export interface DocumentRecord {
  id: string;
  user_id: string;
  filename: string;
  storage_path: string;
  num_pages: number;
  num_chunks: number;
  num_figures: number;
  status: "processing" | "ready" | "failed";
  created_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  used_web_search?: boolean;
  used_image_analysis?: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
}

/* ---------- NEW ---------- */

export interface EvaluationPair {
  index: number;
  question: string;
  answer: string;
}

/* ------------------------- */

export interface EvaluationResult {
  id: string;
  conversation_id: string;
  // null means this metric's judge-LLM call failed to parse/compute for
  // this evaluation (a RAGAS-side failure) — distinct from a genuine low
  // score, which is a normal number like 0.
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  pair_indices?: number[];
  conversation_title?: string;
  created_at: string;
}

/* -------- background jobs (summarise / compare / evaluation) -------- */

export interface JobStatus {
  id: string;
  kind: "summarise" | "compare" | "evaluation";
  status: "running" | "done" | "error" | "cancelled";
  result: any;
  error: string | null;
  meta: Record<string, any>;
  created_at: number;
  updated_at: number;
}