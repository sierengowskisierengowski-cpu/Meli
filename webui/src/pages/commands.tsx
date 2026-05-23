import { useListCommands } from "@/api";
import { formatDistanceToNow } from "date-fns";
import PageShell from "@/components/layout/page-shell";

export default function Commands() {
  const { data: commands, isLoading } = useListCommands({ limit: 100 });

  return (
    <PageShell title="Executed Commands" status="LOGGING" statusTone="sniffing">
      <div className="hive-panel flex-1 overflow-hidden flex flex-col h-full">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-primary uppercase bg-black/40 border-b border-primary/20 sticky top-0 z-10">
              <tr>
                <th className="px-4 py-3 font-semibold tracking-widest w-[50%]">Command</th>
                <th className="px-4 py-3 font-semibold tracking-widest text-right">Count</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Source IP</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Session</th>
                <th className="px-4 py-3 font-semibold tracking-widest">Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground animate-pulse">
                    Loading commands...
                  </td>
                </tr>
              ) : commands?.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    No commands captured yet
                  </td>
                </tr>
              ) : (
                commands?.map((cmd) => (
                  <tr key={cmd.id} className="border-b border-primary/5 hover:bg-primary/5 transition-colors">
                    <td className="px-4 py-3 font-mono text-accent text-xs break-all leading-relaxed">
                      {cmd.command}
                    </td>
                    <td className="px-4 py-3 font-mono text-primary font-bold text-right">
                      {cmd.count ? <span className="bg-primary/20 px-1.5 py-0.5 rounded border border-primary/30">{cmd.count.toLocaleString()}</span> : '-'}
                    </td>
                    <td className="px-4 py-3 font-mono text-muted-foreground">{cmd.sourceIp}</td>
                    <td className="px-4 py-3 font-mono text-muted-foreground text-xs">{cmd.session ? cmd.session.substring(0, 8) : '-'}</td>
                    <td className="px-4 py-3 font-mono text-muted-foreground text-xs whitespace-nowrap">
                      {formatDistanceToNow(new Date(cmd.timestamp), { addSuffix: true })}
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