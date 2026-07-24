import { create } from "zustand";
import type { OrderResponse } from "./api";

interface OrderStore {
  orders: OrderResponse[];
  currentOrder: OrderResponse | null;
  liveTraces: unknown[];
  setOrders: (orders: OrderResponse[]) => void;
  setCurrentOrder: (order: OrderResponse | null) => void;
  addLiveTrace: (trace: unknown) => void;
  clearLiveTraces: () => void;
}

export const useOrderStore = create<OrderStore>((set) => ({
  orders: [],
  currentOrder: null,
  liveTraces: [],
  setOrders: (orders) => set({ orders }),
  setCurrentOrder: (order) => set({ currentOrder: order, liveTraces: order?.traces ?? [] }),
  addLiveTrace: (trace) => set((s) => ({ liveTraces: [...s.liveTraces, trace] })),
  clearLiveTraces: () => set({ liveTraces: [] }),
}));
