import { ReactNode } from "react";
import { useListEvents } from "@/api";
import PageShell from "@/components/layout/page-shell";

function PlaceholderPage({ title, status = "IDLE", statusTone = "idle" as const, children }: { title: string; status?: string; statusTone?: "operational" | "live" | "sniffing" | "guided" | "configured" | "warning" | "idle"; children?: ReactNode }) {
  return (
    <PageShell title={title} status={status} statusTone={statusTone}>
      <div className="hive-panel flex-1 flex items-center justify-center text-muted-foreground p-8 h-full">
        {children || `${title} visualization coming soon`}
      </div>
    </PageShell>
  );
}

export function MapPage() {
  return <PlaceholderPage title="Geo Map" status="MAPPING" statusTone="sniffing" />;
}

export function AtriumPage() {
  return (
    <PageShell title="War Around You" status="SNIFFING" statusTone="sniffing">
      <div className="grid grid-cols-2 gap-6 h-full">
        <div className="hive-panel flex items-center justify-center text-muted-foreground text-sm tracking-widest uppercase">
          [ Radar Visualization ]
        </div>
        <div className="hive-panel flex items-center justify-center text-muted-foreground text-sm tracking-widest uppercase">
          [ Packet Capture Stream ]
        </div>
      </div>
    </PageShell>
  );
}

export function TimelinePage() {
  const { data: events, isLoading } = useListEvents({ limit: 10 });
  return (
    <PageShell title="Timeline" status="REPLAYING" statusTone="sniffing">
      <div className="hive-panel flex-1 p-8 overflow-y-auto h-full">
        {isLoading ? (
          <div className="animate-pulse bg-amber-900/20 h-full w-full rounded-lg"></div>
        ) : (
          <div className="space-y-8 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-primary/20">
            {events?.map((event) => (
              <div key={event.id} className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
                <div className="flex items-center justify-center w-10 h-10 rounded-full border-4 border-[#100a04] bg-primary/20 text-primary shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 shadow-[0_0_10px_rgba(212,160,23,0.3)] z-10">
                  <div className="w-2 h-2 rounded-full bg-primary"></div>
                </div>
                <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] bg-black/40 p-4 rounded border border-primary/20">
                  <div className="flex items-center justify-between mb-1">
                    <div className="font-bold text-primary">{event.eventType}</div>
                    <time className="font-mono text-xs text-muted-foreground">{new Date(event.timestamp).toLocaleTimeString()}</time>
                  </div>
                  <div className="text-sm text-foreground">{event.sourceIp}</div>
                  <div className="text-xs text-muted-foreground mt-2 font-mono break-all">{event.payload || event.command || event.raw}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </PageShell>
  );
}

export function FindingsPage() {
  return <PlaceholderPage title="Findings" status="ANALYZING" statusTone="sniffing" />;
}

export function EnrichmentPage() {
  return <PlaceholderPage title="Enrichment" status="ENRICHING" statusTone="sniffing" />;
}

export function SettingsPage() {
  return (
    <PageShell title="Settings" status="CONFIGURED" statusTone="configured">
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="hive-panel p-8 space-y-8">
        <section>
          <h2 className="text-lg font-bold text-primary mb-4 border-b border-primary/20 pb-2">API Integrations</h2>
          <div className="space-y-4">
            {['AbuseIPDB', 'GreyNoise', 'VirusTotal', 'Shodan'].map(api => (
              <div key={api} className="flex flex-col gap-2">
                <label className="text-sm font-bold text-foreground">{api} API Key</label>
                <input
                  type="password"
                  className="bg-black/50 border border-primary/30 rounded px-4 py-2 text-foreground font-mono focus:outline-none focus:border-primary w-full max-w-md"
                  placeholder={`Enter ${api} key...`}
                />
              </div>
            ))}
            <button className="bg-primary/20 text-primary border border-primary/50 font-bold px-6 py-2 rounded text-sm uppercase tracking-widest hover:bg-primary/40 transition-colors mt-4">
              Save Keys
            </button>
          </div>
        </section>
      </div>
    </div>
    </PageShell>
  );
}
