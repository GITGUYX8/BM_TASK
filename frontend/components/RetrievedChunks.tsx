"use client";

import type { TraceEntry } from "@/lib/api";

interface Chunk {
  document_title?: string;
  chunk_text?: string;
  snippet?: string;
  fused_score?: number;
  vector_score?: number;
  keyword_score?: number;
  score?: number;
}

function extractChunks(trace: TraceEntry): Chunk[] {
  const out = trace.output_json;
  if (!out || typeof out !== "object") return [];
  const candidates = ["chunks", "retrieved_chunks", "results"];
  for (const key of candidates) {
    const val = (out as Record<string, unknown>)[key];
    if (Array.isArray(val)) return val as Chunk[];
  }
  return [];
}

export default function RetrievedChunks({ trace }: { trace: TraceEntry }) {
  const chunks = extractChunks(trace);
  if (chunks.length === 0) return null;

  return (
    <details style={{ marginTop: 8, background: "#f8fafc", borderRadius: 4, padding: 8 }}>
      <summary style={{ cursor: "pointer", fontSize: 13 }}>
        Show source chunks ({chunks.length})
      </summary>
      <ul style={{ marginTop: 8, paddingLeft: 18, fontSize: 13 }}>
        {chunks.map((c, i) => {
          const score = c.fused_score ?? c.score ?? c.vector_score ?? null;
          return (
            <li key={i} style={{ marginBottom: 8 }}>
              <strong>{c.document_title ?? `Chunk ${i + 1}`}</strong>
              {score != null && <span style={{ color: "#666" }}> — score {Number(score).toFixed(3)}</span>}
              {(c.vector_score != null || c.keyword_score != null) && (
                <span style={{ color: "#666", fontSize: 12 }}>
                  {" "}
                  (vector {Number(c.vector_score ?? 0).toFixed(3)} / keyword {Number(c.keyword_score ?? 0).toFixed(3)})
                </span>
              )}
              <br />
              <span style={{ color: "#334155" }}>
                {(c.chunk_text ?? c.snippet ?? "").slice(0, 300)}
                {(c.chunk_text ?? c.snippet ?? "").length > 300 ? "…" : ""}
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
