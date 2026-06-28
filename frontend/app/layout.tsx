import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import AppShell from "./components/AppShell";

export const metadata: Metadata = {
  title: "Riverbend Patient Portal",
  description:
    "Riverbend Community Health — manage appointments, records, intake, and records releases online.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
