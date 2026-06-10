import { AlertCircle } from "lucide-react";
import { Link } from "wouter";
import PageShell from "@/components/layout/page-shell";

export default function NotFound() {
  return (
    <PageShell title="Not Found" status="LOST IN THE HIVE" statusTone="warning">
      <div className="h-full flex items-center justify-center">
        <div className="hive-panel max-w-md w-full p-8 text-center space-y-4">
          <div className="flex items-center justify-center gap-3">
            <AlertCircle className="h-8 w-8 text-red-500" />
            <h2 className="text-2xl font-bold text-foreground">404</h2>
          </div>
          <p className="text-sm text-muted-foreground">
            That route isn't part of the hive. Check the sidebar or head back to the command center.
          </p>
          <Link href="/">
            <button className="bg-primary text-primary-foreground font-bold uppercase tracking-widest px-6 py-2 rounded text-sm hover:bg-primary/90 transition-colors shadow-[0_0_14px_rgba(212,160,23,0.35)]">
              Return to Dashboard
            </button>
          </Link>
        </div>
      </div>
    </PageShell>
  );
}
