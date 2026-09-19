// Decorative star chart for the landing page: the idea at the pole, prior art crowded into one quarter,
// and an empty sector (the whitespace) that a mutation is drifting into. Static SVG + two CSS animations.

const C = 300;
const RINGS = [
  { r: 78, label: "0.75" },
  { r: 148, label: "0.50" },
  { r: 218, label: "0.25" },
];

function rng(seed: number) {
  let s = seed;
  return () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296);
}

const polar = (deg: number, r: number) => {
  const a = (deg * Math.PI) / 180;
  return [C + Math.cos(a) * r, C + Math.sin(a) * r] as const;
};

function arc(from: number, to: number, r: number) {
  const [x0, y0] = polar(from, r);
  const [x1, y1] = polar(to, r);
  return `M${x0.toFixed(1)} ${y0.toFixed(1)}A${r} ${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
}

export function HeroChart({ className }: { className?: string }) {
  const rand = rng(7);
  // prior art: crowded between 95° and 250°, denser near the centre
  const crowd = Array.from({ length: 46 }, (_, i) => {
    const deg = 95 + rand() * 155;
    const r = 52 + Math.pow(rand(), 1.5) * 215;
    const size = 1.2 + rand() * (i % 7 === 0 ? 4.2 : 2.2);
    return { deg, r, size, hue: i % 5 };
  });
  // the LLM prior: a grey haze close to the centre
  const haze = Array.from({ length: 16 }, () => ({ deg: 60 + rand() * 250, r: 40 + rand() * 90, size: 5 + rand() * 9 }));
  // a few strays elsewhere so the empty sector reads as genuinely empty
  const strays = Array.from({ length: 9 }, () => ({ deg: 255 + rand() * 60, r: 120 + rand() * 150, size: 1 + rand() * 1.8 }));
  const colors = ["#78b4ff", "#c4bdf0", "#ff9466", "#ece5d3", "#e87fa6"];
  const [mx0, my0] = polar(-38, 92);
  const [mx1, my1] = polar(-32, 236);

  return (
    <svg viewBox="0 0 600 600" className={className} role="img" aria-label="A star chart of idea-space: prior art crowds one quarter, another is empty.">
      <defs>
        <radialGradient id="hc-core" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#f4b942" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#f4b942" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="hc-sweep" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#f4b942" stopOpacity="0" />
          <stop offset="100%" stopColor="#f4b942" stopOpacity="0.09" />
        </linearGradient>
        <radialGradient id="hc-haze" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#8891a5" stopOpacity="0.32" />
          <stop offset="100%" stopColor="#8891a5" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* graticule */}
      {Array.from({ length: 12 }, (_, i) => {
        const [x, y] = polar(i * 30, 288);
        return <line key={i} x1={C} y1={C} x2={x} y2={y} stroke="#96b0e6" strokeOpacity="0.07" />;
      })}
      {RINGS.map((ring) => (
        <g key={ring.r}>
          <circle cx={C} cy={C} r={ring.r} fill="none" stroke="#96b0e6" strokeOpacity="0.2" strokeDasharray="2 5" />
          <text x={C + 4} y={C - ring.r - 4} fill="#7c8498" fontSize="9" fontFamily="var(--font-dm-mono), monospace" letterSpacing="1">
            sim {ring.label}
          </text>
        </g>
      ))}
      <circle cx={C} cy={C} r={288} fill="none" stroke="#96b0e6" strokeOpacity="0.28" />
      {Array.from({ length: 72 }, (_, i) => {
        const long = i % 6 === 0;
        const [x0, y0] = polar(i * 5, 288);
        const [x1, y1] = polar(i * 5, long ? 277 : 283);
        return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} stroke="#96b0e6" strokeOpacity={long ? 0.5 : 0.25} />;
      })}

      {/* radar sweep */}
      <g style={{ transformOrigin: "300px 300px", animation: "sweep 14s linear infinite" }}>
        <path d={`M${C} ${C}L${polar(-26, 288).join(" ")}A288 288 0 0 1 ${polar(0, 288).join(" ")}Z`} fill="url(#hc-sweep)" />
        <line x1={C} y1={C} x2={C + 288} y2={C} stroke="#f4b942" strokeOpacity="0.28" />
      </g>

      {/* the LLM prior: what any model would suggest */}
      {haze.map((h, i) => {
        const [x, y] = polar(h.deg, h.r);
        return <circle key={i} cx={x} cy={y} r={h.size} fill="url(#hc-haze)" />;
      })}

      {/* prior art */}
      {crowd.map((s, i) => {
        const [x, y] = polar(s.deg, s.r);
        return (
          <g key={i}>
            {s.size > 3.4 && <line x1={C} y1={C} x2={x} y2={y} stroke={colors[s.hue]} strokeOpacity="0.12" />}
            <circle cx={x} cy={y} r={s.size} fill={colors[s.hue]} fillOpacity={s.size > 3.4 ? 0.95 : 0.6} />
          </g>
        );
      })}
      {strays.map((s, i) => {
        const [x, y] = polar(s.deg, s.r);
        return <circle key={i} cx={x} cy={y} r={s.size} fill="#ece5d3" fillOpacity="0.45" />;
      })}
      <text x={polar(214, 226)[0]} y={polar(214, 226)[1]} fill="#b4b09f" fontSize="17" fontStyle="italic" fontFamily="var(--font-instrument-serif), serif" textAnchor="middle">
        the crowded quarter
      </text>

      {/* whitespace: the empty sector */}
      <path d={`${arc(-78, 12, 262)}`} fill="none" stroke="#4fd6c0" strokeOpacity="0.75" strokeDasharray="3 6" style={{ animation: "dash 2.4s linear infinite" }} />
      <path d={`M${polar(-78, 96).join(" ")}L${polar(-78, 262).join(" ")}M${polar(12, 96).join(" ")}L${polar(12, 262).join(" ")}`} stroke="#4fd6c0" strokeOpacity="0.35" strokeDasharray="3 6" />
      <text x={polar(-52, 205)[0]} y={polar(-52, 205)[1]} fill="#4fd6c0" fontSize="25" fontStyle="italic" fontFamily="var(--font-instrument-serif), serif" textAnchor="middle">
        whitespace
      </text>
      <text x={polar(-52, 205)[0]} y={polar(-52, 205)[1] + 16} fill="#4fd6c0" fillOpacity="0.7" fontSize="8.5" fontFamily="var(--font-dm-mono), monospace" letterSpacing="2" textAnchor="middle">
        0 PROJECTS HERE
      </text>

      {/* a mutation leaving the crowd */}
      <line x1={mx0} y1={my0} x2={mx1} y2={my1} stroke="#4fd6c0" strokeOpacity="0.6" strokeDasharray="2 4" />
      <circle cx={mx0} cy={my0} r="3" fill="none" stroke="#4fd6c0" strokeOpacity="0.5" />
      <g transform={`translate(${mx1} ${my1})`}>
        <circle r="11" fill="none" stroke="#4fd6c0" strokeOpacity="0.35" />
        <path d="M0 -6L5.2 3L-5.2 3Z" fill="#4fd6c0" />
        <text x="16" y="4" fill="#4fd6c0" fontSize="10" fontFamily="var(--font-dm-mono), monospace">+31</text>
      </g>

      {/* your idea */}
      <circle cx={C} cy={C} r="58" fill="url(#hc-core)" />
      <path d={`M${C} ${C - 17}c1.1 9.4 3.2 13.300 17 17-13.800 3.700-15.900 7.600-17 17-1.100-9.400-3.200-13.300-17-17 13.800-3.700 15.900-7.600 17-17Z`} fill="#f4b942" />
      <text x={C} y={C + 36} fill="#ece5d3" fontSize="15" fontStyle="italic" fontFamily="var(--font-instrument-serif), serif" textAnchor="middle">
        your idea
      </text>
    </svg>
  );
}
