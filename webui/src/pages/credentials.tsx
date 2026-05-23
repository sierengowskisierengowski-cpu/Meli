import { useState } from "react";
import { useListCredentials } from "@/api";
import { formatDistanceToNow } from "date-fns";
import { Eye, EyeOff } from "lucide-react";
import PageShell from "@/components/layout/page-shell";

export default function Credentials() {
  const { data: credentials, isLoading } = useListCredentials({ limit: 100 });
  const [revealedIds, setRevealedIds] = useState<Set<number>>(new Set());

  const toggleReveal = (id: number) => {
    setRevealedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <PageShell title="Harvested Credentials" status="CAPTURING" statusTone="sniffing">
      <div className="hive-panel flex-1 overflow-hidden flex flex-col h-full">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-primary uppercase bg-black/40 border-b border-primary/20 sticky top-0 z-10">
              <tr>
                <th className="px-4 py-3 font-semibold tracking-widest">Username</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Password</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Service</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Attempts</th>
                <th className="px-4 py-3 font-semibold tracking-widest">First Seen</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground animate-pulse">
                    Loading credentials...
                  </td>
                </tr>
              ) : credentials?.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    No credentials captured yet
                  </td>
                </tr>
              ) : (
                credentials?.map((cred) => {
                  const isRevealed = revealedIds.has(cred.id);
                  return (
                    <tr key={cred.id} className="border-b border-primary/5 hover:bg-primary/5 transition-colors">
                      <td className="px-4 py-3 font-mono text-primary font-bold">{cred.username}</td>
                      <td className="px-4 py-3 font-mono">
                        <div className="flex items-center gap-2">
                          <span className={isRevealed ? "text-red-400" : "text-muted-foreground tracking-widest"}>
                            {isRevealed ? cred.password : "••••••••"}
                          </span>
                          <button 
                            onClick={() => toggleReveal(cred.id)}
                            className="text-muted-foreground hover:text-primary transition-colors focus:outline-none"
                            aria-label={isRevealed ? "Hide password" : "Show password"}
                          >
                            {isRevealed ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {cred.service && (
                          <span className="bg-secondary/50 border border-secondary text-secondary-foreground text-[10px] px-2 py-0.5 rounded font-mono">
                            {cred.service}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-accent font-bold text-right">{cred.count.toLocaleString()}</td>
                      <td className="px-4 py-3 font-mono text-muted-foreground text-xs whitespace-nowrap">
                        {new Date(cred.firstSeen).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3 font-mono text-muted-foreground text-xs whitespace-nowrap">
                        {cred.lastSeen ? formatDistanceToNow(new Date(cred.lastSeen), { addSuffix: true }) : '-'}
                      </td>
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