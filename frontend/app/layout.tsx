import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Self-hosted (see app/fonts/LICENSES.txt) so `pnpm build` works with no network: venue wifi is not a dependency.
const display = localFont({
  variable: "--font-instrument-serif",
  display: "swap",
  src: [
    { path: "./fonts/instrument-serif-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/instrument-serif-latin-400-italic.woff2", weight: "400", style: "italic" },
  ],
  fallback: ["Iowan Old Style", "Palatino Linotype", "Georgia", "serif"],
});

const sans = localFont({
  variable: "--font-instrument-sans",
  display: "swap",
  src: [
    { path: "./fonts/instrument-sans-latin-wght-normal.woff2", weight: "400 700", style: "normal" },
    { path: "./fonts/instrument-sans-latin-wght-italic.woff2", weight: "400 700", style: "italic" },
  ],
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

const mono = localFont({
  variable: "--font-dm-mono",
  display: "swap",
  src: [
    { path: "./fonts/dm-mono-latin-300-normal.woff2", weight: "300", style: "normal" },
    { path: "./fonts/dm-mono-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/dm-mono-latin-500-normal.woff2", weight: "500", style: "normal" },
  ],
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
});

export const metadata: Metadata = {
  title: { default: "Whitespace: how original is your idea?", template: "%s · Whitespace" },
  description: "A swarm of AI agents charts the prior art around your idea, verifies every claim against its source, and coaches you toward the empty regions of the map.",
};

export const viewport: Viewport = { themeColor: "#04060b", colorScheme: "dark" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
