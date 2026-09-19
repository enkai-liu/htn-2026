import type { Metadata } from "next";
import { Suspense } from "react";
import { RunView } from "@/components/RunView";

// The original single-page dashboard, kept as the demo fallback. It sits outside the (tabs) group on purpose:
// it opens its own stream and must not be wrapped by the tab shell.
// "mock" is prerendered so the replay-only deploy (and `pnpm build:static`) always has it.
export function generateStaticParams() {
  return [{ id: "mock" }];
}

export async function generateMetadata({ params }: PageProps<"/runs/[id]/classic">): Promise<Metadata> {
  const { id } = await params;
  return { title: id === "mock" ? "Recorded run · classic" : `Run ${id} · classic` };
}

export default async function RunPage({ params }: PageProps<"/runs/[id]/classic">) {
  const { id } = await params;
  return (
    // RunView reads ?replay= and ?speed= with useSearchParams, which needs a Suspense boundary to prerender
    <Suspense fallback={<div className="theme-dark flex h-dvh items-center justify-center font-mono text-[10.5px] uppercase tracking-[0.2em] text-faint">Unrolling the chart…</div>}>
      <RunView runId={decodeURIComponent(id)} />
    </Suspense>
  );
}
