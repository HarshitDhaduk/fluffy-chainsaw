import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LalFita",
  description: "The agent that cuts through red tape",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <a href="/">
            <strong>🪔 LalFita</strong> <span className="tagline">cuts through red tape</span>
          </a>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
