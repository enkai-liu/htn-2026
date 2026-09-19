import clsx from "clsx";
import Link from "next/link";

export function StarGlyph({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <circle cx="12" cy="12" r="10.5" stroke="currentColor" strokeOpacity="0.35" strokeDasharray="1.5 3" />
      <path d="M12 2.5c.6 5.2 1.8 7.4 9.5 9.5-7.7 2.1-8.9 4.3-9.5 9.5-.6-5.2-1.8-7.4-9.5-9.5 7.7-2.1 8.9-4.3 9.5-9.5Z" fill="currentColor" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <Link href="/" className={clsx("group inline-flex items-center gap-2 text-bone", className)} aria-label="Whitespace home">
      <StarGlyph className="text-amber transition-transform duration-700 group-hover:rotate-90" />
      <span className="font-display text-[22px] leading-none">
        White<span className="ml-[0.2em] italic tracking-[0.14em] text-bone-dim">space</span>
      </span>
    </Link>
  );
}

const LINKS = [
  { href: "/", label: "Investigate" },
  { href: "/runs/mock", label: "Recorded run" },
  { href: "/slop-index", label: "Slop Index" },
  { href: "/about", label: "How it works" },
];

export function SiteNav({ active }: { active?: string }) {
  return (
    <header className="relative z-10 flex h-14 flex-none items-center justify-between border-b border-line px-5 sm:px-8">
      <Wordmark />
      <nav className="flex items-center gap-1 font-mono text-[10.5px] uppercase tracking-[0.18em]">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={clsx(
              "px-2.5 py-1.5 transition-colors hover:text-bone",
              active === l.href ? "text-amber" : "text-mute",
              l.href === "/" && "hidden sm:block",
            )}
          >
            {l.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
