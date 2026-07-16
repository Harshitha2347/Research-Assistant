import { DragEvent, useEffect, useRef, useState } from "react";
import { deleteDocument, listDocuments } from "../api/client";
import { DocumentRecord } from "../types";
import { useSummaryJobs, useUpload } from "../context/JobsContext";

const icons = {
  upload: (
    <svg viewBox="0 0 24 24" fill="none" className="w-6 h-6">
      <path d="M12 15V4M12 4 8 8M12 4l4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  pdf: (
    <svg viewBox="0 0 20 20" fill="none" className="w-5 h-5 shrink-0">
      <path d="M5 2.5h6.17L15 6.33V17.5H5V2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M11 2.5V6.5H15" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  ),
  trash: (
    <svg viewBox="0 0 20 20" fill="none" className="w-3.5 h-3.5">
      <path d="M4 6h12M8 6V4.5A1.5 1.5 0 0 1 9.5 3h1A1.5 1.5 0 0 1 12 4.5V6M6 6l.6 9a1.5 1.5 0 0 0 1.5 1.4h3.8a1.5 1.5 0 0 0 1.5-1.4L14 6"
        stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  spark: (
    <svg viewBox="0 0 20 20" fill="none" className="w-3.5 h-3.5">
      <path d="M10 2.5 11.4 7.6 16.5 9 11.4 10.4 10 15.5 8.6 10.4 3.5 9l5.1-1.4L10 2.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  ),
  check: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M4 10.5 8 14.5 16 5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

function StatusBadge({ status }: { status: DocumentRecord["status"] }) {
  const map: Record<string, string> = {
    ready: "bg-emerald-50 text-emerald-600",
    processing: "bg-amber-50 text-amber-600",
    failed: "bg-red-50 text-red-600",
  };
  return (
    <span className={`badge ${map[status] || "bg-surface-100 text-surface-500"}`}>
      {status === "processing" && (
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse-soft" />
      )}
      {status}
    </span>
  );
}

export default function Documents() {
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const fileInput = useRef<HTMLInputElement>(null);

  const { phase, progress, fileCount, error, completedAt, startUpload } = useUpload();
  const {
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
  } = useSummaryJobs();

  const refresh = async () => {
    const res = await listDocuments();
    setDocs(res.data);
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (completedAt) refresh();
  }, [completedAt]);

  const onUpload = (files: FileList | File[] | null) => {
    const list = files ? Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".pdf")) : [];
    if (list.length === 0) return;
    startUpload(list);
    if (fileInput.current) fileInput.current.value = "";
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    onUpload(e.dataTransfer.files);
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const onDelete = async (id: string) => {
    await deleteDocument(id);
    await refresh();
  };

  const onSummarise = (id: string) => startSummarise(id);

  const onCompare = () => {
    if (selected.size < 2) return;
    startCompare(Array.from(selected));
  };

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6 w-full">
      <div className="card p-6">
        <h2 className="font-display font-semibold text-surface-900 mb-1">Upload PDFs</h2>
        <p className="text-sm text-surface-500 mb-4">
          Upload one or more PDFs. Text, images, and figure metadata are extracted and indexed automatically.
        </p>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          onClick={() => fileInput.current?.click()}
          className={`rounded-xl border-2 border-dashed px-6 py-8 text-center cursor-pointer transition-colors ${
            dragActive ? "border-brand-400 bg-brand-50" : "border-surface-200 hover:border-brand-300 hover:bg-surface-50"
          }`}
        >
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            multiple
            onChange={(e) => onUpload(e.target.files)}
            className="hidden"
          />
          <div className="w-10 h-10 mx-auto rounded-xl bg-brand-50 text-brand-600 flex items-center justify-center mb-3">
            {icons.upload}
          </div>
          <p className="text-sm font-medium text-surface-700">Drop PDFs here, or click to browse</p>
          <p className="text-xs text-surface-400 mt-1">Multiple files supported</p>
        </div>

        {phase !== "idle" && (
          <div className="mt-4 animate-fade-in">
            <div className="flex justify-between text-xs text-surface-500 mb-1.5">
              <span>
                {phase === "uploading"
                  ? `Uploading ${fileCount} file${fileCount > 1 ? "s" : ""}…`
                  : "Extracting text & figures, indexing…"}
              </span>
              {phase === "uploading" && <span>{progress}%</span>}
            </div>
            <div className="w-full h-1.5 rounded-full bg-surface-100 overflow-hidden">
              {phase === "uploading" ? (
                <div
                  className="h-full rounded-full bg-brand-gradient transition-all duration-150"
                  style={{ width: `${progress}%` }}
                />
              ) : (
                <div className="h-full w-1/3 rounded-full bg-brand-gradient animate-[pulseSoft_1.2s_ease-in-out_infinite]" />
              )}
            </div>
          </div>
        )}
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>

      <div className="card p-6">
        <div className="flex items-center justify-between mb-1">
          <h2 className="font-display font-semibold text-surface-900">Your documents</h2>
          {selected.size >= 2 && (
            <button onClick={onCompare} disabled={comparisonLoading} className="btn-primary text-sm px-3.5 py-2">
              {comparisonLoading ? "Comparing…" : `Compare selected (${selected.size})`}
            </button>
          )}
        </div>
        <p className="text-xs text-surface-400 mb-4">Click a document's icon to select it for comparison (pick 2 or more).</p>
        {docs.length === 0 && <p className="text-sm text-surface-400">No documents uploaded yet.</p>}
        <ul className="divide-y divide-surface-100">
          {docs.map((d) => (
            <li key={d.id} className="py-3.5 flex items-center gap-3">
              <button
                type="button"
                onClick={() => toggleSelect(d.id)}
                title={selected.has(d.id) ? "Selected for comparison — click to deselect" : "Click to select for comparison"}
                className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-colors ${
                  selected.has(d.id)
                    ? "bg-brand-600 text-white"
                    : "bg-surface-100 text-surface-500 hover:bg-brand-50 hover:text-brand-600"
                }`}
              >
                {selected.has(d.id) ? icons.check : icons.pdf}
              </button>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-surface-800 truncate">{d.filename}</p>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <StatusBadge status={d.status} />
                  <p className="text-xs text-surface-400">
                    {d.num_pages} pages · {d.num_chunks} chunks · {d.num_figures} figures
                  </p>
                  {d.status === "ready" && d.num_chunks === 0 && d.num_figures === 0 && (
                    <span
                      className="badge bg-red-50 text-red-600"
                      title="No text or figures were indexed for this document — questions about it won't return anything. Check the backend terminal for an [ingestion] warning, or try re-uploading."
                    >
                      nothing indexed
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => onSummarise(d.id)}
                disabled={(summaryLoading && summaryDocId === d.id) || d.status !== "ready"}
                className="btn-ghost text-brand-600 disabled:opacity-40"
              >
                {icons.spark}
                {summaryLoading && summaryDocId === d.id ? "Summarising…" : "Summarise"}
              </button>
              <button onClick={() => onDelete(d.id)} className="btn-ghost text-red-500 hover:bg-red-50">
                {icons.trash}
                Delete
              </button>
            </li>
          ))}
        </ul>
      </div>

      {(summaryLoading || summaryText || summaryError) && (
        <div className="card p-6 animate-fade-in-up">
          <h3 className="font-display font-semibold text-surface-900 mb-2">
            Summary{" "}
            {summaryDocId && (
              <span className="font-normal text-surface-400">
                — {docs.find((d) => d.id === summaryDocId)?.filename ?? "document"}
              </span>
            )}
          </h3>
          {summaryLoading && (
            <p className="text-sm text-surface-400 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse-soft" />
              Generating summary — this keeps running even if you switch tabs…
            </p>
          )}
          {summaryError && <p className="text-sm text-red-600">{summaryError}</p>}
          {summaryText && !summaryLoading && (
            <p className="text-sm text-surface-700 whitespace-pre-wrap leading-relaxed">{summaryText}</p>
          )}
        </div>
      )}

      {(comparisonLoading || comparisonText || comparisonError) && (
        <div className="card p-6 animate-fade-in-up">
          <h3 className="font-display font-semibold text-surface-900 mb-2">
            Comparison{" "}
            {comparisonIds.length > 0 && (
              <span className="font-normal text-surface-400">
                —{" "}
                {comparisonIds
                  .map((id) => docs.find((d) => d.id === id)?.filename ?? "document")
                  .join(", ")}
              </span>
            )}
          </h3>
          {comparisonLoading && (
            <p className="text-sm text-surface-400 flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse-soft" />
              Comparing documents — this keeps running even if you switch tabs…
            </p>
          )}
          {comparisonError && <p className="text-sm text-red-600">{comparisonError}</p>}
          {comparisonText && !comparisonLoading && (
            <p className="text-sm text-surface-700 whitespace-pre-wrap leading-relaxed">{comparisonText}</p>
          )}
        </div>
      )}
    </div>
  );
}
