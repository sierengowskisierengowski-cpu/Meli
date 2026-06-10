import { useListSessions } from "@/api";
import PageShell from "@/components/layout/page-shell";

function formatDuration(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export default function Sessions() {
  const { data: sessions, isLoading } = useListSessions({ limit: 100 });

  return (
    <PageShell title="Interactive Sessions" status="MONITORING" statusTone="sniffing">
      <div className="hive-panel flex-1 overflow-hidden flex flex-col h-full">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-primary uppercase bg-black/40 border-b border-primary/20 sticky top-0 z-10">
              <tr>
                <th className="px-4 py-3 font-semibold tracking-widest">Source IP</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Location</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Duration</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Commands</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Tarpit (s)</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Status</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground animate-pulse">
                    Loading sessions...
                  </td>
                </tr>
              ) : sessions?.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    No sessions captured yet
                  </td>
                </tr>
              ) : (
                sessions?.map((session) => (
                  <tr key={session.id} className="border-b border-primary/5 hover:bg-primary/5 transition-colors">
                    <td className="px-4 py-3 font-mono text-primary font-bold">
                      {session.sourceIp}
                      {session.isSticky && <span className="ml-2 text-[10px] bg-red-500/20 text-red-500 border border-red-500/30 px-1 py-0.5 rounded">STICKY</span>}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{session.country || 'Unknown'}</td>
                    <td className="px-4 py-3 font-mono text-right text-accent">{formatDuration(session.duration)}</td>
                    <td className="px-4 py-3 font-mono text-right">{session.commandCount?.toLocaleString() || 0}</td>
                    <td className="px-4 py-3 font-mono text-right text-muted-foreground">{session.tarpitSeconds || 0}</td>
                    <td className="px-4 py-3">
                      {session.endedAt ? (
                        <span className="text-[10px] text-muted-foreground uppercase">Closed</span>
                      ) : (
                        <span className="text-[10px] text-green-500 uppercase font-bold flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
                          Active
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </PageShell>
  );
}