const API = "/api";

export interface OrderResponse {
  order_id: string;
  title: string;
  description: string;
  priority: string;
  status: string;
  cumulative_cost: number;
  step_count: number;
  traces: TraceEntry[];
  error_trace: Record<string, string> | null;
  created_at: string;
  updated_at: string;
}

export interface TraceEntry {
  id: string;
  agent_name: string;
  step_number: number;
  input_summary: string;
  output_summary: string;
  output_json: Record<string, unknown> | null;
  latency_ms: number;
  cost_usd: number;
  confidence: number | null;
  status: string;
  model_used: string;
  cache_hit: boolean;
}

export async function createOrder(title: string, description: string, priority: string): Promise<OrderResponse> {
  const res = await fetch(`${API}/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, description, priority }),
  });
  if (!res.ok) throw new Error(`createOrder failed: ${res.status}`);
  return res.json();
}

export async function listOrders(): Promise<OrderResponse[]> {
  const res = await fetch(`${API}/orders`);
  if (!res.ok) throw new Error(`listOrders failed: ${res.status}`);
  return res.json();
}

export async function getOrder(orderId: string): Promise<OrderResponse> {
  const res = await fetch(`${API}/orders/${orderId}`);
  if (!res.ok) throw new Error(`getOrder failed: ${res.status}`);
  return res.json();
}

export function streamOrder(orderId: string): EventSource {
  return new EventSource(`${API}/orders/${orderId}/stream`);
}
