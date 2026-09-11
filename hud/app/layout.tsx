import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Butler — HUD",
  description: "Local-only Butler command HUD (FastAPI :8000 backend)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
