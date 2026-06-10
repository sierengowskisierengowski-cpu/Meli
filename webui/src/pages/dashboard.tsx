import { useMemo } from "react";
import { 
  useGetDashboardSummary,
  useGetDashboardSeverity,
  useGetDashboardTopAttackers,
  useGetDashboardIntensity,
  useGetDashboardHoneypotFleet,
  useGetDashboardCapacity,
  getGetDashboardSummaryQueryKey,
} from "@/api";
import { LineChart, Line, AreaChart, Area, XAxis, ResponsiveContainer } from "recharts";
import PageShell from "@/components/layout/page-shell";

function generateSparklineData(value: number) {
  // Synthetic data for the sparklines
  const base = value / 24;
  return Array.from({ length: 24 }).map((_, i) => ({
    val: Math.max(0, base + (Math.random() - 0.5) * base * 0.5)
  }));
}

export default function Dashboard() {
  const { data: summary, isLoading: isLoadingSummary } = useGetDashboardSummary({ query: { refetchInterval: 10000, queryKey: getGetDashboardSummaryQueryKey() } });
  const { data: capacity, isLoading: isLoadingCapacity } = useGetDashboardCapacity();
  const { data: severity, isLoading: isLoadingSeverity } = useGetDashboardSeverity();
  const { data: topAttackers, isLoading: isLoadingAttackers } = useGetDashboardTopAttackers();
  const { data: intensity, isLoading: isLoadingIntensity } = useGetDashboardIntensity();
  const { data: fleet, isLoading: isLoadingFleet } = useGetDashboardHoneypotFleet();

  const eventsSparkline = useMemo(() => summary ? generateSparklineData(summary.eventsLast24h) : [], [summary?.eventsLast24h]);
  const alertsSparkline = useMemo(() => summary ? generateSparklineData(summary.criticalAlerts) : [], [summary?.criticalAlerts]);
  const attackersSparkline = useMemo(() => summary ? generateSparklineData(summary.uniqueAttackers) : [], [summary?.uniqueAttackers]);
  const honeypotsSparkline = useMemo(() => summary ? generateSparklineData(summary.honeypotsOnline) : [], [summary?.honeypotsOnline]);

  if (isLoadingSummary || !summary || !capacity || !severity || !topAttackers || !intensity || !fleet) {
    return (
      <PageShell title="Hive Command Center" status="BOOTING" statusTone="sniffing">
        <div className="animate-pulse bg-amber-900/20 h-full w-full rounded-lg min-h-[600px] flex items-center justify-center">
          <span className="text-primary font-mono tracking-widest">INITIALIZING HIVE...</span>
        </div>
      </PageShell>
    );
  }

  const SEVERITY_COLORS: Record<string, string> = {
    critical: "#ef4444",
    high: "#f97316",
    medium: "#f59e0b",
    low: "#78716c",
    info: "#44403c"
  };

  const maxSeverity = Math.max(severity.critical, severity.high, severity.medium, severity.low, severity.info);

  return (
    <PageShell title="Hive Command Center" status="OPERATIONAL" statusTone="operational">
    <div className="space-y-6">
      {/* ROW 1: KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "EVENTS / 24H", value: summary.eventsLast24h, change: summary.eventsChangePercent ? `${summary.eventsChangePercent > 0 ? '+' : ''}${summary.eventsChangePercent}%` : "—", data: eventsSparkline },
          { label: "CRITICAL ALERTS", value: summary.criticalAlerts, change: summary.criticalUnacknowledged ? `${summary.criticalUnacknowledged} unacked` : "All clear", data: alertsSparkline },
          { label: "UNIQUE ATTACKERS", value: summary.uniqueAttackers, change: summary.attackersNewToday ? `+${summary.attackersNewToday} today` : "—", data: attackersSparkline },
          { label: "HONEYPOTS ONLINE", value: `${summary.honeypotsOnline}/${summary.honeypotsTotal}`, change: "System stable", data: honeypotsSparkline },
        ].map((kpi, i) => (
          <div key={i} className="hive-panel relative h-[140px] overflow-hidden flex flex-col">
            <div className="absolute top-4 right-4 w-2 h-2 rounded-full bg-primary/80 shadow-[0_0_8px_rgba(212,160,23,0.8)]"></div>
            <div className="p-4 z-10 flex-1">
              <div className="text-xs font-bold text-primary tracking-widest mb-1 opacity-90">{kpi.label}</div>
              <div className="font-mono-num text-4xl font-bold text-foreground drop-shadow-md">{kpi.value}</div>
              <div className="text-xs text-muted-foreground mt-1 font-mono">{kpi.change}</div>
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-[50%] opacity-40">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={kpi.data}>
                  <Line type="monotone" dataKey="val" stroke="#f59e0b" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-[50%] bg-gradient-to-t from-[#f59e0b]/10 to-transparent pointer-events-none"></div>
          </div>
        ))}
      </div>

      {/* ROW 2: 3-column layout */}
      <div className="grid grid-cols-[35%_30%_35%] gap-4">
        {/* CAPACITY */}
        <div className="hive-panel p-5 flex flex-col items-center justify-between">
          <div className="text-xs font-bold text-primary tracking-widest w-full text-center">CAPACITY</div>
          
          <div className="relative w-40 h-40 my-4 flex items-center justify-center">
            {/* Background glow */}
            <div className="absolute inset-0 rounded-full amber-glow opacity-50"></div>
            
            {/* The Jar */}
            <div className="relative w-32 h-36 border-2 border-primary/40 rounded-b-2xl rounded-t-lg overflow-hidden bg-black/50">
              {/* Fill level */}
              <div 
                className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-accent to-primary/80 transition-all duration-1000 ease-in-out"
                style={{ height: `${Math.max(4, capacity.capacityPercent)}%` }}
              >
                {/* Honeycomb pattern overlay */}
                <div className="absolute inset-0 opacity-20" style={{ 
                  backgroundImage: `url("data:image/svg+xml,%3Csvg width='20' height='34.64101615137754' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M10 0l10 5.773502691896258v11.547005383792516l-10 5.773502691896258l-10-5.773502691896258V5.773502691896258L10 0zM10 11.547005383792516l10 5.773502691896258v11.547005383792516l-10 5.773502691896258l-10-5.773502691896258v-11.547005383792516L10 11.547005383792516z' fill='%23000' fill-rule='evenodd'/%3E%3C/svg%3E")`,
                  backgroundSize: '20px 34.64px'
                }}></div>
              </div>
            </div>
            
            {/* Percentage text */}
            <div className="absolute inset-0 flex items-center justify-center font-mono-num text-3xl font-bold text-foreground drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)] z-10">
              {Number(capacity.capacityPercent).toFixed(1)}%
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 w-full border-t border-primary/20 pt-4 mt-2">
            <div>
              <div className="text-[10px] text-muted-foreground uppercase">Last Strike</div>
              <div className="font-mono text-sm text-primary truncate" title={summary.lastStrikeIp}>{summary.lastStrikeIp}</div>
              <div className="text-[10px] text-muted-foreground">{new Date(summary.lastStrikeAt).toLocaleTimeString()}</div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-muted-foreground uppercase">Strikes / HR</div>
              <div className="font-mono text-sm text-primary">{summary.strikesPerHour}</div>
              <div className="text-[10px] text-accent">↑ {summary.peakStrikesPerHour} peak</div>
            </div>
          </div>
        </div>

        {/* SEVERITY */}
        <div className="hive-panel p-5 flex flex-col">
          <div className="text-xs font-bold text-primary tracking-widest mb-4">SEVERITY (24H)</div>
          <div className="flex-1 flex flex-col justify-center space-y-4">
            {(['critical', 'high', 'medium', 'low', 'info'] as const).map(level => {
              const count = severity[level];
              const pct = maxSeverity > 0 ? (count / maxSeverity) * 100 : 0;
              return (
                <div key={level} className="flex items-center gap-3">
                  <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: SEVERITY_COLORS[level] }}></div>
                  <div className="text-xs font-bold w-20 uppercase" style={{ color: SEVERITY_COLORS[level] }}>{level}</div>
                  <div className="flex-1 h-1.5 bg-black/40 rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: SEVERITY_COLORS[level] }}></div>
                  </div>
                  <div className="font-mono text-xs w-12 text-right text-muted-foreground">{count}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* TOP ATTACKERS */}
        <div className="hive-panel p-5 flex flex-col">
          <div className="text-xs font-bold text-primary tracking-widest mb-4">TOP ATTACKERS</div>
          <div className="flex-1 flex flex-col space-y-3">
            {topAttackers.slice(0, 5).map(attacker => (
              <div key={attacker.ip} className="flex items-center gap-3 bg-black/20 p-2 rounded border border-primary/10">
                <div className="bg-primary/20 text-primary text-[10px] font-bold px-1.5 py-0.5 rounded">#{attacker.rank}</div>
                <div className="font-mono text-sm text-primary flex-1">{attacker.ip}</div>
                <div className="bg-muted text-muted-foreground text-[10px] px-1.5 py-0.5 rounded border border-muted-foreground/20">
                  {attacker.countryCode || 'UN'} {attacker.asn ? `· ${attacker.asn.substring(0, 8)}` : ''}
                </div>
                <div className="font-mono text-sm font-bold text-accent">{attacker.attackCount.toLocaleString()}</div>
              </div>
            ))}
            {topAttackers.length === 0 && (
              <div className="text-sm text-muted-foreground text-center my-auto">No attackers recorded yet</div>
            )}
          </div>
        </div>
      </div>

      {/* ROW 3: 2 panels */}
      <div className="grid grid-cols-[60%_40%] gap-4">
        {/* ATTACK INTENSITY */}
        <div className="hive-panel p-5 flex flex-col h-[280px]">
          <div className="flex items-center justify-between mb-4">
            <div className="text-xs font-bold text-primary tracking-widest">24H ATTACK INTENSITY</div>
            <div className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded border border-primary/20">HOURLY</div>
          </div>
          <div className="flex-1 w-full -ml-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={intensity} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="hour" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#92400e' }} dy={10} />
                <Area type="monotone" dataKey="count" stroke="#f59e0b" strokeWidth={2} fillOpacity={1} fill="url(#colorCount)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* HONEYPOT FLEET */}
        <div className="hive-panel p-5 flex flex-col h-[280px]">
          <div className="flex items-center justify-between mb-4">
            <div className="text-xs font-bold text-primary tracking-widest">HONEYPOT FLEET</div>
            <div className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded border border-primary/20">
              {fleet.filter(f => f.status === 'online').length}/{fleet.length}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto space-y-2 pr-2">
            {fleet.map(service => (
              <div key={service.id} className="flex items-center justify-between p-2 border-b border-primary/10 hover:bg-primary/5 transition-colors">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${
                    service.status === 'online' ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 
                    service.status === 'degraded' ? 'bg-yellow-500 shadow-[0_0_8px_rgba(234,179,8,0.6)]' : 
                    'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]'
                  }`}></div>
                  <div>
                    <div className="text-sm font-semibold text-foreground">{service.name}</div>
                    <div className="text-[10px] text-muted-foreground font-mono">{service.protocol.toUpperCase()} / {service.port}</div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm text-accent">{service.eventsToday?.toLocaleString() || 0}</div>
                  <div className="text-[10px] text-muted-foreground">events today</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
    </PageShell>
  );
}