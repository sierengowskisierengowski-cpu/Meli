import { ReactNode } from "react";
import { Clock } from "lucide-react";
import {
  useGetDashboardSummary,
  getGetDashboardSummaryQueryKey,
} from "@/api";

type Tone = "operational" | "live" | "sniffing" | "guided" | "configured" | "warning" | "idle";

const TONE_CLASS: Record<Tone, string> = {
  operational: "bg-green-500/15 text-green-400 border-green-500/40 shadow-[0_0_10px_rgba(34,197,94,0.25)]",
  live:        "bg-red-500/15 text-red-400 border-red-500/40 shadow-[0_0_10px_rgba(239,68,68,0.25)]",
  sniffing:    "bg-amber-500/15 text-amber-400 border-amber-500/40 shadow-[0_0_10px_rgba(245,158,11,0.3)]",
  guided:      "bg-green-500/15 text-green-400 border-green-500/40 shadow-[0_0_10px_rgba(34,197,94,0.25)]",
  configured:  "bg-green-500/15 text-green-400 border-green-500/40 shadow-[0_0_10px_rgba(34,197,94,0.25)]",
  warning:     "bg-orange-500/15 text-orange-400 border-orange-500/40 shadow-[0_0_10px_rgba(249,115,22,0.25)]",
  idle:        "bg-stone-700/30 text-stone-300 border-stone-600/40",
};

function formatUptime(s?: number) {
  if (!s || s < 0) return "—";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  if (d > 0) return `${d}d ${String(h).padStart(2, "0")}h`;
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

export function StatusPill({ label, tone = "operational" }: { label: string; tone?: Tone }) {
  const dotColor =
    tone === "live" || tone === "warning" ? "bg-red-500"
    : tone === "sniffing" ? "bg-amber-400"
    : tone === "idle" ? "bg-stone-400"
    : "bg-green-500";
  return (
    <span className={`inline-flex items-center gap-1.5 text-[10px] px-2 py-0.5 rounded-full font-bold tracking-widest uppercase border ${TONE_CLASS[tone]}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor} ${tone === "live" || tone === "sniffing" ? "animate-pulse" : ""}`} />
      {label}
    </span>
  );
}

function TopStats() {
  const { data: summary } = useGetDashboardSummary({
    query: { refetchInterval: 15000, queryKey: getGetDashboardSummaryQueryKey() },
  });
  return (
    <div className="flex items-center gap-4 text-[11px] font-mono text-primary/90 bg-black/40 px-3 py-1.5 rounded-full border border-primary/25 shadow-[0_0_10px_rgba(212,160,23,0.12)]">
      <span className="flex items-center gap-1.5">
        <Clock className="w-3 h-3" />
        <span className="opacity-70">UPTIME</span>
        <span className="text-foreground font-semibold">{formatUptime(summary?.uptimeSeconds)}</span>
      </span>
      <span className="opacity-30">|</span>
      <span className="flex items-center gap-1.5">
        <span className="opacity-70">INGEST</span>
        <span className="text-foreground font-semibold">{summary?.ingestRatePerMin ?? "—"}/min</span>
      </span>
      <span className="opacity-30">|</span>
      <span className="flex items-center gap-1.5">
        <span className="opacity-70">DB</span>
        <span className="text-foreground font-semibold">{summary?.dbSizeMb ?? "—"}MB</span>
      </span>
    </div>
  );
}

function HoneyDrips() {
  return (
    <div className="relative h-[26px] flex items-start justify-center gap-[28%] pt-0 pointer-events-none select-none">
      <span className="honey-drip" />
      <span className="honey-drip" />
      <span className="honey-drip" />
    </div>
  );
}

export function PageShell({
  title,
  status,
  statusTone = "operational",
  hideDrips = false,
  contentClassName = "",
  children,
}: {
  title: ReactNode;
  status?: string;
  statusTone?: Tone;
  hideDrips?: boolean;
  contentClassName?: string;
  children: ReactNode;
}) {
  return (
    <div className="relative flex flex-col h-full">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-primary/20 bg-black/20">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-foreground tracking-tight">{title}</h1>
          {status && <StatusPill label={status} tone={statusTone} />}
        </div>
        <div className="flex items-center gap-3">
          <TopStats />
          <div className="w-7 h-7 rounded-full bg-primary/20 text-primary border border-primary/40 flex items-center justify-center text-[10px] font-bold shadow-[0_0_8px_rgba(212,160,23,0.25)]">
            JS
          </div>
        </div>
      </header>

      {/* Honey drips divider */}
      {!hideDrips && <HoneyDrips />}

      {/* Content — shell owns vertical scroll; inner panels should NOT also overflow-hidden */}
      <div className={`flex-1 min-h-0 px-6 pb-6 ${hideDrips ? "pt-4" : "pt-2"} overflow-y-auto ${contentClassName}`}>
        {children}
      </div>
    </div>
  );
}

export default PageShell;
