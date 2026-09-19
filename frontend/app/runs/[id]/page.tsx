import type { Metadata } from "next";
import { Suspense } from "react";
import { RunView } from "@/components/RunView";

// "mock" is prerendered so the replay-only deploy (and `pnpm build:static`) always has it;
// any other id is rendered on demand and streams from the backend.
export function generateStaticParams() {
  return [{ id: "mock" }];
}

export async function generateMetadata({ params }: PageProps<"/runs/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: id === "mock" ? "Recorded run" : `Run ${id}` };
}

export default async function RunPage({ params }: PageProps<"/runs/[id]">) {
  const { id } = await params;
  return (
    // RunView reads ?replay= and ?speed= with useSearchParams, which needs a Suspense boundary to prerender
    <Suspense fallback={<div className="flex h-dvh items-center justify-center font-mono text-[10.5px] uppercase tracking-[0.2em] text-faint">Unrolling the chart…</div>}>
      <RunView runId={decodeURIComponent(id)} />
    </Suspense>
  );
}
