import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Riverbend Patient Portal",
  description: "Patient intake + records for Riverbend Community Health",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          background: "#f5f7fa",
          color: "#1a2b3c",
        }}
      >
        <header
          style={{
            background: "#0b5d8a",
            color: "white",
            padding: "16px 24px",
            fontWeight: 600,
          }}
        >
          Riverbend Community Health — Patient Portal
        </header>
        <main style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
          {children}
        </main>
      </body>
    </html>
  );
}
