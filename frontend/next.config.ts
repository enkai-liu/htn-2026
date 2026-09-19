import type { NextConfig } from "next";

// `pnpm build`         -> normal Next.js build (Vercel / `next start`): /runs/<any id> works.
// `pnpm build:static`  -> fully static export in ./out for any static host: only /runs/mock is generated,
//                         which is exactly what the replay-only deploy needs.
const staticExport = process.env.NEXT_STATIC_EXPORT === "1";

const nextConfig: NextConfig = {
  ...(staticExport ? { output: "export" as const, trailingSlash: true, images: { unoptimized: true } } : {}),
  // the monorepo root has no lockfile of its own: pin tracing to this package so Next does not guess
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
