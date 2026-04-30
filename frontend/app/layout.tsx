import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Link from "next/link";
import { NavWalletButton } from "./components/dashboard/NavWalletButton";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "MasG EV Tool",
  description: "Cross-platform EV scanner for prediction market opportunities",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        className={`${inter.className} min-h-screen`}
        style={{ background: "#07090a", color: "#e2e8f0" }}
      >
        <header
          className="h-12 flex items-center px-6 border-b"
          style={{ borderColor: "rgba(19,78,74,0.3)", background: "#080b0c" }}
        >
          <div className="flex items-center gap-2.5 mr-10">
            <span style={{ color: "#2dd4bf" }} className="text-base leading-none">&#9670;</span>
            <span
              className="font-mono font-bold text-[13px] tracking-[0.2em] uppercase"
              style={{ color: "#e2e8f0" }}
            >
              MasG EV
            </span>
            <span
              className="font-mono text-[8px] tracking-wider px-1.5 py-0.5 rounded uppercase ml-1"
              style={{ color: "#374151", background: "rgba(75,85,99,0.08)" }}
            >
              Beta
            </span>
          </div>

          <nav className="flex items-center gap-6">
            <Link
              href="/"
              className="nav-link text-[11px] font-mono tracking-widest uppercase transition-colors"
              style={{ color: "#4b7280" }}
            >
              Scanner
            </Link>
            <Link
              href="/model"
              className="nav-link text-[11px] font-mono tracking-widest uppercase transition-colors"
              style={{ color: "#4b7280" }}
            >
              Model
            </Link>
          </nav>

          <div className="ml-auto flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span
                className="w-1.5 h-1.5 rounded-full animate-pulse"
                style={{ background: "#4ade80", boxShadow: "0 0 6px #4ade80" }}
              />
              <span className="font-mono text-[10px] tracking-wider uppercase" style={{ color: "#374151" }}>
                Scanning
              </span>
            </div>
            <div className="h-4 w-px" style={{ background: "rgba(75,85,99,0.3)" }} />
            <NavWalletButton />
          </div>
        </header>

        {children}
      </body>
    </html>
  );
}
