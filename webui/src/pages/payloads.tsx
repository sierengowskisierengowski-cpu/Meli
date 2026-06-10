import { useListPayloads } from "@/api";
import { formatDistanceToNow } from "date-fns";
import { Copy } from "lucide-react";
import PageShell from "@/components/layout/page-shell";

export default function Payloads() {
  const { data: payloads, isLoading } = useListPayloads({ limit: 100 });

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <PageShell title="Captured Payloads" status="QUARANTINED" statusTone="warning">
      <div className="hive-panel flex-1 overflow-hidden flex flex-col h-full">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-primary uppercase bg-black/40 border-b border-primary/20 sticky top-0 z-10">
              <tr>
                <th className="px-4 py-3 font-semibold tracking-widest">Filename</th>
                <th className="px-4 py-3 font-semibold tracking-widest">SHA-256</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Threat</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Size</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Downloads</th>
                <th className="px-4 py-3 font-semibold tracking-widest">First Seen</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground animate-pulse">
                    Loading payloads...
                  </td>
                </tr>
              ) : payloads?.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                    No payloads captured yet
                  </td>
                </tr>
              ) : (
                payloads?.map((payload) => (
                  <tr key={payload.id} className="border-b border-primary/5 hover:bg-primary/5 transition-colors">
                    <td className="px-4 py-3 font-mono text-primary font-bold">{payload.filename}</td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                      <div className="flex items-center gap-2">
                        <span className="truncate w-32 block">{payload.sha256}</span>
                        <button onClick={() => copyToClipboard(payload.sha256)} className="hover:text-primary transition-colors focus:outline-none" aria-label="Copy hash">
                          <Copy className="w-3 h-3" />
                        </button>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {payload.threatName ? (
                        <span className="bg-red-500/20 text-red-500 border border-red-500/30 text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-wider">
                          {payload.threatName}
                        </span>
                      ) : (
                        <span className="text-muted-foreground text-xs italic">Unknown</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-right">{(payload.size / 1024).toFixed(1)} KB</td>
                    <td className="px-4 py-3 font-mono text-accent font-bold text-right">{payload.downloadCount?.toLocaleString() || 0}</td>
                    <td className="px-4 py-3 font-mono text-muted-foreground text-xs whitespace-nowrap">
                      {new Date(payload.firstSeen).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 font-mono text-muted-foreground text-xs whitespace-nowrap">
                      {payload.lastSeen ? formatDistanceToNow(new Date(payload.lastSeen), { addSuffix: true }) : '-'}
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