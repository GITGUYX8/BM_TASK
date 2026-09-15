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

export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(`${body.code}: ${body.message}`);
    this.name = "ApiError";
    this.code = body.code;
    this.status = status;
    this.details = body.details ?? {};
  }
}

const API = "/api";

async function parseOrThrow(res: Response): Promise<unknown> {
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (data && typeof data === "object" && "error" in data) {
      const err = (data as { error: ApiErrorBody }).error;
      throw new ApiError(res.status, {
        code: err.code ?? "INTERNAL_ERROR",
        message: err.message ?? `Request failed: ${res.status}`,
        details: err.details ?? {},
      });
    }
    throw new Error(`Request failed: ${res.status}`);
  }
  return data;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function createOrder(
  title: string,
  description: string,
  priority: string,
  idempotencyKey?: string,
): Promise<OrderResponse> {
  const res = await fetch(`${API}/orders`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey ?? newIdempotencyKey(),
    },
    body: JSON.stringify({ title, description, priority }),
  });
  return (await parseOrThrow(res)) as OrderResponse;
}

export async function listOrders(status?: string): Promise<OrderResponse[]> {
  const url = status ? `${API}/orders?status=${encodeURIComponent(status)}` : `${API}/orders`;
  const res = await fetch(url);
  return (await parseOrThrow(res)) as OrderResponse[];
}

export async function getOrder(orderId: string): Promise<OrderResponse> {
  const res = await fetch(`${API}/orders/${orderId}`);
  return (await parseOrThrow(res)) as OrderResponse;
}

export async function retryOrder(orderId: string): Promise<OrderResponse> {
  const res = await fetch(`${API}/orders/${orderId}/retry`, { method: "POST" });
  return (await parseOrThrow(res)) as OrderResponse;
}

export function streamOrder(orderId: string): EventSource {
  return new EventSource(`${API}/orders/${orderId}/stream`);
}
