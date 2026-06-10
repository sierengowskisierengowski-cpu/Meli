import { useListAlerts, useAcknowledgeAlert } from "@/api";
import { formatDistanceToNow } from "date-fns";
import PageShell from "@/components/layout/page-shell";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "border-red-500 text-red-500",
  high: "border-orange-500 text-orange-500",
  medium: "border-amber-500 text-amber-500",
  low: "border-stone-500 text-stone-500",
  info: "border-stone-700 text-stone-400"
};

export default function Alerts() {
  const { data: alerts, isLoading } = useListAlerts();
  const ackMutation = useAcknowledgeAlert();

  const handleAcknowledge = (id: number) => {
    ackMutation.mutate({ id });
  };

  const unackedCount = alerts?.filter(a => !a.acknowledged).length ?? 0;
  return (
    <PageShell title="System Alerts" status={unackedCount > 0 ? `${unackedCount} UNACKED` : "ALL CLEAR"} statusTone={unackedCount > 0 ? "warning" : "operational"}>
      {isLoading ? (
        <div className="animate-pulse bg-amber-900/20 h-64 w-full rounded-lg"></div>
      ) : alerts?.length === 0 ? (
        <div className="hive-panel p-8 text-center text-muted-foreground">
          No active alerts
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {alerts?.map((alert) => {
            const severityColor = SEVERITY_COLORS[alert.severity.toLowerCase()] || SEVERITY_COLORS.info;
            const unackedClass = !alert.acknowledged ? "border-l-4 !border-l-amber-500 bg-amber-900/10" : "border-l-4 !border-l-transparent opacity-60";
            
            return (
              <div key={alert.id} className={`hive-panel p-4 flex items-center justify-between transition-all ${unackedClass}`}>
                <div className="flex-1 pr-6">
                  <div className="flex items-center gap-3 mb-1">
                    <span className={`text-[10px] px-2 py-0.5 rounded border uppercase font-bold tracking-wider ${severityColor}`}>
                      {alert.severity}
                    </span>
                    <span className="text-xs font-mono text-muted-foreground">
                      {formatDistanceToNow(new Date(alert.createdAt), { addSuffix: true })}
                    </span>
                  </div>
                  <h3 className="text-base font-bold text-foreground">{alert.title}</h3>
                  {alert.description && (
                    <p className="text-sm text-muted-foreground mt-1">{alert.description}</p>
                  )}
                  <div className="flex items-center gap-4 mt-2">
                    {alert.sourceIp && <span className="text-xs font-mono text-primary">IP: {alert.sourceIp}</span>}
                    {alert.service && <span className="text-xs text-muted-foreground border border-muted-foreground/30 px-1.5 py-0.5 rounded bg-black/40">{alert.service}</span>}
                  </div>
                </div>
                {!alert.acknowledged && (
                  <button 
                    onClick={() => handleAcknowledge(alert.id)}
                    disabled={ackMutation.isPending}
                    className="flex-shrink-0 bg-primary/20 hover:bg-primary/40 text-primary border border-primary/50 font-bold px-4 py-2 rounded text-sm transition-colors uppercase tracking-widest disabled:opacity-50"
                  >
                    Acknowledge
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}