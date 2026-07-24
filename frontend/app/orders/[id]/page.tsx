"use client";

import { useEffect, useState } from "react";
import { getOrder, streamOrder } from "@/lib/api";
import type { OrderResponse, TraceEntry } from "@/lib/api";
import TraceTimeline from "@/components/TraceTimeline";

export default function OrderDetailPage({ params }: { params: { id: string } }) {
  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [traces, setTraces] = useState<TraceEntry[]>([]);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    getOrder(params.id).then((o) => {
      setOrder(o);
      setTraces(o.traces);
    }).catch(console.error);

    const es = streamOrder(params.id);

    es.addEventListener("done", () => {
      setStatus("done");
      es.close();
    });

    es.onmessage = (event) => {
      try {
        const trace = JSON.parse(event.data) as TraceEntry;
        setTraces((prev) => {
          if (prev.some((t) => t.step_number === trace.step_number && t.agent_name === trace.agent_name)) {
            return prev;
          }
          return [...prev, trace];
        });
      } catch {
        // ignore
      }
    };

    es.onerror = () => {
      setStatus("error");
    };

    return () => es.close();
  }, [params.id]);

  if (!order) return <p>Loading...</p>;

  return (
    <div>
      <h2>{order.title}</h2>
      <p>{order.description}</p>
      <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
        <span>Status: <strong>{status === "loading" ? order.status : status}</strong></span>
        <span>Priority: {order.priority}</span>
        <span>Cost: ${Number(order.cumulative_cost).toFixed(6)}</span>
        <span>Steps: {traces.length}</span>
      </div>
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
