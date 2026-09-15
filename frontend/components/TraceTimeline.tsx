"use client";

import type { TraceEntry } from "@/lib/api";
import RetrievedChunks from "./RetrievedChunks";

export default function TraceTimeline({ traces }: { traces: TraceEntry[] }) {
  if (traces.length === 0) {
    return <p>No agent traces yet. Processing...</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {traces.map((t, i) => (
        <details key={t.id || i} style={{ border: "1px solid #ccc", borderRadius: 6, padding: 8 }}>
          <summary>
            <strong>{t.agent_name}</strong> — step {t.step_number}
            <span style={{ marginLeft: 12, color: t.status === "ok" ? "green" : "red" }}>{t.status}</span>
            <span style={{ marginLeft: 12, fontSize: 12, color: "#666" }}>{t.latency_ms}ms</span>
            {t.confidence != null && (
              <span style={{ marginLeft: 12, fontSize: 12 }}>confidence: {(t.confidence * 100).toFixed(0)}%</span>
            )}
            {t.cache_hit && (
              <span style={{ marginLeft: 12, fontSize: 12, color: "blue" }}>cached</span>
            )}
          </summary>
          <div style={{ marginTop: 8, fontSize: 14 }}>
            <p><strong>Input:</strong> {t.input_summary}</p>
            <p><strong>Output:</strong> {t.output_summary}</p>
            {t.cost_usd > 0 && <p><strong>Cost:</strong> ${Number(t.cost_usd).toFixed(6)}</p>}
            {t.model_used && <p><strong>Model:</strong> {t.model_used}</p>}
            {t.cache_hit && <p style={{ color: "blue" }}>Served from LLM cache</p>}
            <RetrievedChunks trace={t} />
          </div>
        </details>
      ))}
    </div>
  );
}
