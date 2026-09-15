"use client";

export const COST_CEILING = 0.05;

export default function CostBar({ cost, ceiling = COST_CEILING }: { cost: number; ceiling?: number }) {
  const pct = Math.min(100, (cost / ceiling) * 100);
  const color = pct >= 100 ? "#dc2626" : pct >= 70 ? "#d97706" : "#16a34a";
  const over = cost > ceiling;

  return (
    <div style={{ minWidth: 220 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
        <span>
          Cost: <strong>${cost.toFixed(6)} / ${ceiling.toFixed(2)}</strong>
        </span>
        <span style={{ color }}>{pct.toFixed(0)}%</span>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: "#e5e7eb", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.3s" }} />
      </div>
      {over && <p style={{ fontSize: 12, color: "#dc2626", marginTop: 4 }}>Budget exceeded — remaining steps use cheap model tier.</p>}
    </div>
  );
}
