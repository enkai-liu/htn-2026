import Link from "next/link";
import { HeroIslands } from "@/components/HeroIslands";
import { SiteNav } from "@/components/SiteNav";

export default function NotFound() {
  return (
    <>
      {/* the same sea as every other page, with nothing in it */}
      <HeroIslands empty className="pointer-events-none fixed inset-0 bg-sea" />
      <SiteNav />
      <main className="relative z-10 flex flex-1 flex-col items-center justify-center px-6 py-24 text-center">
        <p className="label text-on-sea">Off the chart</p>
        <h1 className="mt-3 font-display text-[56px] leading-none text-bone">Nothing at these coordinates.</h1>
        
        <div className="mt-6 flex gap-3">
          <Link href="/" className="btn btn-primary h-10 px-5">Investigate an idea</Link>
        </div>
      </main>
    </>
  );
}
