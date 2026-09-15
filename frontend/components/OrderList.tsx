"use client";

import { useEffect, useState } from "react";
import { listOrders, ApiError } from "@/lib/api";
import { useOrderStore as useStore } from "@/lib/store";
import StatusBadge from "./StatusBadge";

export default function OrderList({ statusFilter }: { statusFilter?: string }) {
  const orders = useStore((s) => s.orders);
  const setOrders = useStore((s) => s.setOrders);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    listOrders(statusFilter).then(setOrders).catch((e) => {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    });
  }, [setOrders, statusFilter]);

  if (error) return <p style={{ color: "red" }}>Failed to load orders: {error}</p>;
  if (orders.length === 0) return <p>No orders submitted yet.</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {orders.map((o) => (
        <a
          key={o.order_id}
          href={`/orders/${o.order_id}`}
          style={{
            textDecoration: "none",
            color: "inherit",
            border: "1px solid #ddd",
            borderRadius: 6,
            padding: 12,
          }}
        >
          <strong>{o.title}</strong> — <StatusBadge status={o.status} />
          <br />
          <small>
            {o.priority} priority | ${Number(o.cumulative_cost).toFixed(4)} | {o.step_count} steps
          </small>
        </a>
      ))}
    </div>
  );
}
