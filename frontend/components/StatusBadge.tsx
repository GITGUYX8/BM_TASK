"use client";

const COLORS: Record<string, string> = {
  queued: "#6b7280",
  processing: "#2563eb",
  completed: "#16a34a",
  failed: "#dc2626",
  escalated: "#d97706",
};

export default function StatusBadge({ status }: { status: string }) {
  const color = COLORS[status] ?? "#6b7280";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        color: "#fff",
        background: color,
      }}
    >
      {status}
    </span>
  );
}
