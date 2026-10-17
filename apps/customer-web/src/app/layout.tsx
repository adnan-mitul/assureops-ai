import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { CustomerShell } from "@/components/CustomerShell";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AssureOps AI",
  description: "Continuous readiness assurance for AI agent applications",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="flex min-h-full font-sans">
        <CustomerShell>{children}</CustomerShell>
      </body>
    </html>
  );
}
