import type { Metadata } from "next";
import { Suspense } from "react";
import { RunProvider } from "@/components/run/RunProvider";

// "mock" is prerendered so the replay-only deploy (and `pnpm build:static`) always has it;
// any other id is rendered on demand and streams from the backend.
export function generateStaticParams() {
  return [{ id: "mock" }];
}

export async function generateMetadata({ params }: LayoutProps<"/runs/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: id === "mock" ? "Recorded run" : `Run ${id}` };
}

// A layout keeps its state while the pages under it swap, so the run is streamed once here and every tab reads it
// from context. (No layout at app/runs/[id]/ itself: that would also wrap /classic and open a second stream.)
export default async function RunTabsLayout({ children, params }: LayoutProps<"/runs/[id]">) {
  const { id } = await params;
  return (
    // RunProvider reads ?replay= and ?speed= with useSearchParams, which needs a Suspense boundary to prerender
    <Suspense fallback={<div className="flex h-dvh items-center justify-center font-display text-[20px] italic text-mute">Charting the islands…</div>}>
      <RunProvider runId={decodeURIComponent(id)}>{children}</RunProvider>
    </Suspense>
  );
}
