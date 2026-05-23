// Meli v2.3 — clickable preview shell.
// Three views (Dashboard, Geo Map, Atrium kiosk) wired up via tab state.
// Visual goals: deep dark base (less yellow wash), honeycomb accents NOT
// global wash, animated honey drips, corner hex clusters, pot as the true
// centerpiece on Dashboard.

import React, { useEffect, useMemo, useRef, useState } from "react";

const HONEY = "#d4a017";
const AMBER = "#f59e0b";
const PALE = "#fde68a";
const STING = "#dc2626";
const ORANGE = "#ea7f1c";
const INK = "#06060a";          // deeper dark — less amber than before
const PANEL = "#11110d";
const PANEL2 = "#1a1812";
const BORDER = "#2c2418";
const MUTED = "#8a8270";
const NEON_GREEN = "#22c55e";
const NEON_CYAN = "#22d3ee";

// ── Global decorative layer ──────────────────────────────────────────────
function HoneyAtmosphere() {
  // 4 falling honey drips, staggered, on the right edge of the viewport
  const drips = [0, 1, 2, 3];
  return (
    <>
      <style>{`
        @keyframes drip {
          0%   { transform: translateY(-20px) scaleY(0.6); opacity: 0; }
          10%  { opacity: 0.85; }
          80%  { opacity: 0.7; transform: translateY(60vh) scaleY(1.4); }
          100% { transform: translateY(85vh) scaleY(0.4); opacity: 0; }
        }
        @keyframes pulse-glow {
          0%, 100% { filter: drop-shadow(0 0 8px ${AMBER}99); }
          50%      { filter: drop-shadow(0 0 22px ${AMBER}); }
        }
        @keyframes bee-fly {
          0%   { transform: translate(0, 0) rotate(0deg); }
          25%  { transform: translate(40px, -20px) rotate(15deg); }
          50%  { transform: translate(80px, 10px) rotate(-10deg); }
          75%  { transform: translate(35px, 25px) rotate(10deg); }
          100% { transform: translate(0, 0) rotate(0deg); }
        }
        @keyframes radar-sweep {
          0%   { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        @keyframes ticker {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        @keyframes shimmer {
          0%, 100% { opacity: 0.4; }
          50%      { opacity: 1; }
        }
        @keyframes flow-arc {
          0%   { stroke-dashoffset: 200; opacity: 0; }
          15%  { opacity: 1; }
          100% { stroke-dashoffset: 0;   opacity: 0; }
        }
        .drip {
          position: absolute;
          width: 6px; height: 14px;
          border-radius: 50% 50% 50% 50% / 30% 30% 70% 70%;
          background: linear-gradient(180deg, ${PALE}, ${HONEY});
          box-shadow: 0 0 8px ${AMBER}aa, inset -1px -1px 2px ${ORANGE};
          pointer-events: none;
          z-index: 1;
        }
      `}</style>
      {drips.map(i => (
        <div key={i} className="drip"
          style={{
            right: `${[3, 28, 62, 88][i]}%`,
            top: 0,
            animation: `drip ${8 + i * 1.7}s ${i * 2.2}s infinite ease-in`,
          }} />
      ))}
    </>
  );
}

