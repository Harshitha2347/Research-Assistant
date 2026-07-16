import { useEffect, useState } from "react";

import { evaluationHistory, getEvaluationPairs, listConversations } from "../api/client";

import {
  ConversationSummary,
  EvaluationPair,
  EvaluationResult,
} from "../types";
import { useEvaluationJob } from "../context/JobsContext";

const METRIC_LABELS: Record<string, string> = {
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer Relevancy",
  context_precision: "Context Precision",
  context_recall: "Context Recall",
};

function Bar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) {
   
    return <div className="w-full bg-surface-100 rounded-full h-2" title="Couldn't be computed for this evaluation" />;
  }
  const pct = Math.max(0, Math.min(100, value * 100));
  const color = pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-500";

  return (
    <div className="w-full bg-surface-100 rounded-full h-2">
      <div className={`${color} h-2 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function Evaluation() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConv, setSelectedConv] = useState("");
  const [pairs, setPairs] = useState<EvaluationPair[]>([]);
  const [selectedPairs, setSelectedPairs] = useState<number[]>([]);
  const [history, setHistory] = useState<EvaluationResult[]>([]);
  const [validationError, setValidationError] = useState("");

  // Evaluation progress lives above this page (see context/JobsContext.tsx)
  // so a running RAGAS job — which can take a while, since each Q&A pair
  // needs several LLM calls — keeps showing as running (and refreshes
  // history the moment it finishes) even if the user checks another tab
  // while it works.
  const { evalRunning, evalStatus, evalMessage, evalCompletedAt, startEvaluation, stopEvaluation } =
    useEvaluationJob();
  const error = validationError || (evalStatus === "error" ? evalMessage : "");

  const refreshHistory = () => evaluationHistory().then((r) => setHistory(r.data));

  useEffect(() => {
    listConversations().then((r) => setConversations(r.data));
    refreshHistory();
  }, []);


  useEffect(() => {
    if (evalCompletedAt) refreshHistory();
  }, [evalCompletedAt]);

  useEffect(() => {
    if (!selectedConv) {
      setPairs([]);
      setSelectedPairs([]);
      return;
    }
    getEvaluationPairs(selectedConv)
      .then((r) => {
        setPairs(r.data);
        setSelectedPairs([]);
      })
      .catch(() => setPairs([]));
  }, [selectedConv]);

  const togglePair = (index: number) => {
    setSelectedPairs((prev) => (prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index]));
  };

  const selectAll = () => setSelectedPairs(pairs.map((p) => p.index));
  const clearAll = () => setSelectedPairs([]);

  const onRun = () => {
    if (!selectedConv) return;
    if (selectedPairs.length === 0) {
      setValidationError("Select at least one Q&A pair.");
      return;
    }
    setValidationError("");
    startEvaluation(selectedConv, selectedPairs);
  };


  const estimatedCalls = selectedPairs.length * 5;

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6 w-full">
      <div className="card p-6">
        <h2 className="font-display font-semibold text-surface-900 text-lg">RAGAS Evaluation</h2>
        <p className="text-sm text-surface-500 mt-1">
          Select a conversation, choose the Q&A pairs you want to evaluate, then run RAGAS only on those pairs.
        </p>

        <div className="mt-5">
          <label className="text-sm font-medium text-surface-700">Conversation</label>
          <select
            value={selectedConv}
            onChange={(e) => setSelectedConv(e.target.value)}
            className="input-field mt-2"
          >
            <option value="">Select a conversation...</option>
            {conversations.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title || c.id}
              </option>
            ))}
          </select>
        </div>

        {selectedConv && (
          <div className="mt-6">
            <div className="flex justify-between items-center mb-3">
              <h3 className="font-medium text-surface-800">Conversation Q&A Pairs</h3>
              {pairs.length > 0 && (
                <div className="space-x-2">
                  <button onClick={selectAll} className="btn-ghost border border-surface-200">
                    Select All
                  </button>
                  <button onClick={clearAll} className="btn-ghost border border-surface-200">
                    Clear
                  </button>
                </div>
              )}
            </div>

            {pairs.length === 0 ? (
              <p className="text-sm text-surface-400">No Q&A pairs found.</p>
            ) : (
              <div className="border border-surface-200 rounded-xl max-h-96 overflow-y-auto scroll-thin divide-y divide-surface-100">
                {pairs.map((pair) => (
                  <label
                    key={pair.index}
                    className="flex gap-3 p-4 hover:bg-surface-50 cursor-pointer transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={selectedPairs.includes(pair.index)}
                      onChange={() => togglePair(pair.index)}
                      className="mt-1 accent-brand-600"
                    />
                    <div className="flex-1">
                      <p className="font-medium text-sm text-surface-800">Pair #{pair.index + 1}</p>
                      <p className="text-sm text-surface-700 mt-2">
                        <span className="font-semibold">Question:</span> {pair.question}
                      </p>
                      <p className="text-sm text-surface-500 mt-2">
                        <span className="font-semibold">Answer:</span> {pair.answer}
                      </p>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="mt-6 flex items-center gap-3 flex-wrap">
          <button
            onClick={onRun}
            disabled={evalRunning || !selectedConv || selectedPairs.length === 0}
            className="btn-primary"
          >
            {evalRunning ? "Running evaluation…" : `Run Evaluation (${selectedPairs.length})`}
          </button>
          {evalRunning && (
            <button onClick={stopEvaluation} className="btn-ghost border border-surface-200 text-surface-600">
              Stop
            </button>
          )}
          {selectedPairs.length > 0 && !evalRunning && (
            <span className="text-xs text-surface-400">
              ~{estimatedCalls} LLM calls expected — RAGAS's metrics each verify the answer from a few angles
            </span>
          )}
          {evalRunning && (
            <span className="text-xs text-surface-400">
              Running in the background, one pair at a time — feel free to check another tab, or stop it above.
            </span>
          )}
          {evalStatus === "cancelled" && (
            <span className="text-xs text-surface-400">{evalMessage}</span>
          )}
        </div>

        {error && <p className="mt-4 text-red-600 text-sm">{error}</p>}
      </div>

      <div className="card p-6">
        <h3 className="font-display font-semibold text-surface-900 mb-5">Evaluation History</h3>

        {history.length === 0 ? (
          <p className="text-surface-400 text-sm">No evaluations yet.</p>
        ) : (
          <div className="space-y-6">
            {history.map((h) => (
              <div key={h.id} className="border-b border-surface-100 last:border-0 pb-5">
                <div className="flex items-center justify-between gap-3 mb-1">
                  <p className="text-sm font-medium text-surface-700 truncate">
                    {h.conversation_title || "Untitled conversation"}
                  </p>
                  {h.pair_indices && h.pair_indices.length > 0 && (
                    <span className="badge bg-surface-100 text-surface-500 shrink-0">
                      {h.pair_indices.length} pair{h.pair_indices.length > 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                <p className="text-xs text-surface-400 mb-3">{new Date(h.created_at).toLocaleString()}</p>
                <div className="grid grid-cols-2 gap-4">
                  {(["faithfulness", "answer_relevancy", "context_precision", "context_recall"] as const).map((key) => (
                    <div key={key}>
                      <div className="flex justify-between text-xs mb-1 text-surface-600">
                        <span>{METRIC_LABELS[key]}</span>
                        <span>{h[key] === null || h[key] === undefined ? "—" : `${(h[key]! * 100).toFixed(0)}%`}</span>
                      </div>
                      <Bar value={h[key]} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
