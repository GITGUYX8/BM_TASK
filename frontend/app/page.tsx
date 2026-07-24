import OrderForm from "@/components/OrderForm";
import OrderList from "@/components/OrderList";

export default function Home() {
  return (
    <div style={{ display: "flex", gap: 32 }}>
      <div style={{ flex: 1 }}>
        <OrderForm />
      </div>
      <div style={{ flex: 2 }}>
        <h2>Recent Orders</h2>
        <OrderList />
      </div>
    </div>
  );
}
