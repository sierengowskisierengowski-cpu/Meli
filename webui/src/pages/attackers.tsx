import { useState } from "react";
import { useListAttackers, useGetAttacker, useGetAttackerReputation, getGetAttackerQueryKey, getGetAttackerReputationQueryKey } from "@/api";
import { formatDistanceToNow } from "date-fns";
import { X } from "lucide-react";
import PageShell from "@/components/layout/page-shell";

function AttackerDetailPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: attacker, isLoading: isLoadingAttacker } = useGetAttacker(id, { query: { enabled: !!id, queryKey: getGetAttackerQueryKey(id) } });
  
  // Note: we'd need a queryKey for reputation, but we'll assume it works if we don't pass it or pass a derived one if it was provided in the generated types.
  // Actually, the api-client might not have a specific hook for reputation by ID if we use useGetAttackerReputation, but we'll assume it takes ID.
  const { data: reputation, isLoading: isLoadingReputation } = useGetAttackerReputation(id, { query: { enabled: !!id, queryKey: getGetAttackerReputationQueryKey(id) } });

  if (isLoadingAttacker) {
    return (
      <div className="absolute right-0 top-0 bottom-0 w-[400px] hive-panel border-l border-primary/30 z-20 flex items-center justify-center p-6">
        <div className="animate-pulse bg-amber-900/20 h-full w-full rounded-lg"></div>
      </div>
    );
  }

  if (!attacker) return null;

  return (
    <div className="absolute right-0 top-0 bottom-0 w-[400px] hive-panel border-l border-primary/30 z-20 flex flex-col shadow-2xl">
      <div className="flex items-center justify-between p-4 border-b border-primary/20">
        <h2 className="font-bold text-lg text-primary font-mono">{attacker.ip}</h2>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X className="w-5 h-5" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div>
          <div className="text-[10px] font-bold text-primary tracking-widest mb-2">OVERVIEW</div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-muted-foreground">Country</div>
              <div className="text-sm">{attacker.country || attacker.countryCode || 'Unknown'}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">ASN / Org</div>
              <div className="text-sm truncate" title={attacker.asn || attacker.org || ''}>{attacker.asn || attacker.org || '-'}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">First Seen</div>
              <div className="text-sm font-mono text-muted-foreground">{new Date(attacker.firstSeen).toLocaleDateString()}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Last Seen</div>
              <div className="text-sm font-mono text-muted-foreground">{formatDistanceToNow(new Date(attacker.lastSeen), { addSuffix: true })}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Total Attacks</div>
              <div className="text-sm font-mono text-accent font-bold">{attacker.attackCount.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Risk Score</div>
              <div className="text-sm font-mono text-red-500 font-bold">{attacker.riskScore || '-'}</div>
            </div>
          </div>
        </div>

        {isLoadingReputation ? (
           <div className="animate-pulse bg-amber-900/20 h-32 w-full rounded-lg"></div>
        ) : reputation ? (
          <div>
            <div className="text-[10px] font-bold text-primary tracking-widest mb-2">REPUTATION INTEL</div>
            <div className="space-y-3">
              {reputation.abuseConfidenceScore != null && (
                <div className="flex justify-between items-center bg-black/40 p-2 rounded">
                  <span className="text-xs text-muted-foreground">Abuse Confidence</span>
                  <span className="font-mono text-red-500">{reputation.abuseConfidenceScore}%</span>
                </div>
              )}
              {reputation.isTor && (
                <div className="flex justify-between items-center bg-black/40 p-2 rounded">
                  <span className="text-xs text-muted-foreground">Network Type</span>
                  <span className="text-xs font-bold text-orange-500 uppercase tracking-widest">Tor Exit Node</span>
                </div>
              )}
              {reputation.virusTotalPositives != null && (
                <div className="flex justify-between items-center bg-black/40 p-2 rounded">
                  <span className="text-xs text-muted-foreground">VT Positives</span>
                  <span className="font-mono text-red-500">{reputation.virusTotalPositives}</span>
                </div>
              )}
              {reputation.shodanPorts && (
                <div className="bg-black/40 p-2 rounded">
                  <span className="text-xs text-muted-foreground block mb-1">Open Ports</span>
                  <div className="font-mono text-xs text-primary">{reputation.shodanPorts}</div>
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function Attackers() {
  const { data: attackers, isLoading } = useListAttackers({ limit: 100 });
  const [selectedAttackerId, setSelectedAttackerId] = useState<number | null>(null);

  return (
    <PageShell title="Attackers" status={`${attackers?.length ?? 0} PROFILED`} statusTone="sniffing">
    <div className="relative h-full overflow-hidden">
      <div className="hive-panel flex-1 overflow-hidden flex flex-col h-full">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-primary uppercase bg-black/40 border-b border-primary/20 sticky top-0 z-10">
              <tr>
                <th className="px-4 py-3 font-semibold tracking-widest w-16">Rank</th>
                <th className="px-4 py-3 font-semibold tracking-widest">IP Address</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Country</th>
                <th className="px-4 py-3 font-semibold tracking-widest">ASN / Org</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Attacks</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Risk Score</th>
                <th className="px-4 py-3 font-semibold tracking-widest">First Seen</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-muted-foreground animate-pulse">
                    Loading attacker profiles...
                  </td>
                </tr>
              ) : attackers?.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">
                    No attackers recorded yet
                  </td>
                </tr>
              ) : (
                attackers?.map((attacker, idx) => (
                  <tr 
                    key={attacker.id} 
                    onClick={() => setSelectedAttackerId(attacker.id)}
                    className={`border-b border-primary/5 hover:bg-primary/10 transition-colors cursor-pointer ${selectedAttackerId === attacker.id ? 'bg-primary/20' : ''}`} 
                    data-testid={`row-attacker-${attacker.id}`}
                  >
                    <td className="px-4 py-3 font-mono text-muted-foreground text-xs text-center">{idx + 1}</td>
                    <td className="px-4 py-3 font-mono text-primary font-bold">
                      {attacker.ip}
                      {attacker.isSticky && <span className="ml-2 text-[10px] bg-red-500/20 text-red-500 border border-red-500/30 px-1 py-0.5 rounded">STICKY</span>}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{attacker.country || attacker.countryCode || 'Unknown'}</td>
                    <td className="px-4 py-3 text-muted-foreground text-xs truncate max-w-[200px]" title={attacker.asn || attacker.org || ''}>
                      {attacker.asn || attacker.org || '-'}
                    </td>
                    <td className="px-4 py-3 font-mono text-accent font-bold text-right">{attacker.attackCount.toLocaleString()}</td>
                    <td className="px-4 py-3">
                      {attacker.riskScore != null ? (
                        <div className="w-24 h-1.5 bg-black/40 rounded-full overflow-hidden border border-primary/10">
                          <div className={`h-full rounded-full ${attacker.riskScore > 80 ? 'bg-red-500' : attacker.riskScore > 50 ? 'bg-orange-500' : 'bg-primary'}`} style={{ width: `${attacker.riskScore}%` }}></div>
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-xs">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-muted-foreground text-xs whitespace-nowrap">
                      {new Date(attacker.firstSeen).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 font-mono text-muted-foreground text-xs whitespace-nowrap">
                      {formatDistanceToNow(new Date(attacker.lastSeen), { addSuffix: true })}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedAttackerId && (
        <AttackerDetailPanel id={selectedAttackerId} onClose={() => setSelectedAttackerId(null)} />
      )}
    </div>
    </PageShell>
  );
}