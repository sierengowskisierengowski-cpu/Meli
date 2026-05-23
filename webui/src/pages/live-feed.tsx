import { useListEvents, getListEventsQueryKey } from "@/api";
import { formatDistanceToNow } from "date-fns";
import PageShell from "@/components/layout/page-shell";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "border-red-500 text-red-500 bg-red-500/10",
  high: "border-orange-500 text-orange-500 bg-orange-500/10",
  medium: "border-amber-500 text-amber-500 bg-amber-500/10",
  low: "border-stone-500 text-stone-500 bg-stone-500/10",
  info: "border-stone-700 text-stone-400 bg-stone-800/30"
};

export default function LiveFeed() {
  const { data: events, isLoading } = useListEvents({ limit: 50 }, { query: { refetchInterval: 10000, queryKey: getListEventsQueryKey({ limit: 50 }) } });

  return (
    <PageShell title="Live Feed" status="LIVE" statusTone="live">
      <div className="hive-panel flex-1 overflow-hidden flex flex-col h-full">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-primary uppercase bg-black/40 border-b border-primary/20 sticky top-0 z-10">
              <tr>
                <th className="px-4 py-3 font-semibold tracking-widest">Time</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Source IP</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Location</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Service</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Type</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Severity</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Context</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground animate-pulse">
                    Monitoring grid...
                  </td>
                </tr>
              ) : events?.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                    No events captured yet
                  </td>
                </tr>
              ) : (
                events?.map((event) => {
                  const severityClass = SEVERITY_COLORS[event.severity?.toLowerCase() || "info"] || SEVERITY_COLORS.info;
                  return (
                    <tr key={event.id} className="border-b border-primary/5 hover:bg-primary/5 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground whitespace-nowrap">{formatDistanceToNow(new Date(event.timestamp), { addSuffix: true })}</td>
                      <td className="px-4 py-3 font-mono text-primary font-bold">{event.sourceIp}</td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">{event.sourceCountry || event.sourceCountryCode || "—"}</td>
                      <td className="px-4 py-3 text-xs">{event.service || "—"}</td>
                      <td className="px-4 py-3 text-xs uppercase tracking-wider text-accent">{event.eventType}</td>
                      <td className="px-4 py-3"><span className={`text-[10px] px-2 py-0.5 rounded border uppercase font-bold tracking-wider ${severityClass}`}>{event.severity}</span></td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground truncate max-w-xs" title={event.payload || event.command || event.raw || ""}>{(event.payload || event.command || event.raw || "").substring(0, 80)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </PageShell>
  );
}
