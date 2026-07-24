import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "BM Build — Work Order Processor",
  description: "AI-powered work order processing system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
        <header style={{ marginBottom: "2rem" }}>
          <h1>BM Build</h1>
          <nav style={{ display: "flex", gap: 16 }}>
            <a href="/">Home</a>
            <a href="/orders">Orders</a>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