function HexCluster({ pos, size = 110, opacity = 0.18 }: {
  pos: "tl" | "tr" | "bl" | "br"; size?: number; opacity?: number;
}) {
  const corner = {
    tl: { top: -size / 3, left: -size / 3 },
    tr: { top: -size / 3, right: -size / 3 },
    bl: { bottom: -size / 3, left: -size / 3 },
    br: { bottom: -size / 3, right: -size / 3 },
  }[pos];
  return (
    <svg width={size * 2} height={size * 2} style={{ position: "absolute", ...corner, pointerEvents: "none", zIndex: 0 }}>
      <defs>
        <radialGradient id={`hcg-${pos}`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={HONEY} stopOpacity={opacity} />
          <stop offset="100%" stopColor={HONEY} stopOpacity={0} />
        </radialGradient>
      </defs>
      <circle cx={size} cy={size} r={size} fill={`url(#hcg-${pos})`} />
      <g fill="none" stroke={HONEY} strokeWidth="1" opacity={opacity * 1.5}>
        {[0, 1, 2, 3, 4, 5, 6].map(r => [0, 1, 2, 3, 4, 5, 6].map(c => {
          const x = c * 26 + (r % 2 ? 13 : 0) + 10;
          const y = r * 22 + 10;
          return <polygon key={`${r}-${c}`} points={`${x},${y - 8} ${x + 13},${y - 4} ${x + 13},${y + 4} ${x},${y + 8} ${x - 13},${y + 4} ${x - 13},${y - 4}`} />;
        }))}
      </g>
    </svg>
  );
}

function pageBg(): React.CSSProperties {
  return {
    background: `
      radial-gradient(ellipse at 18% 8%,  rgba(212,160,23,0.12) 0%, transparent 45%),
      radial-gradient(ellipse at 82% 92%, rgba(234,127,28,0.10) 0%, transparent 45%),
      radial-gradient(ellipse at 50% 50%, ${PANEL} 0%, ${INK} 70%)
    `,
  };
}

// ── Shared primitives ────────────────────────────────────────────────────
function Panel({ children, className = "", style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={`relative rounded-2xl p-4 ${className}`} style={{
      background: `linear-gradient(155deg, ${PANEL2}f5 0%, ${PANEL}f8 100%)`,
      border: `1px solid ${BORDER}`,
      boxShadow: `inset 0 1px 0 rgba(254,243,199,0.04), 0 8px 28px rgba(0,0,0,0.55), 0 0 0 1px rgba(212,160,23,0.05)`,
      ...style,
    }}>
      {/* honey drip top stripe */}
      <div className="absolute left-0 top-0 h-[2px] w-full rounded-t-2xl"
        style={{ background: `linear-gradient(90deg, transparent, ${HONEY}, ${AMBER}, ${ORANGE}, transparent)` }} />
      {children}
    </div>
  );
}

function SectionHeader({ title, accent, right }: { title: string; accent?: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <div className="w-1.5 h-5 rounded-sm" style={{ background: `linear-gradient(180deg, ${HONEY}, ${ORANGE})`, boxShadow: `0 0 10px ${HONEY}99` }} />
      <div className="text-[11px] font-bold uppercase tracking-[0.22em]" style={{ color: PALE }}>{title}</div>
      {accent && <div className="text-[10px] px-2 py-0.5 rounded-full font-bold" style={{ background: `${HONEY}22`, color: HONEY, border: `1px solid ${HONEY}55` }}>{accent}</div>}
      <div className="flex-1 h-px" style={{ background: `linear-gradient(90deg, ${HONEY}55, transparent)` }} />
      {right}
    </div>
  );
}

function Sparkline({ values, color = AMBER, w = 220, h = 44 }: { values: number[]; color?: string; w?: number; h?: number }) {
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => {
    const x = 4 + (i / (values.length - 1)) * (w - 8);
    const y = 6 + (h - 12) - (v / max) * (h - 12);
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(" ");
  const area = `${line} L${pts[pts.length - 1][0]},${h - 6} L${pts[0][0]},${h - 6} Z`;
  const [lx, ly] = pts[pts.length - 1];
  const gid = `g-${color.replace("#", "")}`;
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <defs><linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stopColor={color} stopOpacity={0.5} />
        <stop offset="100%" stopColor={color} stopOpacity={0.02} />
      </linearGradient></defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth={3.5} strokeOpacity={0.3} strokeLinejoin="round" />
      <path d={line} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r={4.5} fill={color} opacity={0.35} />
      <circle cx={lx} cy={ly} r={2} fill={PALE} />
    </svg>
  );
}

function KpiTile({ title, value, sub, accent = AMBER, state = "ok", spark }: {
  title: string; value: string; sub: string; accent?: string; state?: "ok" | "warn" | "critical"; spark: number[];
}) {
  const stateCol = state === "critical" ? STING : state === "warn" ? ORANGE : PALE;
  return (
    <Panel className="overflow-hidden">
      <div className="absolute right-3 top-3 w-2 h-2 rounded-full" style={{ background: stateCol, boxShadow: `0 0 8px ${stateCol}`, animation: "shimmer 2.5s infinite" }} />
      <div className="text-[10px] tracking-[0.18em] font-bold uppercase" style={{ color: HONEY }}>{title}</div>
      <div className="text-[36px] leading-none font-extrabold tabular-nums mt-1" style={{ color: stateCol, textShadow: `0 0 20px ${stateCol}66` }}>{value}</div>
      <div className="text-[11px] mt-0.5" style={{ color: MUTED }}>{sub}</div>
      <div className="mt-2 -mx-1"><Sparkline values={spark} color={accent} /></div>
    </Panel>
  );
}

// ── Sidebar (clickable) ──────────────────────────────────────────────────
type View = "dashboard" | "geo" | "atrium" | "settings" | "wizard";

function Sidebar({ view, setView }: { view: View; setView: (v: View) => void }) {
  const items: { id: View | string; ic: string; label: string; clickable?: boolean }[] = [
    { id: "dashboard", ic: "▦", label: "Dashboard", clickable: true },
    { id: "live", ic: "⌁", label: "Live Feed" },
    { id: "geo", ic: "◉", label: "Geo Map", clickable: true },
    { id: "atrium", ic: "✦", label: "Atrium Kiosk", clickable: true },
    { id: "sessions", ic: "⛁", label: "Sessions" },
    { id: "findings", ic: "⚑", label: "Findings" },
    { id: "alerts", ic: "⚙", label: "Alerts" },
    { id: "reports", ic: "▤", label: "Reports" },
    { id: "enrich", ic: "☷", label: "Enrichment" },
    { id: "settings", ic: "⛭", label: "Settings", clickable: true },
    { id: "wizard", ic: "✺", label: "Setup Wizard", clickable: true },
  ];
  return (
    <div className="w-[210px] flex flex-col gap-1 p-3 relative" style={{
      background: `linear-gradient(180deg, ${PANEL}f8 0%, ${INK}f8 100%)`,
      borderRight: `1px solid ${BORDER}`,
      boxShadow: `inset -1px 0 0 ${HONEY}22`,
    }}>
      <HexCluster pos="tl" size={140} opacity={0.10} />
      <HexCluster pos="bl" size={120} opacity={0.08} />
      <div className="flex items-center gap-2 mb-4 px-2 pt-1 relative z-10">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center text-[20px] font-black"
          style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK, boxShadow: `0 0 16px ${HONEY}aa`, animation: "pulse-glow 3s infinite" }}>M</div>
        <div>
          <div className="text-[15px] font-extrabold leading-none" style={{ color: PALE }}>MELI</div>
          <div className="text-[8px] tracking-[0.2em] uppercase" style={{ color: HONEY }}>v2.3.0 hive</div>
        </div>
      </div>
      {items.map(it => {
        const active = it.clickable && it.id === view;
        return (
          <div key={it.label}
            onClick={() => it.clickable && setView(it.id as View)}
            className="flex items-center gap-2.5 px-2.5 py-2 rounded-md relative z-10 transition-colors"
            style={{
              cursor: it.clickable ? "pointer" : "default",
              background: active ? `linear-gradient(90deg, ${HONEY}30, transparent)` : "transparent",
              borderLeft: active ? `2px solid ${HONEY}` : "2px solid transparent",
              color: active ? PALE : it.clickable ? "#c8b89e" : MUTED,
              fontWeight: active ? 700 : 500,
              boxShadow: active ? `inset 0 0 16px ${HONEY}22` : "none",
            }}
            onMouseEnter={e => { if (it.clickable && !active) (e.currentTarget as HTMLDivElement).style.background = `${HONEY}15`; }}
            onMouseLeave={e => { if (it.clickable && !active) (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
          >
            <span style={{ color: active ? HONEY : MUTED, fontSize: 14 }}>{it.ic}</span>
            <span className="text-[12px]">{it.label}</span>
            {it.clickable && !active && <span className="ml-auto text-[8px] uppercase tracking-wider" style={{ color: HONEY, opacity: 0.5 }}>click</span>}
          </div>
        );
      })}
      <div className="flex-1" />
      <div className="px-2 py-2 rounded-md text-[10px] relative z-10" style={{ background: `${HONEY}11`, color: HONEY, border: `1px dashed ${HONEY}44` }}>
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full" style={{ background: NEON_GREEN, boxShadow: `0 0 6px ${NEON_GREEN}` }} />
          <span>All systems nominal</span>
        </div>
      </div>
    </div>
  );
}

function HeaderBar({ title, badge }: { title: string; badge?: string }) {
  return (
    <div className="flex items-center gap-4 px-5 py-3 relative" style={{
      background: `linear-gradient(180deg, ${PANEL2}f0 0%, ${PANEL}f0 100%)`,
      borderBottom: `1px solid ${BORDER}`,
      boxShadow: `inset 0 -1px 0 ${HONEY}22, 0 2px 12px rgba(0,0,0,0.4)`,
    }}>
      <div className="text-[16px] font-extrabold tracking-tight" style={{ color: PALE }}>{title}</div>
      {badge && <div className="px-2 py-0.5 rounded-full text-[10px] font-bold" style={{ background: `${NEON_GREEN}22`, color: NEON_GREEN, border: `1px solid ${NEON_GREEN}55` }}>● {badge}</div>}
      <div className="flex-1" />
      <div className="text-[11px] flex items-center gap-3" style={{ color: MUTED }}>
        <span><span style={{ color: HONEY }}>UPTIME</span> 14d 06h</span>
        <span><span style={{ color: HONEY }}>INGEST</span> 142/min</span>
        <span><span style={{ color: HONEY }}>DB</span> 384MB</span>
      </div>
      <div className="w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold" style={{ background: `${HONEY}22`, color: HONEY, border: `1px solid ${HONEY}55` }}>JS</div>
    </div>
  );
}

// ── Honey Pot Centerpiece (bigger, animated) ─────────────────────────────
function HoneyPotCenter({ size = 360 }: { size?: number }) {
  return (
    <div className="relative" style={{ width: size, height: size }}>
      {/* radial pulse rings */}
      <div className="absolute inset-0 rounded-full" style={{
        background: `radial-gradient(circle, ${AMBER}22 0%, transparent 60%)`,
        animation: "shimmer 4s infinite",
      }} />
      <svg viewBox="0 0 240 280" width={size} height={size} style={{ animation: "pulse-glow 4s infinite" }}>
        <defs>
          <radialGradient id="potGlow" cx="50%" cy="60%" r="50%">
            <stop offset="0%" stopColor={AMBER} stopOpacity={0.55} />
            <stop offset="100%" stopColor={AMBER} stopOpacity={0} />
          </radialGradient>
          <linearGradient id="potBody" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={ORANGE} />
            <stop offset="55%" stopColor={HONEY} />
            <stop offset="100%" stopColor="#6e4a0b" />
          </linearGradient>
          <linearGradient id="honeyFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={PALE} />
            <stop offset="100%" stopColor={AMBER} />
          </linearGradient>
          <linearGradient id="potRim" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={PALE} />
            <stop offset="100%" stopColor={HONEY} />
          </linearGradient>
        </defs>
        <circle cx="120" cy="155" r="135" fill="url(#potGlow)" />
        {/* rim */}
        <ellipse cx="120" cy="78" rx="62" ry="11" fill="url(#potRim)" stroke={ORANGE} strokeWidth="1.5" />
        {/* body */}
        <path d="M 60 92 Q 60 80 75 78 L 165 78 Q 180 80 180 92 L 175 232 Q 170 260 120 260 Q 70 260 65 232 Z"
          fill="url(#potBody)" stroke={HONEY} strokeWidth="2" />
        {/* honey level fill */}
        <clipPath id="potClip2">
          <path d="M 62 92 Q 62 82 76 80 L 164 80 Q 178 82 178 92 L 173 230 Q 168 256 120 256 Q 72 256 67 230 Z" />
        </clipPath>
        <rect x="58" y="135" width="125" height="125" fill="url(#honeyFill)" clipPath="url(#potClip2)" opacity={0.95} />
        {/* dripping honey from rim */}
        <path d="M 78 88 Q 76 110 82 130 Q 86 148 82 138 Z" fill={PALE} opacity={0.8} />
        <path d="M 158 88 Q 162 112 156 138 Q 152 152 156 142 Z" fill={PALE} opacity={0.7} />
        {/* hex pattern on body */}
        <g opacity={0.28} stroke={INK} strokeWidth="1.2" fill="none">
          <polygon points="100,180 116,189 116,207 100,216 84,207 84,189" />
          <polygon points="136,180 152,189 152,207 136,216 120,207 120,189" />
          <polygon points="118,150 134,159 134,177 118,186 102,177 102,159" />
          <polygon points="118,210 134,219 134,237 118,246 102,237 102,219" />
          <polygon points="82,150 98,159 98,177 82,186 66,177 66,159" />
          <polygon points="154,150 170,159 170,177 154,186 138,177 138,159" />
        </g>
        {/* bee flying around */}
        <g style={{ animation: "bee-fly 6s infinite ease-in-out", transformOrigin: "180px 60px" }}>
          <g transform="translate(180, 60)">
            <ellipse cx="0" cy="0" rx="10" ry="7" fill={PALE} />
            <rect x="-7" y="-4" width="3" height="8" fill={INK} />
            <rect x="0" y="-4" width="3" height="8" fill={INK} />
            <ellipse cx="-3" cy="-8" rx="7" ry="3.5" fill={PALE} opacity={0.5} />
            <ellipse cx="3" cy="-8" rx="7" ry="3.5" fill={PALE} opacity={0.5} />
          </g>
        </g>
      </svg>
      {/* capacity ring label */}
      <div className="absolute top-2 right-2 text-right">
        <div className="text-[10px] uppercase tracking-widest" style={{ color: HONEY }}>Capacity</div>
        <div className="text-[44px] font-extrabold leading-none" style={{ color: PALE, textShadow: `0 0 24px ${AMBER}88` }}>
          78<span className="text-[22px]" style={{ color: HONEY }}>%</span>
        </div>
        <div className="text-[10px]" style={{ color: MUTED }}>2,762 captured</div>
      </div>
    </div>
  );
}

// Canonical small jar — same body / rim / hex pattern as HoneyPotCenter so
// every honeypot reference in the UI reads as the SAME object, just sized.
function MiniHoneyJar({ size = 28, glow = true, dim = false }: { size?: number; glow?: boolean; dim?: boolean }) {
  const op = dim ? 0.45 : 1;
  return (
    <svg viewBox="0 0 240 280" width={size} height={size} style={{
      filter: glow && !dim ? `drop-shadow(0 0 6px ${AMBER}99)` : "none",
      opacity: op,
    }}>
      <defs>
        <linearGradient id={`mjBody-${size}-${dim ? "d" : "n"}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={dim ? MUTED : ORANGE} />
          <stop offset="55%" stopColor={dim ? "#5a4f30" : HONEY} />
          <stop offset="100%" stopColor={dim ? "#2a2418" : "#6e4a0b"} />
        </linearGradient>
        <linearGradient id={`mjFill-${size}-${dim ? "d" : "n"}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={dim ? "#8a8270" : PALE} />
          <stop offset="100%" stopColor={dim ? "#5a4f30" : AMBER} />
        </linearGradient>
        <clipPath id={`mjClip-${size}-${dim ? "d" : "n"}`}>
          <path d="M 62 92 Q 62 82 76 80 L 164 80 Q 178 82 178 92 L 173 230 Q 168 256 120 256 Q 72 256 67 230 Z" />
        </clipPath>
      </defs>
      <ellipse cx="120" cy="78" rx="62" ry="11" fill={dim ? MUTED : PALE} stroke={dim ? "#5a4f30" : ORANGE} strokeWidth="2" />
      <path d="M 60 92 Q 60 80 75 78 L 165 78 Q 180 80 180 92 L 175 232 Q 170 260 120 260 Q 70 260 65 232 Z"
        fill={`url(#mjBody-${size}-${dim ? "d" : "n"})`} stroke={dim ? "#5a4f30" : HONEY} strokeWidth="3" />
      <rect x="58" y="140" width="125" height="125" fill={`url(#mjFill-${size}-${dim ? "d" : "n"})`} clipPath={`url(#mjClip-${size}-${dim ? "d" : "n"})`} opacity={0.92} />
      <g opacity={0.32} stroke={INK} strokeWidth="1.5" fill="none">
        <polygon points="100,180 116,189 116,207 100,216 84,207 84,189" />
        <polygon points="136,180 152,189 152,207 136,216 120,207 120,189" />
        <polygon points="118,150 134,159 134,177 118,186 102,177 102,159" />
      </g>
    </svg>
  );
}

// ── View: Dashboard ──────────────────────────────────────────────────────
function ViewDashboard() {
  return (
    <div className="p-5 flex flex-col gap-4 relative" style={pageBg()}>
      <HoneyAtmosphere />
      <HexCluster pos="tr" size={180} opacity={0.10} />
      <HexCluster pos="bl" size={160} opacity={0.08} />

      {/* KPI row */}
      <div className="grid grid-cols-4 gap-4 relative z-10">
        <KpiTile title="Events / 24h" value="2,762" sub="↗ 18% vs yesterday" accent={AMBER} state="ok" spark={[12, 18, 14, 22, 28, 35, 31, 42, 38, 51, 48, 62, 58, 71]} />
        <KpiTile title="Critical Alerts" value="47" sub="14 unacknowledged" accent={STING} state="critical" spark={[2, 4, 3, 6, 5, 8, 7, 11, 9, 13, 15, 12, 18, 22]} />
        <KpiTile title="Unique Attackers" value="384" sub="↗ 12 new today" accent={ORANGE} state="warn" spark={[20, 24, 22, 28, 31, 35, 33, 38, 42, 45, 48, 52, 55, 58]} />
        <KpiTile title="Honeypots Online" value="6/7" sub="glastopf degraded" accent={HONEY} state="ok" spark={[7, 7, 7, 7, 7, 7, 6, 7, 7, 6, 7, 7, 6, 6]} />
      </div>

      {/* Pot centerpiece spanning 2 cols + side stats */}
      <div className="grid grid-cols-5 gap-4 relative z-10">
        <Panel className="col-span-3 flex items-center justify-center" style={{ minHeight: 420 }}>
          <SectionHeader title="The Hive" accent="LIVE" />
          <div className="absolute top-12 left-0 right-0 bottom-0 flex items-center justify-center">
            <HoneyPotCenter size={360} />
          </div>
          <div className="absolute bottom-4 left-4 right-4 flex items-end justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-widest" style={{ color: HONEY }}>Last Strike</div>
              <div className="text-[15px] font-bold" style={{ color: PALE }}>3 sec ago</div>
              <div className="text-[11px] font-mono" style={{ color: ORANGE }}>185.220.101.42 · cowrie</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-widest" style={{ color: HONEY }}>Strikes / hr</div>
              <div className="text-[22px] font-extrabold" style={{ color: PALE }}>184</div>
              <div className="text-[11px]" style={{ color: NEON_GREEN }}>↑ peak hour</div>
            </div>
          </div>
        </Panel>
        <div className="col-span-2 flex flex-col gap-4">
          <Panel>
            <SectionHeader title="Severity (24h)" />
            <div className="flex flex-col gap-2.5 text-[11px]">
              {[{ l: "CRITICAL", c: 47, col: STING }, { l: "HIGH", c: 124, col: ORANGE }, { l: "MEDIUM", c: 286, col: HONEY }, { l: "LOW", c: 412, col: PALE }, { l: "INFO", c: 1893, col: MUTED }].map(r => (
                <div key={r.l} className="flex items-center gap-2.5">
                  <div className="font-bold w-[70px]" style={{ color: r.col }}>{r.l}</div>
                  <div className="flex-1 h-2 rounded-full" style={{ background: `${BORDER}55` }}>
                    <div className="h-full rounded-full" style={{ width: `${(r.c / 1893) * 100}%`, background: `linear-gradient(90deg, ${r.col}, ${r.col}88)`, boxShadow: `0 0 6px ${r.col}77` }} />
                  </div>
                  <div className="w-12 text-right font-bold tabular-nums" style={{ color: PALE }}>{r.c}</div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel>
            <SectionHeader title="Top Attackers" />
            <div className="flex flex-col gap-1.5">
              {[
                ["185.220.101.42", "Tor·DE", 412],
                ["45.155.205.119", "VPN·NL", 287],
                ["194.5.249.18", "Host·RU", 198],
                ["171.25.193.77", "Tor·SE", 156],
              ].map(([ip, geo, cnt], i) => (
                <div key={i} className="flex items-center gap-2 p-1.5 rounded" style={{ background: `${BORDER}30` }}>
                  <div className="w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center"
                    style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK }}>{i + 1}</div>
                  <div className="flex-1 text-[11px] font-mono" style={{ color: PALE }}>{ip}</div>
                  <div className="text-[10px]" style={{ color: MUTED }}>{geo}</div>
                  <div className="text-[12px] font-bold tabular-nums" style={{ color: AMBER }}>{cnt}</div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>

      {/* Attack intensity + fleet */}
      <div className="grid grid-cols-3 gap-4 relative z-10">
        <Panel className="col-span-2">
          <SectionHeader title="24h Attack Intensity" accent="HOURLY" />
          <div className="flex items-end gap-[3px] h-[90px] px-1">
            {[3, 5, 4, 8, 6, 7, 12, 18, 22, 15, 9, 11, 14, 26, 38, 31, 24, 19, 28, 42, 35, 22, 14, 9].map((v, i, a) => {
              const peak = Math.max(...a);
              const tier = v >= peak * 0.66 ? AMBER : v >= peak * 0.33 ? HONEY : `${HONEY}88`;
              const col = v === peak ? STING : tier;
              return <div key={i} className="flex-1 flex flex-col justify-end">
                <div style={{
                  height: `${(v / peak) * 100}%`,
                  background: `linear-gradient(180deg, ${col}, ${col}66)`,
                  boxShadow: v === peak ? `0 0 8px ${col}` : "none",
                  borderRadius: "3px 3px 0 0",
                }} />
              </div>;
            })}
          </div>
          <div className="flex justify-between text-[9px] mt-1 px-1" style={{ color: MUTED }}>
            <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>NOW</span>
          </div>
        </Panel>
        <Panel>
          <SectionHeader title="Honeypot Fleet" accent="6/7" />
          <div className="grid grid-cols-2 gap-2">
            {[
              { n: "cowrie", e: 1842, l: 0.42, ok: true },
              { n: "dionaea", e: 423, l: 0.18, ok: true },
              { n: "heralding", e: 198, l: 0.09, ok: true },
              { n: "http-pot", e: 256, l: 0.31, ok: true },
              { n: "mailoney", e: 38, l: 0.04, ok: true },
              { n: "glastopf", e: 5, l: 0.02, ok: false },
            ].map(p => {
              const dot = p.ok ? NEON_GREEN : AMBER;
              return <div key={p.n} className="rounded-lg p-2" style={{ background: `${BORDER}30`, border: `1px solid ${BORDER}aa` }}>
                <div className="flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full" style={{ background: dot, boxShadow: `0 0 6px ${dot}` }} />
                  <div className="text-[10px] font-bold font-mono truncate" style={{ color: PALE }}>{p.n}</div>
                </div>
                <div className="text-[14px] font-extrabold tabular-nums" style={{ color: HONEY }}>{p.e.toLocaleString()}</div>
                <div className="h-0.5 rounded-full mt-1" style={{ background: `${BORDER}80` }}>
                  <div className="h-full rounded-full" style={{ width: `${p.l * 100}%`, background: `linear-gradient(90deg, ${HONEY}, ${ORANGE})` }} />
                </div>
              </div>;
            })}
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ── View: Geo Map (beefed up) ────────────────────────────────────────────
function ViewGeoMap() {
  // Animated attack arcs FROM origin THE the honeypot in central US-ish
  const target = { x: 500, y: 280 };
  const sources = [
    { name: "Berlin, DE", x: 920, y: 220, sev: STING, count: 412 },
    { name: "Moscow, RU", x: 1050, y: 190, sev: STING, count: 287 },
    { name: "Amsterdam, NL", x: 880, y: 210, sev: ORANGE, count: 198 },
    { name: "Stockholm, SE", x: 920, y: 170, sev: HONEY, count: 156 },
    { name: "Shanghai, CN", x: 1300, y: 290, sev: STING, count: 142 },
    { name: "São Paulo, BR", x: 620, y: 480, sev: ORANGE, count: 98 },
    { name: "Lagos, NG", x: 880, y: 380, sev: HONEY, count: 76 },
    { name: "Sydney, AU", x: 1480, y: 510, sev: HONEY, count: 54 },
    { name: "Tokyo, JP", x: 1420, y: 270, sev: ORANGE, count: 121 },
  ];
  return (
    <div className="p-5 flex flex-col gap-4 relative" style={pageBg()}>
      <HoneyAtmosphere />
      <HexCluster pos="tl" size={160} opacity={0.10} />
      <HexCluster pos="br" size={180} opacity={0.10} />

      <div className="grid grid-cols-4 gap-4 relative z-10">
        <KpiTile title="Countries Today" value="47" sub="6 new this week" accent={HONEY} state="ok" spark={[35, 38, 40, 42, 41, 44, 45, 47]} />
        <KpiTile title="Peak Region" value="EU" sub="62% of all traffic" accent={AMBER} state="warn" spark={[40, 45, 50, 55, 58, 60, 61, 62]} />
        <KpiTile title="Tor Exit Hits" value="892" sub="↗ 34% vs week" accent={STING} state="critical" spark={[300, 350, 420, 480, 560, 680, 780, 892]} />
        <KpiTile title="Avg ASN Reputation" value="-4.2" sub="malicious-leaning" accent={ORANGE} state="warn" spark={[-2, -2.5, -3, -3.4, -3.8, -4.0, -4.1, -4.2]} />
      </div>

      <Panel className="relative z-10" style={{ height: 560 }}>
        <SectionHeader title="Global Attack Origin Map" accent="LIVE · last 60min" right={
          <div className="flex items-center gap-2 text-[10px]" style={{ color: MUTED }}>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: STING, boxShadow: `0 0 6px ${STING}` }} /> CRITICAL</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: ORANGE, boxShadow: `0 0 6px ${ORANGE}` }} /> HIGH</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: HONEY, boxShadow: `0 0 6px ${HONEY}` }} /> MEDIUM</span>
          </div>
        } />
        <svg viewBox="0 0 1700 600" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="globePulse" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor={AMBER} stopOpacity={0.8} />
              <stop offset="100%" stopColor={AMBER} stopOpacity={0} />
            </radialGradient>
          </defs>
          {/* Dot world map (poor man's continents via dot grid) */}
          <g fill={HONEY} opacity={0.35}>
            {Array.from({ length: 40 }).map((_, r) =>
              Array.from({ length: 85 }).map((_, c) => {
                const x = 30 + c * 20;
                const y = 30 + r * 14;
                // Crude continent mask
                const inland =
                  (x > 120 && x < 380 && y > 100 && y < 280) ||         // NA
                  (x > 220 && x < 380 && y > 280 && y < 360) ||         // Cent A
                  (x > 530 && x < 720 && y > 380 && y < 540) ||         // SA
                  (x > 760 && x < 920 && y > 110 && y < 180) ||         // EU N
                  (x > 800 && x < 1020 && y > 180 && y < 240) ||        // EU
                  (x > 820 && x < 1080 && y > 280 && y < 450) ||        // Africa
                  (x > 1080 && x < 1300 && y > 130 && y < 280) ||       // Russia
                  (x > 1080 && x < 1380 && y > 240 && y < 360) ||       // Asia
                  (x > 1380 && x < 1520 && y > 460 && y < 540);         // Aus
                if (!inland) return null;
                return <circle key={`${r}-${c}`} cx={x} cy={y} r="2" />;
              })
            )}
          </g>
          {/* Origin pulse markers */}
          {sources.map((s, i) => (
            <g key={i}>
              <circle cx={s.x} cy={s.y} r="14" fill="none" stroke={s.sev} strokeWidth="1.5" opacity={0.6} style={{ animation: `shimmer ${2 + i * 0.3}s infinite` }} />
              <circle cx={s.x} cy={s.y} r="6" fill={s.sev} opacity={0.9} />
              <circle cx={s.x} cy={s.y} r="3" fill={PALE} />
              {/* attack arc to target */}
              <path d={`M ${s.x},${s.y} Q ${(s.x + target.x) / 2},${Math.min(s.y, target.y) - 120} ${target.x},${target.y}`}
                fill="none" stroke={s.sev} strokeWidth="1.5" strokeDasharray="200"
                style={{ animation: `flow-arc ${3 + i * 0.4}s ${i * 0.2}s infinite linear`, filter: `drop-shadow(0 0 4px ${s.sev})` }} />
              <text x={s.x + 12} y={s.y - 8} fontSize="10" fontFamily="JetBrains Mono, monospace" fill={PALE} opacity={0.85}>{s.name}</text>
            </g>
          ))}
          {/* Target (honeypot) */}
          <circle cx={target.x} cy={target.y} r="60" fill="url(#globePulse)" style={{ animation: "shimmer 2s infinite" }} />
          <circle cx={target.x} cy={target.y} r="14" fill={AMBER} stroke={PALE} strokeWidth="2" />
          <text x={target.x} y={target.y + 36} fontSize="11" fontFamily="JetBrains Mono, monospace" fill={PALE} textAnchor="middle" fontWeight="bold">HIVE</text>
        </svg>
      </Panel>

      <div className="grid grid-cols-3 gap-4 relative z-10">
        <Panel>
          <SectionHeader title="Top Countries (24h)" />
          <div className="flex flex-col gap-2 text-[11px]">
            {[
              { f: "🇩🇪", n: "Germany", c: 612 },
              { f: "🇷🇺", n: "Russia", c: 487 },
              { f: "🇨🇳", n: "China", c: 412 },
              { f: "🇳🇱", n: "Netherlands", c: 298 },
              { f: "🇺🇸", n: "United States", c: 256 },
              { f: "🇫🇷", n: "France", c: 184 },
            ].map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-[14px]">{r.f}</span>
                <span className="flex-1" style={{ color: PALE }}>{r.n}</span>
                <div className="w-24 h-1.5 rounded-full" style={{ background: `${BORDER}55` }}>
                  <div className="h-full rounded-full" style={{ width: `${(r.c / 612) * 100}%`, background: `linear-gradient(90deg, ${HONEY}, ${ORANGE})`, boxShadow: `0 0 4px ${HONEY}77` }} />
                </div>
                <span className="w-10 text-right font-bold tabular-nums" style={{ color: AMBER }}>{r.c}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel>
          <SectionHeader title="ASN Hot List" />
          <div className="flex flex-col gap-1.5 text-[11px] font-mono">
            {[
              ["AS14061", "DigitalOcean", 482, ORANGE],
              ["AS16276", "OVH SAS", 367, AMBER],
              ["AS9009", "M247 Ltd", 284, STING],
              ["AS24940", "Hetzner", 198, HONEY],
              ["AS197540", "netcup GmbH", 142, HONEY],
              ["AS208046", "TheFortress", 87, STING],
            ].map((r, i) => (
              <div key={i} className="flex items-center gap-2 p-1.5 rounded" style={{ background: `${BORDER}30`, borderLeft: `2px solid ${r[3]}` }}>
                <span className="font-bold" style={{ color: PALE }}>{r[0]}</span>
                <span className="flex-1 truncate" style={{ color: MUTED }}>{r[1]}</span>
                <span className="font-bold tabular-nums" style={{ color: r[3] as string }}>{r[2]}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel>
          <SectionHeader title="Region Intensity" accent="LIVE" />
          <div className="flex flex-col gap-2.5">
            {[
              { r: "Europe", c: 1342, col: STING },
              { r: "Asia-Pacific", c: 894, col: ORANGE },
              { r: "North America", c: 412, col: HONEY },
              { r: "South America", c: 184, col: HONEY },
              { r: "Africa", c: 124, col: PALE },
              { r: "Oceania", c: 86, col: PALE },
            ].map((r, i) => (
              <div key={i}>
                <div className="flex items-center justify-between text-[11px] mb-0.5">
                  <span style={{ color: r.col }} className="font-bold">{r.r}</span>
                  <span className="font-mono tabular-nums" style={{ color: PALE }}>{r.c}</span>
                </div>
                <div className="h-2 rounded-full" style={{ background: `${BORDER}55` }}>
                  <div className="h-full rounded-full" style={{ width: `${(r.c / 1342) * 100}%`, background: `linear-gradient(90deg, ${r.col}, ${r.col}88)`, boxShadow: `0 0 6px ${r.col}77` }} />
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ── View: Atrium (live "war around you" sniffer kiosk) ───────────────────
function useTickingPackets() {
  const [packets, setPackets] = useState(() => seedPackets());
  useEffect(() => {
    const t = setInterval(() => {
      setPackets(p => [genPacket(), ...p].slice(0, 18));
    }, 900);
    return () => clearInterval(t);
  }, []);
  return packets;
}
function seedPackets() {
  return Array.from({ length: 12 }, () => genPacket());
}
function genPacket() {
  const protos = [
    { p: "TCP", c: NEON_CYAN, w: 0.35 },
    { p: "UDP", c: HONEY, w: 0.25 },
    { p: "TLS", c: NEON_GREEN, w: 0.15 },
    { p: "DNS", c: PALE, w: 0.10 },
    { p: "ICMP", c: ORANGE, w: 0.05 },
    { p: "ARP", c: MUTED, w: 0.05 },
    { p: "SSH", c: STING, w: 0.05 },
  ];
  const r = Math.random();
  let acc = 0;
  const proto = protos.find(p => (acc += p.w) >= r) || protos[0];
  const rip = () => `${1 + Math.floor(Math.random() * 254)}.${Math.floor(Math.random() * 254)}.${Math.floor(Math.random() * 254)}.${Math.floor(Math.random() * 254)}`;
  const local = () => `192.168.1.${10 + Math.floor(Math.random() * 240)}`;
  const inbound = Math.random() < 0.45;
  const ports = [22, 80, 443, 53, 3389, 8080, 5060, 21, 25, 17654];
  return {
    id: Math.random().toString(36).slice(2),
    t: new Date().toISOString().slice(11, 19),
    proto: proto.p,
    color: proto.c,
    src: inbound ? rip() : local(),
    dst: inbound ? local() : rip(),
    sport: ports[Math.floor(Math.random() * ports.length)],
    dport: ports[Math.floor(Math.random() * ports.length)],
    size: 40 + Math.floor(Math.random() * 1460),
    flag: inbound ? "↓" : "↑",
  };
}

function RadarSweep() {
  // Concentric range rings + sweep beam, blips for nearby devices/attackers
  return (
    <div className="relative" style={{ width: 380, height: 380 }}>
      <svg viewBox="0 0 380 380" width="380" height="380">
        <defs>
          <radialGradient id="radarGrad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={AMBER} stopOpacity={0.25} />
            <stop offset="100%" stopColor={INK} stopOpacity={0} />
          </radialGradient>
          <linearGradient id="sweepGrad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor={AMBER} stopOpacity={0.6} />
            <stop offset="100%" stopColor={AMBER} stopOpacity={0} />
          </linearGradient>
        </defs>
        <circle cx="190" cy="190" r="180" fill="url(#radarGrad)" />
        {[60, 110, 160, 180].map(r => (
          <circle key={r} cx="190" cy="190" r={r} fill="none" stroke={HONEY} strokeOpacity={0.25} strokeWidth="1" />
        ))}
        <line x1="10" y1="190" x2="370" y2="190" stroke={HONEY} strokeOpacity={0.18} />
        <line x1="190" y1="10" x2="190" y2="370" stroke={HONEY} strokeOpacity={0.18} />
        {/* sweep */}
        <g style={{ transformOrigin: "190px 190px", animation: "radar-sweep 6s linear infinite" }}>
          <path d="M 190 190 L 370 190 A 180 180 0 0 0 240 22 Z" fill="url(#sweepGrad)" />
        </g>
        {/* blips */}
        {[
          { x: 240, y: 130, lab: "iPhone-Jay", c: NEON_GREEN, kind: "device" },
          { x: 130, y: 230, lab: "router.lan", c: NEON_GREEN, kind: "device" },
          { x: 285, y: 250, lab: "printer", c: PALE, kind: "device" },
          { x: 95, y: 130, lab: "?? unknown", c: AMBER, kind: "unk" },
          { x: 310, y: 95, lab: "scan@:22", c: STING, kind: "attack" },
          { x: 70, y: 280, lab: "scan@:445", c: STING, kind: "attack" },
          { x: 220, y: 320, lab: "BLE-Tile", c: HONEY, kind: "ble" },
          { x: 340, y: 200, lab: "wifi-probe", c: ORANGE, kind: "probe" },
        ].map((b, i) => (
          <g key={i}>
            <circle cx={b.x} cy={b.y} r="8" fill="none" stroke={b.c} strokeOpacity={0.5} style={{ animation: `shimmer ${1.5 + i * 0.2}s infinite` }} />
            <circle cx={b.x} cy={b.y} r="3.5" fill={b.c} />
            <text x={b.x + 8} y={b.y + 3} fontSize="9" fontFamily="JetBrains Mono, monospace" fill={PALE} opacity={0.8}>{b.lab}</text>
          </g>
        ))}
        {/* center self marker */}
        <circle cx="190" cy="190" r="6" fill={AMBER} stroke={PALE} strokeWidth="2" />
        <text x="190" y="208" fontSize="9" fill={PALE} textAnchor="middle" fontFamily="JetBrains Mono, monospace" fontWeight="bold">YOU</text>
      </svg>
    </div>
  );
}

function ViewAtrium() {
  const packets = useTickingPackets();
  const [protoCount, setProtoCount] = useState({ TCP: 0, UDP: 0, TLS: 0, DNS: 0, ICMP: 0, ARP: 0, SSH: 0 });
  useEffect(() => {
    setProtoCount(c => {
      const np: any = { ...c };
      packets.slice(0, 3).forEach(p => { np[p.proto] = (np[p.proto] || 0) + 1; });
      return np;
    });
  }, [packets]);

  return (
    <div className="p-5 flex flex-col gap-4 relative" style={pageBg()}>
      <HoneyAtmosphere />
      <HexCluster pos="tl" size={200} opacity={0.12} />
      <HexCluster pos="tr" size={180} opacity={0.10} />
      <HexCluster pos="bl" size={200} opacity={0.10} />
      <HexCluster pos="br" size={220} opacity={0.12} />

      {/* Header strip — location + threat level */}
      <Panel className="relative z-10">
        <div className="flex items-center gap-6">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em]" style={{ color: HONEY }}>Atrium · Live</div>
            <div className="text-[22px] font-extrabold" style={{ color: PALE }}>The War Around You</div>
            <div className="text-[11px]" style={{ color: MUTED }}>192.168.1.34 · home.lan · Brooklyn, NY · 14:08:32 EST</div>
            <div className="flex items-center gap-1.5 mt-1.5 text-[10px]" style={{ color: HONEY }}>
              <span style={{ fontSize: 11 }}>🛡</span>
              <span>Monitoring local network — authorized use on your own network only.</span>
            </div>
          </div>
          <div className="flex-1" />
          {[
            { l: "Active Threats", v: "12", c: STING },
            { l: "Devices Seen", v: "27", c: NEON_CYAN },
            { l: "SSIDs Nearby", v: "14", c: AMBER },
            { l: "BLE Beacons", v: "8", c: HONEY },
            { l: "Packets/sec", v: "418", c: NEON_GREEN },
          ].map((s, i) => (
            <div key={i} className="text-center px-4 border-l" style={{ borderColor: BORDER }}>
              <div className="text-[9px] uppercase tracking-widest" style={{ color: HONEY }}>{s.l}</div>
              <div className="text-[26px] font-extrabold tabular-nums" style={{ color: s.c, textShadow: `0 0 16px ${s.c}66` }}>{s.v}</div>
            </div>
          ))}
          <div className="text-center px-4 border-l" style={{ borderColor: BORDER }}>
            <div className="text-[9px] uppercase tracking-widest" style={{ color: HONEY }}>Threat Level</div>
            <div className="text-[15px] font-extrabold px-3 py-1 rounded mt-1" style={{ background: `linear-gradient(135deg, ${STING}, ${ORANGE})`, color: INK, boxShadow: `0 0 12px ${STING}88` }}>ELEVATED</div>
          </div>
        </div>
      </Panel>

      {/* Main grid: sniffer | radar | nearby */}
      <div className="grid grid-cols-12 gap-4 relative z-10">
        {/* Sniffer feed */}
        <Panel className="col-span-4" style={{ height: 460 }}>
          <SectionHeader title="Live Packet Capture" accent="wlan0 · promisc" />
          <div className="flex flex-col gap-0.5 font-mono text-[10px] overflow-hidden" style={{ height: 400 }}>
            {packets.map((p, i) => (
              <div key={p.id} className="flex items-center gap-1.5 px-1.5 py-1 rounded transition-opacity"
                style={{ background: i === 0 ? `${p.color}22` : `${BORDER}25`, borderLeft: `2px solid ${p.color}`, opacity: 1 - i * 0.04 }}>
                <span style={{ color: MUTED }}>{p.t}</span>
                <span className="px-1.5 py-px rounded text-[9px] font-bold" style={{ background: `${p.color}33`, color: p.color, minWidth: 30, textAlign: "center" }}>{p.proto}</span>
                <span style={{ color: p.flag === "↓" ? STING : NEON_GREEN, fontSize: 11 }}>{p.flag}</span>
                <span style={{ color: PALE }} className="truncate">{p.src}:{p.sport}</span>
                <span style={{ color: MUTED }}>→</span>
                <span style={{ color: PALE }} className="truncate">{p.dst}:{p.dport}</span>
                <span className="ml-auto tabular-nums" style={{ color: HONEY }}>{p.size}B</span>
              </div>
            ))}
          </div>
        </Panel>

        {/* Radar centerpiece */}
        <Panel className="col-span-5 flex flex-col items-center justify-center" style={{ height: 460 }}>
          <SectionHeader title="Local Radar · 100m" accent="SWEEPING" />
          <div className="flex-1 flex items-center justify-center">
            <RadarSweep />
          </div>
          <div className="text-[10px] grid grid-cols-3 gap-2 w-full mt-2">
            <div className="text-center"><span style={{ color: NEON_GREEN }}>●</span> <span style={{ color: MUTED }}>known device</span></div>
            <div className="text-center"><span style={{ color: AMBER }}>●</span> <span style={{ color: MUTED }}>unknown</span></div>
            <div className="text-center"><span style={{ color: STING }}>●</span> <span style={{ color: MUTED }}>attacker</span></div>
          </div>
        </Panel>

        {/* Right column — nearby */}
        <div className="col-span-3 flex flex-col gap-4">
          <Panel style={{ height: 222 }}>
            <SectionHeader title="WiFi Nearby" accent="14 SSIDs" />
            <div className="flex flex-col gap-1 font-mono text-[10px]">
              {[
                { s: "linksys-2.4", b: -42, sec: "WPA2", risk: HONEY },
                { s: "xfinitywifi", b: -56, sec: "OPEN", risk: STING },
                { s: "ATT-3829", b: -61, sec: "WPA3", risk: NEON_GREEN },
                { s: "FBI-Surveillance", b: -68, sec: "OPEN", risk: STING },
                { s: "TP-LINK_GUEST", b: -71, sec: "WPA2", risk: AMBER },
                { s: "<hidden>", b: -74, sec: "WPA2", risk: AMBER },
                { s: "Pretty Fly 4 WiFi", b: -78, sec: "WPA2", risk: HONEY },
              ].map((w, i) => (
                <div key={i} className="flex items-center gap-1.5 px-1 py-0.5 rounded" style={{ background: `${BORDER}25` }}>
                  <span style={{ color: w.risk, fontSize: 9 }}>●</span>
                  <span className="truncate flex-1" style={{ color: PALE }}>{w.s}</span>
                  <span style={{ color: HONEY }}>{w.sec}</span>
                  <span className="tabular-nums" style={{ color: MUTED }}>{w.b}</span>
                </div>
              ))}
            </div>
          </Panel>
          <Panel style={{ height: 222 }}>
            <SectionHeader title="BLE & Bonjour" accent="8 SEEN" />
            <div className="flex flex-col gap-1 font-mono text-[10px]">
              {[
                { n: "AirPods Pro · Jay", k: "BLE", c: NEON_CYAN },
                { n: "Tile_4F2A", k: "BLE", c: HONEY },
                { n: "Brother HL-L23 [_ipp]", k: "mDNS", c: PALE },
                { n: "Roku Ultra [_googlecast]", k: "mDNS", c: PALE },
                { n: "Nest-cam-living", k: "mDNS", c: NEON_GREEN },
                { n: "Unknown · A4:E5:7C:..", k: "BLE", c: AMBER },
                { n: "MacBook-Pro [_smb]", k: "mDNS", c: NEON_GREEN },
              ].map((d, i) => (
                <div key={i} className="flex items-center gap-1.5 px-1 py-0.5 rounded" style={{ background: `${BORDER}25` }}>
                  <span style={{ color: d.c, fontSize: 9 }}>●</span>
                  <span className="truncate flex-1" style={{ color: PALE }}>{d.n}</span>
                  <span style={{ color: HONEY }}>{d.k}</span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>

      {/* Bottom row: protocol mix, port scans, threat intel ticker */}
      <div className="grid grid-cols-12 gap-4 relative z-10">
        <Panel className="col-span-3">
          <SectionHeader title="Protocol Mix" accent="60s" />
          <div className="flex flex-col gap-2 text-[11px]">
            {Object.entries(protoCount).map(([p, c]) => {
              const col = { TCP: NEON_CYAN, UDP: HONEY, TLS: NEON_GREEN, DNS: PALE, ICMP: ORANGE, ARP: MUTED, SSH: STING }[p] || HONEY;
              const max = Math.max(...Object.values(protoCount).map(Number), 1);
              return (
                <div key={p} className="flex items-center gap-2">
                  <span className="font-bold w-[40px]" style={{ color: col }}>{p}</span>
                  <div className="flex-1 h-2 rounded-full" style={{ background: `${BORDER}55` }}>
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${(Number(c) / max) * 100}%`, background: `linear-gradient(90deg, ${col}, ${col}88)`, boxShadow: `0 0 6px ${col}77` }} />
                  </div>
                  <span className="tabular-nums w-8 text-right" style={{ color: PALE }}>{Number(c)}</span>
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel className="col-span-4">
          <SectionHeader title="Inbound Port Scans · Last Hour" accent="42 HITS" />
          <div className="grid grid-cols-8 gap-1.5 mb-2">
            {[22, 80, 443, 445, 3389, 21, 23, 25, 53, 110, 135, 139, 1433, 3306, 5060, 5432, 6379, 8080, 8443, 9200, 11211, 27017, 17654, 50050].map((port, i) => {
              const hits = Math.floor(Math.random() * 50);
              const heat = hits / 50;
              return (
                <div key={port} className="rounded p-1 text-center font-mono text-[9px]" style={{
                  background: heat > 0.7 ? `${STING}33` : heat > 0.4 ? `${ORANGE}33` : heat > 0.1 ? `${HONEY}22` : `${BORDER}40`,
                  border: `1px solid ${heat > 0.7 ? STING : heat > 0.4 ? ORANGE : heat > 0.1 ? HONEY : BORDER}66`,
                  color: heat > 0.4 ? PALE : MUTED,
                }}>
                  <div className="font-bold">{port}</div>
                  <div className="tabular-nums">{hits}</div>
                </div>
              );
            })}
          </div>
          <div className="text-[10px]" style={{ color: MUTED }}>
            Hot ports: <span style={{ color: STING }}>:22 (SSH)</span>, <span style={{ color: STING }}>:445 (SMB)</span>, <span style={{ color: ORANGE }}>:3389 (RDP)</span>
          </div>
        </Panel>

        <Panel className="col-span-5 overflow-hidden">
          <SectionHeader title="Threat Intel · Last 60min" accent="CVE / IOC" />
          <div className="flex flex-col gap-1.5 text-[11px]">
            {[
              { t: "CVE-2026-1042", sev: STING, d: "Critical RCE in F5 BIG-IP — exploits seen in wild" },
              { t: "IOC match",     sev: STING, d: "185.220.101.42 in Feodo + AbuseIPDB · 7 hits today" },
              { t: "CVE-2026-0918", sev: ORANGE, d: "Auth bypass in Fortinet FortiOS · patch pending" },
              { t: "Mass scan",     sev: ORANGE, d: "Internet-wide :22 spray from AS9009 (M247) detected" },
              { t: "New IOC",       sev: HONEY,  d: "Cobalt Strike C2 cluster · 14 IPs added to feed" },
              { t: "CVE-2026-0744", sev: HONEY,  d: "XSS in Confluence DC · medium · patch available" },
            ].map((it, i) => (
              <div key={i} className="flex items-center gap-2 p-1.5 rounded" style={{ background: `${BORDER}25`, borderLeft: `2px solid ${it.sev}` }}>
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${it.sev}33`, color: it.sev }}>{it.t}</span>
                <span className="truncate" style={{ color: PALE }}>{it.d}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ── View: Settings ───────────────────────────────────────────────────────
type SettingsCat = "auth" | "pots" | "classify" | "alerts" | "enrich" | "backup" | "about";

function CatRow({ icon, label, sub, active, onClick }: { icon: string; label: string; sub: string; active: boolean; onClick: () => void }) {
  return (
    <div onClick={onClick} className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all"
      style={{
        background: active ? `linear-gradient(90deg, ${HONEY}30, ${HONEY}08)` : "transparent",
        borderLeft: active ? `3px solid ${HONEY}` : "3px solid transparent",
        boxShadow: active ? `inset 0 0 14px ${HONEY}22` : "none",
      }}
      onMouseEnter={e => { if (!active) (e.currentTarget as HTMLDivElement).style.background = `${HONEY}12`; }}
      onMouseLeave={e => { if (!active) (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}>
      <div className="w-8 h-8 rounded-md flex items-center justify-center text-[14px]"
        style={{ background: active ? `linear-gradient(135deg, ${HONEY}, ${ORANGE})` : `${BORDER}66`, color: active ? INK : HONEY, boxShadow: active ? `0 0 12px ${HONEY}88` : "none" }}>{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-bold truncate" style={{ color: active ? PALE : "#c8b89e" }}>{label}</div>
        <div className="text-[10px] truncate" style={{ color: MUTED }}>{sub}</div>
      </div>
    </div>
  );
}

function Field({ label, value, hint, monospace }: { label: string; value: React.ReactNode; hint?: string; monospace?: boolean }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-[10px] uppercase tracking-[0.18em] font-bold" style={{ color: HONEY }}>{label}</div>
      <div className="rounded-lg px-3 py-2.5 text-[12px]" style={{
        background: `${INK}aa`,
        border: `1px solid ${BORDER}`,
        color: PALE,
        fontFamily: monospace ? "JetBrains Mono, monospace" : undefined,
        boxShadow: `inset 0 1px 3px rgba(0,0,0,0.5)`,
      }}>{value}</div>
      {hint && <div className="text-[10px]" style={{ color: MUTED }}>{hint}</div>}
    </div>
  );
}

function Toggle({ on }: { on: boolean }) {
  return (
    <div className="w-10 h-5 rounded-full relative transition-colors" style={{
      background: on ? `linear-gradient(90deg, ${HONEY}, ${ORANGE})` : `${BORDER}aa`,
      boxShadow: on ? `0 0 10px ${HONEY}aa` : "inset 0 1px 3px rgba(0,0,0,0.6)",
    }}>
      <div className="w-4 h-4 rounded-full absolute top-0.5 transition-all" style={{
        background: PALE, left: on ? 22 : 2,
        boxShadow: "0 1px 4px rgba(0,0,0,0.6)",
      }} />
    </div>
  );
}

function ChannelRow({ name, icon, on, target, status }: { name: string; icon: string; on: boolean; target: string; status: string }) {
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg" style={{ background: `${BORDER}30`, border: `1px solid ${BORDER}aa` }}>
      <div className="w-10 h-10 rounded-md flex items-center justify-center text-[18px]"
        style={{ background: on ? `linear-gradient(135deg, ${HONEY}, ${ORANGE})` : `${BORDER}80`, color: on ? INK : MUTED }}>{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-bold" style={{ color: PALE }}>{name}</span>
          {on && <span className="text-[9px] px-1.5 py-0.5 rounded font-bold" style={{ background: `${NEON_GREEN}22`, color: NEON_GREEN, border: `1px solid ${NEON_GREEN}55` }}>● {status}</span>}
        </div>
        <div className="text-[10px] font-mono truncate" style={{ color: MUTED }}>{target}</div>
      </div>
      <Toggle on={on} />
    </div>
  );
}

function EnrichServiceRow({ name, ok, hits, limit, key_set }: { name: string; ok: boolean; hits: number; limit: number; key_set: boolean }) {
  const pct = (hits / limit) * 100;
  const col = pct > 80 ? STING : pct > 50 ? ORANGE : NEON_GREEN;
  return (
    <div className="p-3 rounded-lg" style={{ background: `${BORDER}30`, border: `1px solid ${BORDER}aa` }}>
      <div className="flex items-center gap-2 mb-2">
        <div className="w-1.5 h-1.5 rounded-full" style={{ background: ok && key_set ? NEON_GREEN : key_set ? AMBER : MUTED, boxShadow: `0 0 6px ${ok && key_set ? NEON_GREEN : AMBER}` }} />
        <span className="text-[12px] font-bold" style={{ color: PALE }}>{name}</span>
        <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded font-bold"
          style={{ background: key_set ? `${NEON_GREEN}22` : `${MUTED}22`, color: key_set ? NEON_GREEN : MUTED }}>
          {key_set ? "KEY SET" : "NO KEY"}
        </span>
      </div>
      <div className="flex items-center justify-between text-[10px] mb-1" style={{ color: MUTED }}>
        <span>Quota</span><span className="font-mono tabular-nums" style={{ color: col }}>{hits.toLocaleString()} / {limit.toLocaleString()}</span>
      </div>
      <div className="h-1.5 rounded-full" style={{ background: `${BORDER}80` }}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct)}%`, background: `linear-gradient(90deg, ${col}, ${col}88)`, boxShadow: `0 0 6px ${col}77` }} />
      </div>
    </div>
  );
}

function ViewSettings() {
  const [cat, setCat] = useState<SettingsCat>("alerts");
  const cats: { id: SettingsCat; icon: string; label: string; sub: string }[] = [
    { id: "auth", icon: "🔐", label: "Authentication", sub: "Master password + TOTP" },
    { id: "pots", icon: "🍯", label: "Honeypots", sub: "7 parsers · ingest endpoints" },
    { id: "classify", icon: "⚖", label: "Classification", sub: "16 rules · YAML editor" },
    { id: "alerts", icon: "⚡", label: "Alert Channels", sub: "7 notification routes" },
    { id: "enrich", icon: "✦", label: "Enrichment", sub: "6 IP intel services" },
    { id: "backup", icon: "💾", label: "Backup & Restore", sub: "Automatic snapshots" },
    { id: "about", icon: "ⓘ", label: "About Meli", sub: "Version · licenses · system" },
  ];

  return (
    <div className="p-5 flex flex-col gap-4 relative" style={pageBg()}>
      <HoneyAtmosphere />
      <HexCluster pos="tl" size={160} opacity={0.10} />
      <HexCluster pos="br" size={180} opacity={0.10} />

      <div className="grid grid-cols-12 gap-4 relative z-10">
        {/* Categories sidebar */}
        <Panel className="col-span-3" style={{ height: "fit-content" }}>
          <SectionHeader title="Configuration" />
          <div className="flex flex-col gap-1">
            {cats.map(c => <CatRow key={c.id} icon={c.icon} label={c.label} sub={c.sub} active={cat === c.id} onClick={() => setCat(c.id)} />)}
          </div>
          <div className="mt-4 p-2.5 rounded-md text-[10px]" style={{ background: `${HONEY}11`, border: `1px dashed ${HONEY}44`, color: HONEY }}>
            <div className="font-bold mb-0.5">💾 Auto-saved</div>
            <div style={{ color: MUTED }}>Last write 14:08:32 EST</div>
          </div>
        </Panel>

        {/* Main panel */}
        <div className="col-span-9 flex flex-col gap-4">
          {cat === "alerts" && (
            <>
              <Panel>
                <SectionHeader title="Alert Channels" accent="7 AVAILABLE" right={
                  <button className="text-[10px] font-bold px-2.5 py-1 rounded" style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK }}>+ Add channel</button>
                } />
                <div className="grid grid-cols-2 gap-2.5">
                  <ChannelRow name="Email · SMTP" icon="✉" on={true}  target="alerts@joseph.sh · smtp.gmail.com:587" status="DELIVERING" />
                  <ChannelRow name="Slack"        icon="#" on={true}  target="hooks.slack.com/services/T…/B…/…" status="HEALTHY" />
                  <ChannelRow name="Discord"      icon="◈" on={true}  target="discord.com/api/webhooks/…" status="HEALTHY" />
                  <ChannelRow name="Webhook"      icon="↗" on={false} target="https://n8n.local/webhook/meli-alert" status="—" />
                  <ChannelRow name="Telegram"     icon="✈" on={false} target="bot_token · chat_id" status="—" />
                  <ChannelRow name="Pushover"     icon="◉" on={false} target="user_key · app_token" status="—" />
                  <ChannelRow name="ntfy.sh"      icon="♪" on={true}  target="ntfy.sh/meli-jay-alerts" status="HEALTHY" />
                </div>
              </Panel>

              <Panel>
                <SectionHeader title="Routing Rules" accent="3 ACTIVE" />
                <div className="flex flex-col gap-2">
                  {[
                    { name: "Critical → All", filter: "severity == CRITICAL", channels: ["Email", "Slack", "Discord", "ntfy.sh"], cnt: 47 },
                    { name: "Brute-force flood", filter: "tag has \"brute\" && count > 50/min", channels: ["Slack", "ntfy.sh"], cnt: 12 },
                    { name: "Known APT IOC", filter: "enrich.apt_match == true", channels: ["Email", "Discord"], cnt: 4 },
                  ].map((r, i) => (
                    <div key={i} className="flex items-center gap-3 p-3 rounded-lg" style={{ background: `${BORDER}30`, borderLeft: `3px solid ${HONEY}` }}>
                      <div className="flex-1 min-w-0">
                        <div className="text-[12px] font-bold" style={{ color: PALE }}>{r.name}</div>
                        <div className="text-[10px] font-mono" style={{ color: AMBER }}>{r.filter}</div>
                        <div className="flex gap-1 mt-1">
                          {r.channels.map(c => <span key={c} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: `${HONEY}22`, color: HONEY, border: `1px solid ${HONEY}55` }}>{c}</span>)}
                        </div>
                      </div>
                      <div className="text-center">
                        <div className="text-[18px] font-extrabold tabular-nums" style={{ color: AMBER }}>{r.cnt}</div>
                        <div className="text-[9px] uppercase tracking-wider" style={{ color: MUTED }}>fired 24h</div>
                      </div>
                      <Toggle on={true} />
                    </div>
                  ))}
                </div>
              </Panel>
            </>
          )}

          {cat === "enrich" && (
            <>
              <Panel>
                <SectionHeader title="IP Intelligence Services" accent="6 PROVIDERS" />
                <div className="grid grid-cols-3 gap-3">
                  <EnrichServiceRow name="AbuseIPDB"    ok={true}  hits={847}  limit={1000} key_set={true} />
                  <EnrichServiceRow name="GreyNoise"    ok={true}  hits={412}  limit={10000} key_set={true} />
                  <EnrichServiceRow name="VirusTotal"   ok={true}  hits={284}  limit={500} key_set={true} />
                  <EnrichServiceRow name="Shodan"       ok={true}  hits={94}   limit={100} key_set={true} />
                  <EnrichServiceRow name="IPInfo"       ok={true}  hits={1284} limit={50000} key_set={true} />
                  <EnrichServiceRow name="MaxMind GeoIP" ok={true} hits={0}    limit={0} key_set={true} />
                </div>
              </Panel>
              <Panel>
                <SectionHeader title="Enrichment Cache" accent="TTL 24h" />
                <div className="grid grid-cols-4 gap-3">
                  <Field label="Cached Entries" value="14,283" />
                  <Field label="Hit Rate" value="92.4%" hint="last 24h" />
                  <Field label="Avg Lookup" value="38 ms" />
                  <Field label="Cache Size" value="42 MB" />
                </div>
              </Panel>
            </>
          )}

          {cat === "pots" && (
            <Panel>
              <SectionHeader title="Honeypot Parsers" accent="7 SUPPORTED" />
              <div className="grid grid-cols-2 gap-3">
                {[
                  { n: "Cowrie", on: true, events: 1842, fmt: "JSON · stdin/file" },
                  { n: "Dionaea", on: true, events: 423, fmt: "SQLite · log/sqlite3" },
                  { n: "Heralding", on: true, events: 198, fmt: "JSON · stdin" },
                  { n: "HTTP Pot", on: true, events: 256, fmt: "Combined log" },
                  { n: "Mailoney", on: true, events: 38, fmt: "JSON" },
                  { n: "Glastopf", on: false, events: 5, fmt: "SQLite" },
                  { n: "Generic JSON", on: true, events: 0, fmt: "POST :17654" },
                ].map((p, i) => (
                  <div key={i} className="p-3 rounded-lg flex items-center gap-3" style={{ background: `${BORDER}30`, border: `1px solid ${BORDER}aa` }}>
                    <div className="w-10 h-10 rounded-md flex items-center justify-center"
                      style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})` }}><MiniHoneyJar size={26} glow={false} /></div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[12px] font-bold" style={{ color: PALE }}>{p.n}</div>
                      <div className="text-[10px] font-mono" style={{ color: MUTED }}>{p.fmt}</div>
                      <div className="text-[10px]" style={{ color: HONEY }}>{p.events.toLocaleString()} events</div>
                    </div>
                    <Toggle on={p.on} />
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {cat === "auth" && (
            <Panel>
              <SectionHeader title="Master Password & 2FA" accent="🔒 LOCKED" />
              <div className="grid grid-cols-2 gap-4">
                <Field label="Master Password" value="•••••••••••••••••" hint="Argon2id · 4 lanes · 64 MiB · last rotated 22 days ago" />
                <Field label="TOTP 2FA" value={<span style={{ color: NEON_GREEN }}>● ENABLED · Authy</span>} hint="6 backup codes remaining" />
                <Field label="Auto-lock idle" value="15 minutes" hint="UI locks; ingest keeps running" />
                <Field label="Failed lockout" value="5 attempts → 30 min" />
              </div>
              <div className="flex gap-2 mt-4">
                <button className="px-3 py-2 rounded text-[11px] font-bold" style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK }}>Rotate password</button>
                <button className="px-3 py-2 rounded text-[11px] font-bold" style={{ background: `${BORDER}aa`, color: PALE, border: `1px solid ${HONEY}55` }}>Regenerate backup codes</button>
                <button className="px-3 py-2 rounded text-[11px] font-bold" style={{ background: `${STING}33`, color: STING, border: `1px solid ${STING}66` }}>Reset 2FA</button>
              </div>
            </Panel>
          )}

          {cat === "classify" && (
            <Panel>
              <SectionHeader title="Classification Rules" accent="16 ACTIVE · YAML" />
              <div className="rounded-lg p-3 font-mono text-[11px] overflow-x-auto" style={{ background: INK, border: `1px solid ${BORDER}`, color: PALE }}>
                <pre style={{ margin: 0 }}>{`# /etc/meli/classification.yml
rules:
  - id: brute-ssh-root
    when: service == "cowrie" && user == "root"
    severity: HIGH
    tags: [brute, ssh, root]
    score: +15

  - id: cve-exploit-attempt
    when: payload =~ /(MS17-010|EternalBlue|Log4Shell|CVE-\\d{4}-\\d{4,})/
    severity: CRITICAL
    tags: [exploit, cve]
    score: +50

  - id: tor-exit-traffic
    when: enrich.tor_exit == true
    severity: MEDIUM
    tags: [tor, anon]
    score: +10`}</pre>
              </div>
              <div className="flex gap-2 mt-3">
                <button className="px-3 py-2 rounded text-[11px] font-bold" style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK }}>Edit rules</button>
                <button className="px-3 py-2 rounded text-[11px] font-bold" style={{ background: `${BORDER}aa`, color: PALE, border: `1px solid ${HONEY}55` }}>Validate</button>
                <button className="px-3 py-2 rounded text-[11px] font-bold" style={{ background: `${BORDER}aa`, color: PALE, border: `1px solid ${HONEY}55` }}>Reload</button>
              </div>
            </Panel>
          )}

          {cat === "backup" && (
            <>
              <Panel>
                <SectionHeader title="Backup Schedule" accent="ENABLED" />
                <div className="grid grid-cols-3 gap-4">
                  <Field label="Frequency" value="Every 6 hours" />
                  <Field label="Retention" value="30 days" />
                  <Field label="Destination" value="~/.local/share/meli/backups/" monospace />
                </div>
              </Panel>
              <Panel>
                <SectionHeader title="Recent Snapshots" accent="14 ON DISK" />
                <div className="flex flex-col gap-1.5 font-mono text-[11px]">
                  {[
                    ["meli-2026-05-22-1200.db.gz", "42.1 MB", "2h ago"],
                    ["meli-2026-05-22-0600.db.gz", "41.8 MB", "8h ago"],
                    ["meli-2026-05-22-0000.db.gz", "41.5 MB", "14h ago"],
                    ["meli-2026-05-21-1800.db.gz", "41.2 MB", "20h ago"],
                  ].map(([n, s, t], i) => (
                    <div key={i} className="flex items-center gap-2 p-2 rounded" style={{ background: `${BORDER}30` }}>
                      <span style={{ color: HONEY }}>💾</span>
                      <span className="flex-1" style={{ color: PALE }}>{n}</span>
                      <span style={{ color: MUTED }}>{s}</span>
                      <span style={{ color: AMBER }}>{t}</span>
                      <button className="text-[10px] px-2 py-0.5 rounded" style={{ background: `${HONEY}22`, color: HONEY, border: `1px solid ${HONEY}55` }}>restore</button>
                    </div>
                  ))}
                </div>
              </Panel>
            </>
          )}

          {cat === "about" && (
            <Panel>
              <SectionHeader title="About Meli" />
              <div className="flex items-center gap-4 mb-4">
                <div className="w-16 h-16 rounded-xl flex items-center justify-center text-[32px] font-black"
                  style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK, boxShadow: `0 0 24px ${HONEY}aa`, animation: "pulse-glow 3s infinite" }}>M</div>
                <div>
                  <div className="text-[22px] font-extrabold" style={{ color: PALE }}>Meli</div>
                  <div className="text-[12px]" style={{ color: HONEY }}>Honeypot Command Center</div>
                  <div className="text-[10px]" style={{ color: MUTED }}>v2.3.0 · Apr 2026 · MIT License</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 text-[11px]">
                <Field label="Author" value="Joseph Sierengowski" />
                <Field label="Repository" value="github.com/.../Meli" monospace />
                <Field label="GTK4" value="4.14.2" monospace />
                <Field label="libadwaita" value="1.5.0" monospace />
                <Field label="Python" value="3.12.4" monospace />
                <Field label="Database" value="SQLite · 384 MB" />
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

// ── View: First-Run Setup Wizard ─────────────────────────────────────────
function ViewWizard() {
  const [step, setStep] = useState(1); // start on Authorization
  const [agreed, setAgreed] = useState(false);
  const steps = [
    { t: "Welcome", d: "Meet your hive" },
    { t: "Authorization", d: "Intended use" },
    { t: "Master Password", d: "Argon2id + 2FA" },
    { t: "Honeypots", d: "Pick your sensors" },
    { t: "Enrichment", d: "API keys" },
    { t: "Alerts", d: "Notification routes" },
    { t: "Finish", d: "First boot" },
  ];

  return (
    <div className="p-5 flex flex-col gap-4 relative items-center" style={pageBg()}>
      <HoneyAtmosphere />
      <HexCluster pos="tl" size={220} opacity={0.14} />
      <HexCluster pos="tr" size={220} opacity={0.14} />
      <HexCluster pos="bl" size={220} opacity={0.14} />
      <HexCluster pos="br" size={220} opacity={0.14} />

      <div className="relative z-10 w-full max-w-[1100px] flex flex-col gap-4 mt-2">
        {/* Welcome banner */}
        <Panel>
          <div className="flex items-center gap-4">
            <div className="relative">
              <HoneyPotCenter size={140} />
            </div>
            <div className="flex-1">
              <div className="text-[11px] uppercase tracking-[0.22em]" style={{ color: HONEY }}>First-Run Setup</div>
              <div className="text-[26px] font-extrabold leading-tight" style={{ color: PALE }}>Welcome to the Hive</div>
              <div className="text-[12px] mt-1" style={{ color: MUTED }}>
                Six guided steps to a fully-armed honeypot command center. You can revisit any step later from Settings.
              </div>
            </div>
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-widest" style={{ color: HONEY }}>Time</div>
              <div className="text-[24px] font-extrabold" style={{ color: PALE }}>~5 min</div>
            </div>
          </div>
        </Panel>

        {/* Stepper */}
        <Panel>
          <div className="flex items-center gap-2">
            {steps.map((s, i) => {
              const done = i < step;
              const active = i === step;
              const col = done ? NEON_GREEN : active ? HONEY : MUTED;
              return (
                <React.Fragment key={i}>
                  <div className="flex items-center gap-2 cursor-pointer" onClick={() => setStep(i)}>
                    <div className="w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-extrabold"
                      style={{
                        background: done ? NEON_GREEN : active ? `linear-gradient(135deg, ${HONEY}, ${ORANGE})` : `${BORDER}aa`,
                        color: done || active ? INK : MUTED,
                        boxShadow: active ? `0 0 12px ${HONEY}aa` : "none",
                        border: `1px solid ${col}66`,
                      }}>{done ? "✓" : i + 1}</div>
                    <div>
                      <div className="text-[11px] font-bold" style={{ color: active ? PALE : col }}>{s.t}</div>
                      <div className="text-[9px]" style={{ color: MUTED }}>{s.d}</div>
                    </div>
                  </div>
                  {i < steps.length - 1 && (
                    <div className="flex-1 h-px" style={{ background: i < step ? `linear-gradient(90deg, ${NEON_GREEN}, ${HONEY})` : `${BORDER}aa` }} />
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </Panel>

        {/* Step body — Authorization (step 1) */}
        {step === 1 && (
        <Panel>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-md flex items-center justify-center text-[16px]"
              style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK, boxShadow: `0 0 14px ${HONEY}88` }}>🛡</div>
            <div>
              <div className="text-[18px] font-extrabold" style={{ color: PALE }}>Step 2 · Authorization & Intended Use</div>
              <div className="text-[11px]" style={{ color: MUTED }}>Standard practice for security tools. Please read and acknowledge before continuing.</div>
            </div>
          </div>
          <div className="rounded-lg p-4 mb-4" style={{ background: `${INK}aa`, border: `1px solid ${HONEY}55`, boxShadow: `inset 0 0 24px ${HONEY}11` }}>
            <div className="text-[12px] leading-relaxed" style={{ color: PALE }}>
              <p className="mb-2">
                <span className="font-extrabold" style={{ color: HONEY }}>Meli is a defensive-security and home-lab tool.</span>{" "}
                It is designed for monitoring honeypots, networks, and devices that <span className="italic">you own or are explicitly authorized to operate.</span>
              </p>
              <p className="mb-2" style={{ color: "#c8b89e" }}>
                Do <span style={{ color: STING, fontWeight: 700 }}>not</span> use Meli to monitor networks you don't own, surveil other people, or scan / attack systems without written authorization.
                Laws covering packet capture, wireless interception, and security testing vary by jurisdiction — you are solely responsible for ensuring your use is lawful.
              </p>
              <p className="text-[11px]" style={{ color: MUTED }}>
                Full notice: <span style={{ color: HONEY, fontFamily: "JetBrains Mono, monospace" }}>DISCLAIMER.md</span> · MIT license · provided as-is, no warranty.
              </p>
            </div>
          </div>
          <div onClick={() => setAgreed(a => !a)} className="flex items-start gap-3 p-3 rounded-lg cursor-pointer" style={{
            background: agreed ? `linear-gradient(135deg, ${HONEY}22, ${ORANGE}11)` : `${BORDER}40`,
            border: `1px solid ${agreed ? HONEY : BORDER}`,
            boxShadow: agreed ? `inset 0 0 16px ${HONEY}22, 0 0 12px ${HONEY}44` : "none",
          }}>
            <div className="w-5 h-5 rounded-md flex items-center justify-center flex-shrink-0 mt-0.5" style={{
              background: agreed ? HONEY : "transparent",
              border: `1.5px solid ${agreed ? HONEY : MUTED}`,
              color: INK, fontSize: 12, fontWeight: 900,
            }}>{agreed ? "✓" : ""}</div>
            <div className="text-[12px]" style={{ color: agreed ? PALE : "#c8b89e" }}>
              I understand and will use Meli only on systems and networks I own or am explicitly authorized to monitor.
            </div>
          </div>
          <div className="flex items-center gap-2 mt-5">
            <button onClick={() => setStep(Math.max(0, step - 1))}
              className="px-4 py-2 rounded-md text-[11px] font-bold" style={{ background: `${BORDER}aa`, color: PALE, border: `1px solid ${HONEY}44` }}>← Back</button>
            <a className="px-4 py-2 rounded-md text-[11px] font-bold cursor-pointer" style={{ background: "transparent", color: HONEY }}>Read full DISCLAIMER.md →</a>
            <div className="flex-1" />
            <div className="text-[10px]" style={{ color: agreed ? NEON_GREEN : MUTED }}>
              {agreed ? "✓ Acknowledged · will be timestamped to ~/.config/meli/eula.json" : "Tick the box to continue"}
            </div>
            <button
              disabled={!agreed}
              onClick={() => agreed && setStep(step + 1)}
              className="px-5 py-2 rounded-md text-[11px] font-bold"
              style={{
                background: agreed ? `linear-gradient(135deg, ${HONEY}, ${ORANGE})` : `${BORDER}80`,
                color: agreed ? INK : MUTED,
                boxShadow: agreed ? `0 0 14px ${HONEY}aa` : "none",
                cursor: agreed ? "pointer" : "not-allowed",
              }}>I Agree →</button>
          </div>
        </Panel>
        )}

        {/* Step body — Honeypots (step 3) */}
        {step === 3 && (
        <Panel>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-md flex items-center justify-center"
              style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, boxShadow: `0 0 14px ${HONEY}88` }}><MiniHoneyJar size={22} glow={false} /></div>
            <div>
              <div className="text-[18px] font-extrabold" style={{ color: PALE }}>Step 4 · Pick your honeypots</div>
              <div className="text-[11px]" style={{ color: MUTED }}>Select which sensors will feed events into Meli. You can add more later.</div>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {[
              { n: "Cowrie", d: "SSH/Telnet honeypot · Python", pop: "MOST POPULAR", on: true },
              { n: "Dionaea", d: "Multi-protocol · malware capture", pop: "RECOMMENDED", on: true },
              { n: "Heralding", d: "Credential collector · 13 protocols", pop: "", on: true },
              { n: "HTTP Pot", d: "Web app trap · custom parser", pop: "", on: false },
              { n: "Mailoney", d: "SMTP honeypot", pop: "", on: false },
              { n: "Glastopf", d: "Web app · vuln emulation", pop: "LEGACY", on: false },
              { n: "Generic JSON", d: "POST :17654 endpoint · catch-all", pop: "ALWAYS ON", on: true },
            ].map((p, i) => (
              <div key={i} className="p-3 rounded-lg cursor-pointer transition-all" style={{
                background: p.on ? `linear-gradient(155deg, ${HONEY}22, ${ORANGE}11)` : `${BORDER}30`,
                border: `1px solid ${p.on ? HONEY : BORDER}`,
                boxShadow: p.on ? `inset 0 0 16px ${HONEY}22, 0 0 12px ${HONEY}33` : "none",
              }}>
                <div className="flex items-start gap-2">
                  <div className="w-9 h-9 rounded-md flex items-center justify-center"
                    style={{ background: p.on ? `linear-gradient(135deg, ${HONEY}, ${ORANGE})` : `${BORDER}80` }}><MiniHoneyJar size={22} glow={false} dim={!p.on} /></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[13px] font-extrabold" style={{ color: PALE }}>{p.n}</span>
                      {p.pop && <span className="text-[8px] px-1 py-px rounded font-bold" style={{
                        background: p.pop === "MOST POPULAR" ? `${HONEY}33` : p.pop === "RECOMMENDED" ? `${NEON_GREEN}22` : p.pop === "ALWAYS ON" ? `${AMBER}33` : `${MUTED}22`,
                        color: p.pop === "MOST POPULAR" ? HONEY : p.pop === "RECOMMENDED" ? NEON_GREEN : p.pop === "ALWAYS ON" ? AMBER : MUTED,
                      }}>{p.pop}</span>}
                    </div>
                    <div className="text-[10px] mt-0.5" style={{ color: MUTED }}>{p.d}</div>
                  </div>
                  <div className="w-5 h-5 rounded-md flex items-center justify-center" style={{
                    background: p.on ? HONEY : "transparent",
                    border: `1.5px solid ${p.on ? HONEY : MUTED}`,
                    color: INK, fontSize: 11, fontWeight: 900,
                  }}>{p.on ? "✓" : ""}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2 mt-5">
            <button onClick={() => setStep(Math.max(0, step - 1))}
              className="px-4 py-2 rounded-md text-[11px] font-bold" style={{ background: `${BORDER}aa`, color: PALE, border: `1px solid ${HONEY}44` }}>← Back</button>
            <button className="px-4 py-2 rounded-md text-[11px] font-bold" style={{ background: "transparent", color: MUTED }}>Skip this step</button>
            <div className="flex-1" />
            <div className="text-[10px]" style={{ color: HONEY }}>4 honeypots selected · ingest endpoint :17654</div>
            <button onClick={() => setStep(Math.min(steps.length - 1, step + 1))}
              className="px-5 py-2 rounded-md text-[11px] font-bold"
              style={{ background: `linear-gradient(135deg, ${HONEY}, ${ORANGE})`, color: INK, boxShadow: `0 0 14px ${HONEY}aa` }}>Continue →</button>
          </div>
        </Panel>
        )}

        {/* Inline help */}
        <Panel>
          <SectionHeader title="What happens next" />
          <div className="grid grid-cols-3 gap-3 text-[11px]">
            {[
              { ic: "✦", t: "Enrichment", d: "Drop in API keys for AbuseIPDB, GreyNoise, VirusTotal, Shodan — or skip and use built-in GeoIP only." },
              { ic: "⚡", t: "Alert routes", d: "Wire up Email, Slack, Discord, ntfy, Telegram, Pushover, or Webhook destinations. Routing rules come later." },
              { ic: "🚀", t: "First boot", d: "Meli starts ingesting, classifying, and enriching. Dashboard fills up within minutes of your first attacker." },
            ].map((h, i) => (
              <div key={i} className="p-3 rounded-lg" style={{ background: `${BORDER}30`, border: `1px solid ${BORDER}aa` }}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[16px]" style={{ color: HONEY }}>{h.ic}</span>
                  <span className="text-[12px] font-extrabold" style={{ color: PALE }}>{h.t}</span>
                </div>
                <div style={{ color: MUTED }}>{h.d}</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ── Top-level shell ──────────────────────────────────────────────────────
export function MeliShell() {
  const [view, setView] = useState<View>("dashboard");
  const titles: Record<View, { t: string; b: string }> = {
    dashboard: { t: "Hive Command Center", b: "OPERATIONAL" },
    geo:       { t: "Global Threat Map", b: "LIVE" },
    atrium:    { t: "Atrium · The War Around You", b: "SNIFFING" },
    settings:  { t: "Settings", b: "CONFIGURED" },
    wizard:    { t: "First-Run Setup Wizard", b: "GUIDED" },
  };
  return (
    <div className="min-h-screen w-full font-sans flex" style={{ fontFamily: "Inter, system-ui, sans-serif", background: INK }}>
      <Sidebar view={view} setView={setView} />
      <div className="flex-1 flex flex-col min-w-0">
        <HeaderBar title={titles[view].t} badge={titles[view].b} />
        <div className="flex-1 overflow-auto">
          {view === "dashboard" && <ViewDashboard />}
          {view === "geo" && <ViewGeoMap />}
          {view === "atrium" && <ViewAtrium />}
          {view === "settings" && <ViewSettings />}
          {view === "wizard" && <ViewWizard />}
        </div>
      </div>
    </div>
  );
}
