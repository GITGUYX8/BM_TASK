"use client";

import { useEffect } from "react";
import { listOrders } from "@/lib/api";
import { useOrderStore as useStore } from "@/lib/store";

export default function OrderList() {
  const orders = useStore((s) => s.orders);
  const setOrders = useStore((s) => s.setOrders);

  useEffect(() => {
    listOrders().then(setOrders).catch(console.error);
  }, [setOrders]);

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
          <strong>{o.title}</strong> — <span style={{ color: "#666" }}>{o.status}</span>
          <br />
          <small>
            {o.priority} priority | ${Number(o.cumulative_cost).toFixed(4)} | {o.step_count} steps
          </small>
        </a>
      ))}
    </div>
  );
}
