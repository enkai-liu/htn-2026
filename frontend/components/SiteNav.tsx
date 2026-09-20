import clsx from "clsx";
import Link from "next/link";

/** The mark: one small floating island. (Still exported as StarGlyph for the pages that import it by that name.) */
export function StarGlyph({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <path d="M3 9.5 12 6l9 3.5-9 3.5-9-3.5Z" fill="currentColor" />
      <path d="M4.5 12.2 12 15l7.5-2.8L12 22 4.5 12.2Z" fill="currentColor" fillOpacity="0.45" />
      <path d="M10.2 3.2h3.6v4.6l-1.8.7-1.8-.7V3.2Z" fill="currentColor" fillOpacity="0.8" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <Link href="/" className={clsx("group inline-flex items-center gap-2 text-bone", className)} aria-label="Whitespace home">
      <StarGlyph className="text-amber transition-transform duration-500 group-hover:-translate-y-0.5" />
      <span className="font-display text-[22px] leading-none">
        White<span className="ml-[0.2em] italic tracking-[0.14em] text-bone-dim">space</span>
      </span>
    </Link>
  );
}

const LINKS = [
  { href: "/", label: "Investigate" },
];

export function SiteNav({ active }: { active?: string }) {
  return (
    <header className="relative z-10 flex h-[60px] flex-none items-center justify-between px-5 sm:px-8">
      <Wordmark />
      <nav className="flex items-center gap-1 text-[13.5px]">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={clsx(
              "px-2.5 py-1.5 transition-colors hover:text-bone",
              active === l.href ? "text-bone" : "text-mute",
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
