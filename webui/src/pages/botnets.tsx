import { useListBotnets } from "@/api";
import PageShell from "@/components/layout/page-shell";

export default function Botnets() {
  const { data: botnets, isLoading } = useListBotnets();

  return (
    <PageShell title="Identified Botnets" status={`${botnets?.length ?? 0} TRACKED`} statusTone="warning">
      {isLoading ? (
        <div className="animate-pulse bg-amber-900/20 h-64 w-full rounded-lg"></div>
      ) : botnets?.length === 0 ? (
        <div className="hive-panel p-8 text-center text-muted-foreground">
          No botnets identified
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {botnets?.map((botnet) => (
            <div key={botnet.id} className="hive-panel p-5 flex flex-col">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 className="text-xl font-bold text-foreground flex items-center gap-2">
                    {botnet.name}
                    {botnet.family && (
                      <span className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded border border-primary/20 uppercase tracking-widest font-normal">
                        Family: {botnet.family}
                      </span>
                    )}
                  </h3>
                  <div className="text-xs font-mono text-muted-foreground mt-1">
                    First seen: {new Date(botnet.firstSeen).toLocaleDateString()}
                  </div>
                </div>
                <div className="flex flex-col items-end">
                  <span className={`text-[10px] px-2 py-0.5 rounded uppercase font-bold tracking-wider ${
                    botnet.riskLevel === 'high' ? 'bg-red-500/20 text-red-500 border border-red-500/30' :
                    botnet.riskLevel === 'medium' ? 'bg-orange-500/20 text-orange-500 border border-orange-500/30' :
                    'bg-amber-500/20 text-amber-500 border border-amber-500/30'
                  }`}>
                    {botnet.riskLevel || 'Unknown'} Risk
                  </span>
                </div>
              </div>
              
              <div className="grid grid-cols-[1fr_2fr] gap-6 mt-2">
                <div className="bg-black/40 p-4 rounded border border-primary/10 flex flex-col items-center justify-center text-center">
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">Active Nodes</div>
                  <div className="font-mono-num text-4xl font-bold text-accent">{botnet.nodeCount.toLocaleString()}</div>
                </div>
                
                <div className="space-y-4">
                  <div>
                    <div className="text-xs font-bold text-primary tracking-widest mb-2">C2 SERVERS</div>
                    {botnet.c2Servers && botnet.c2Servers.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {botnet.c2Servers.map((ip, i) => (
                          <span key={i} className="font-mono text-xs bg-black/60 border border-muted-foreground/30 px-2 py-1 rounded text-red-400">
                            {ip}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground italic">Unknown</div>
                    )}
                  </div>
                  
                  <div>
                    <div className="text-xs font-bold text-primary tracking-widest mb-2">TARGETED SERVICES</div>
                    {botnet.targetedServices && botnet.targetedServices.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {botnet.targetedServices.map((svc, i) => (
                          <span key={i} className="text-xs bg-secondary/50 border border-secondary text-secondary-foreground px-2 py-1 rounded">
                            {svc}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground italic">Unknown</div>
                    )}
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