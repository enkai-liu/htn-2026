// A deliberately tiny Markdown renderer for model-written summaries. It builds React elements only
// (no innerHTML anywhere), so nothing a model or a scraped page says can inject markup.
// Supports: paragraphs, "-"/"*" lists, #-headings, **bold**, *italic*, `code`, [n] citation refs, [text](http link).
import { Fragment, type ReactNode } from "react";
import { safeHref } from "@/lib/format";

const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[\d{1,3}\]|\[[^\]\n]+\]\([^)\s]+\))/g;

function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const tok = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyPrefix}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("*")) out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    else if (/^\[\d+\]$/.test(tok)) {
      const n = tok.slice(1, -1);
      out.push(<sup key={key}><a href={`#cite-${n}`}>[{n}]</a></sup>);
    } else {
      const parts = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
      const href = parts ? safeHref(parts[2]) : null;
      out.push(href ? <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="text-amber underline decoration-dotted underline-offset-2">{parts![1]}</a> : parts ? parts[1] : tok);
    }
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function SafeMarkdown({ source, className }: { source: string; className?: string }) {
  const blocks = (source ?? "").replace(/\r\n/g, "\n").split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  return (
    <div className={className}>
      {blocks.map((block, bi) => {
        const lines = block.split("\n");
        if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
          return <ul key={bi}>{lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*[-*]\s+/, ""), `${bi}-${li}`)}</li>)}</ul>;
        }
        const heading = /^(#{1,4})\s+(.*)$/.exec(lines[0]);
        if (heading && lines.length === 1) return <h4 key={bi}>{inline(heading[2], `${bi}`)}</h4>;
        return (
          <p key={bi}>
            {lines.map((l, li) => <Fragment key={li}>{li > 0 && <br />}{inline(l, `${bi}-${li}`)}</Fragment>)}
          </p>
        );
      })}
    </div>
  );
}
