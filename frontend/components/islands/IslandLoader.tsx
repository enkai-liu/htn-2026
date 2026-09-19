"use client";
// What the map shows until there is a map: one small island bobbing over its own ripples. It covers three waits that
// used to look identical to "nothing is happening": the three.js chunk downloading, the scene compiling its shaders
// and drawing a first frame, and a run that has not placed any island yet.
import { useEffect, useState } from "react";

const FADE_MS = 450; // matches .island-loader's transition

export function IslandLoader({ gone, quiet }: { gone: boolean; quiet?: boolean }) {
  // Unmounted on a timer rather than on transitionend: a scene that is ready before the loader has faded in never
  // runs a visible transition, and the ripples would go on animating at opacity 0 for the life of the page.
  const [removed, setRemoved] = useState(false);
  useEffect(() => {
    if (!gone) return;
    const t = setTimeout(() => setRemoved(true), FADE_MS + 50);
    return () => clearTimeout(t);
  }, [gone]);
  // a replay that restarts empties the map again: the loader has to be able to come back
  if (removed && !gone) setRemoved(false);
  if (removed) return null;
  return (
    <div className="island-loader" data-gone={gone ? "1" : "0"} role={quiet ? undefined : "status"} aria-hidden={quiet || undefined}>
      <span className="island-loader-mark" aria-hidden>
        <span className="island-loader-ring" />
        <span className="island-loader-ring" style={{ animationDelay: "0.9s" }} />
        <svg className="island-loader-isle" viewBox="0 0 64 48" width="64" height="48">
          <polygon points="6,18 20,10 44,9 58,17 50,25 16,26" fill="#f1d7a0" />
          <polygon points="6,18 16,26 50,25 58,17 58,21 50,29 16,30 6,22" fill="#dcc28c" />
          <polygon points="6,22 16,30 30,44" fill="#b3ac9f" />
          <polygon points="16,30 50,29 30,44" fill="#c4bdb0" />
          <polygon points="50,29 58,21 30,44" fill="#9a9387" />
        </svg>
      </span>
      {!quiet && <span className="font-display text-[19px] italic text-mute">Charting the islands…</span>}
    </div>
  );
}
