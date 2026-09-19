"use client";
// The only file that touches WebGL from React. Loaded with ssr:false by IslandMap: three.js wants a window.
import { useEffect, useRef } from "react";
import type { LayoutState } from "@/lib/islandLayout";
import { IslandScene, type CameraPose, type IslandDatum, type SceneLink } from "./IslandScene";

export interface IslandMapCanvasProps {
  islands: IslandDatum[];
  links: SceneLink[];
  layout: LayoutState;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onHover?: (id: string | null) => void;
  onContextLost: () => void;
  /** islands that have already popped in (owned by the provider so it survives this component unmounting) */
  seen: Set<string>;
  cameraMemo?: { current: CameraPose | null };
  /** bumped by the "re-centre" button */
  recenterTick?: number;
  ambient?: boolean;
}

export default function IslandMapCanvas({ islands, links, layout, selectedId, onSelect, onHover, onContextLost, seen, cameraMemo, recenterTick = 0, ambient }: IslandMapCanvasProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const labelRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<IslandScene | null>(null);
  const cb = useRef({ onSelect, onHover, onContextLost });
  useEffect(() => { cb.current = { onSelect, onHover, onContextLost }; });

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    let scene: IslandScene;
    try {
      scene = new IslandScene(canvas, {
        onHover: (id) => cb.current.onHover?.(id),
        onSelect: (id) => cb.current.onSelect(id),
        onContextLost: () => cb.current.onContextLost(),
      }, {
        reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        ambient, seen, camera: cameraMemo?.current ?? null, labelLayer: labelRef.current,
      });
    } catch {
      cb.current.onContextLost();
      return;
    }
    sceneRef.current = scene;
    const ro = new ResizeObserver(([entry]) => scene.resize(entry.contentRect.width, entry.contentRect.height));
    ro.observe(wrap);
    scene.resize(wrap.clientWidth, wrap.clientHeight);
    return () => {
      ro.disconnect();
      if (cameraMemo) cameraMemo.current = scene.getCameraPose();
      scene.dispose();
      sceneRef.current = null;
    };
    // the scene lives as long as the component: data flows in through the effects below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { sceneRef.current?.setData(islands, links, layout); }, [islands, links, layout]);
  useEffect(() => { sceneRef.current?.setSelected(selectedId); }, [selectedId]);
  useEffect(() => { if (recenterTick > 0) sceneRef.current?.recenter(); }, [recenterTick]);

  return (
    <div ref={wrapRef} className="absolute inset-0 overflow-hidden">
      <canvas ref={canvasRef} className="block h-full w-full touch-none outline-none" style={{ cursor: ambient ? "default" : "grab" }} />
      <div ref={labelRef} className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden />
    </div>
  );
}
