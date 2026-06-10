import { useListServices } from "@/api";
import { formatDistanceToNow } from "date-fns";
import PageShell from "@/components/layout/page-shell";

export default function Services() {
  const { data: services, isLoading } = useListServices();

  return (
    <PageShell title="Active Services" status="OPERATIONAL" statusTone="operational">
      {isLoading ? (
        <div className="animate-pulse bg-amber-900/20 h-64 w-full rounded-lg"></div>
      ) : services?.length === 0 ? (
        <div className="hive-panel p-8 text-center text-muted-foreground">
          No services configured
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {services?.map((service) => (
            <div key={service.id} className="hive-panel p-5 flex flex-col">
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-3">
                  <div className={`w-3 h-3 rounded-full ${
                    service.status === 'online' ? 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.6)]' : 
                    service.status === 'degraded' ? 'bg-yellow-500 shadow-[0_0_10px_rgba(234,179,8,0.6)]' : 
                    'bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.6)]'
                  }`}></div>
                  <h3 className="text-lg font-bold text-foreground">{service.name}</h3>
                </div>
                <div className="bg-black/40 text-primary border border-primary/20 text-xs px-2 py-1 rounded font-mono">
                  {service.protocol.toUpperCase()} / {service.port}
                </div>
              </div>
              
              <div className="mt-auto grid grid-cols-2 gap-4 border-t border-primary/10 pt-4">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">Events Today</div>
                  <div className="font-mono text-xl font-bold text-accent">{service.eventsToday?.toLocaleString() || 0}</div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">Last Seen</div>
                  <div className="font-mono text-sm text-primary">
                    {service.lastSeen ? formatDistanceToNow(new Date(service.lastSeen), { addSuffix: true }) : '-'}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}