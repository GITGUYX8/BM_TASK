"use client";

import { useCallback, useEffect, useState } from "react";
import { getOrder, streamOrder, retryOrder, ApiError } from "@/lib/api";
import type { OrderResponse, TraceEntry } from "@/lib/api";
import TraceTimeline from "@/components/TraceTimeline";
import StatusBadge from "@/components/StatusBadge";
import CostBar from "@/components/CostBar";

function appendDedup(prev: TraceEntry[], trace: TraceEntry): TraceEntry[] {
  if (prev.some((t) => (t.id && trace.id && t.id === trace.id) || (t.step_number === trace.step_number && t.agent_name === trace.agent_name))) {
    return prev;
  }
  return [...prev, trace];
}

export default function OrderDetailPage({ params }: { params: { id: string } }) {
  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [traces, setTraces] = useState<TraceEntry[]>([]);
  const [status, setStatus] = useState("loading");
  const [streamError, setStreamError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [retrying, setRetrying] = useState(false);

  const handleStep = useCallback((event: MessageEvent) => {
    try {
      const trace = JSON.parse(event.data) as TraceEntry;
      if (typeof trace.step_number !== "number" || !trace.agent_name) return;
      setTraces((prev) => appendDedup(prev, trace));
    } catch {
      // ignore malformed frames
    }
  }, []);

  const handleTerminal = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as { status?: string };
        if (data.status) setStatus(data.status);
      } catch {
        setStatus(event.type === "error" ? "failed" : "done");
      }
      getOrder(params.id)
        .then((o) => {
          setOrder(o);
          setTraces(o.traces);
        })
        .catch(() => undefined);
    },
    [params.id],
  );

  useEffect(() => {
    getOrder(params.id)
      .then((o) => {
        setOrder(o);
        setTraces(o.traces);
        if (["completed", "failed", "escalated"].includes(o.status)) {
          setStatus(o.status);
        }
      })
      .catch((e) => {
        setLoadError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
        setStatus("error");
      });

    const es = streamOrder(params.id);

    es.addEventListener("step", handleStep as EventListener);
    // Backward compat: pre-WS4 servers send bare `data:` frames (onmessage)
    es.onmessage = (event) => handleStep(event as MessageEvent);
    es.addEventListener("complete", handleTerminal as EventListener);
    es.addEventListener("error", handleTerminal as EventListener);
    // Legacy alias kept by the backend
    es.addEventListener("done", handleTerminal as EventListener);

    es.onerror = () => {
      // EventSource fires onerror on close as well; only flag if not terminal
      setStreamError((prev) => prev || "");
    };

    return () => es.close();
  }, [params.id, handleStep, handleTerminal]);

  async function handleRetry() {
    setRetrying(true);
    setStreamError("");
    try {
      const o = await retryOrder(params.id);
      setOrder(o);
      setTraces(o.traces);
      setStatus(o.status);
    } catch (e) {
      setStreamError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setRetrying(false);
    }
  }

  if (loadError) return <p style={{ color: "red" }}>Failed to load order: {loadError}</p>;
  if (!order) return <p>Loading...</p>;

  const displayStatus = status === "loading" ? order.status : status;
  const canRetry = ["failed", "escalated"].includes(order.status) || ["failed", "escalated", "error"].includes(displayStatus);

  return (
    <div>
      <h2>{order.title}</h2>
      <p>{order.description}</p>
      <div style={{ display: "flex", gap: 16, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        <span>
          Status: <StatusBadge status={displayStatus} />
        </span>
        <span>Priority: {order.priority}</span>
        <CostBar cost={Number(order.cumulative_cost)} />
        <span>Steps: {traces.length}</span>
        {canRetry && (
          <button onClick={handleRetry} disabled={retrying}>
            {retrying ? "Retrying..." : "Retry order"}
          </button>
        )}
      </div>
      {streamError && <p style={{ color: "red" }}>{streamError}</p>}
      {order.error_trace && (
        <pre style={{ background: "#fee", padding: 8, borderRadius: 4 }}>
          {JSON.stringify(order.error_trace, null, 2)}
        </pre>
      )}
      <h3>Agent Traces</h3>
      <TraceTimeline traces={traces} />
    </div>
  );
}
