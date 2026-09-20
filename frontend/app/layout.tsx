import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// One typeface, Instrument Sans, for everything. Self-hosted (see app/fonts/LICENSES.txt) so `pnpm build` works with
// no network: venue wifi is not a dependency.
const sans = localFont({
  variable: "--font-instrument-sans",
  display: "swap",
  src: [
    { path: "./fonts/instrument-sans-latin-wght-normal.woff2", weight: "400 700", style: "normal" },
    { path: "./fonts/instrument-sans-latin-wght-italic.woff2", weight: "400 700", style: "italic" },
  ],
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

export const metadata: Metadata = {
  title: { default: "Whitespace: how original is your idea?", template: "%s · Whitespace" },
  description: "A swarm of AI agents charts the prior art around your idea, verifies every claim against its source, and coaches you toward the empty regions of the map.",
};

export const viewport: Viewport = { themeColor: "#a8d3e3", colorScheme: "light" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
