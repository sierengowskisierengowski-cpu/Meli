import { useListReports } from "@/api";
import PageShell from "@/components/layout/page-shell";

export default function Reports() {
  const { data: reports, isLoading } = useListReports();

  return (
    <PageShell title="Intelligence Reports" status={`${reports?.length ?? 0} ARCHIVED`} statusTone="operational">
      {isLoading ? (
        <div className="animate-pulse bg-amber-900/20 h-64 w-full rounded-lg"></div>
      ) : reports?.length === 0 ? (
        <div className="hive-panel p-8 text-center text-muted-foreground">
          No reports generated yet
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {reports?.map((report) => (
            <div key={report.id} className="hive-panel p-5 flex flex-col h-48 cursor-pointer hover:amber-glow transition-all">
              <div className="flex justify-between items-start mb-2">
                <span className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded border border-primary/20 uppercase tracking-widest">
                  {report.type}
                </span>
                <span className="text-xs font-mono text-muted-foreground">
                  {new Date(report.createdAt).toLocaleDateString()}
                </span>
              </div>
              <h3 className="text-lg font-bold text-foreground mb-2 line-clamp-1">{report.title}</h3>
              <p className="text-sm text-muted-foreground flex-1 line-clamp-3">
                {report.summary || "No summary available."}
              </p>
              
              <div className="flex items-center gap-2 mt-4 pt-3 border-t border-primary/10">
                {report.eventCount !== undefined && (
                  <div className="flex items-center gap-1 text-xs">
                    <span className="text-muted-foreground">Events:</span>
                    <span className="font-mono text-primary">{report.eventCount.toLocaleString()}</span>
                  </div>
                )}
                {report.attackerCount !== undefined && (
                  <div className="flex items-center gap-1 text-xs ml-4">
                    <span className="text-muted-foreground">Actors:</span>
                    <span className="font-mono text-accent">{report.attackerCount.toLocaleString()}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}