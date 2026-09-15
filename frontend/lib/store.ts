import { create } from "zustand";
import type { OrderResponse, TraceEntry } from "./api";

interface OrderStore {
  orders: OrderResponse[];
  currentOrder: OrderResponse | null;
  liveTraces: TraceEntry[];
  setOrders: (orders: OrderResponse[]) => void;
  setCurrentOrder: (order: OrderResponse | null) => void;
  setLiveTraces: (traces: TraceEntry[]) => void;
  appendTraceStep: (trace: TraceEntry) => void;
  addLiveTrace: (trace: TraceEntry) => void;
  clearLiveTraces: () => void;
}

function sameStep(a: TraceEntry, b: TraceEntry): boolean {
  if (a.id && b.id && a.id === b.id) return true;
  return a.step_number === b.step_number && a.agent_name === b.agent_name;
}

export const useOrderStore = create<OrderStore>((set) => ({
  orders: [],
  currentOrder: null,
  liveTraces: [],
  setOrders: (orders) => set({ orders }),
  setCurrentOrder: (order) => set({ currentOrder: order, liveTraces: order?.traces ?? [] }),
  setLiveTraces: (traces) => set({ liveTraces: traces }),
  appendTraceStep: (trace) =>
    set((s) => (s.liveTraces.some((t) => sameStep(t, trace)) ? s : { liveTraces: [...s.liveTraces, trace] })),
  addLiveTrace: (trace) =>
    set((s) => (s.liveTraces.some((t) => sameStep(t, trace)) ? s : { liveTraces: [...s.liveTraces, trace] })),
  clearLiveTraces: () => set({ liveTraces: [] }),
}));
