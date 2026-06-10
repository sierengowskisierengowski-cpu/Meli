import { Link, useLocation } from "wouter";
import {
  LayoutDashboard, Radio, Map, Users, Key, Terminal,
  Package, Server, GitCommit, Shield, Network, Bell,
  FileText, Monitor, Activity, Search, Zap, Settings, Wand2, Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { icon: LayoutDashboard, label: "Dashboard", href: "/" },
  { icon: Radio, label: "Live Feed", href: "/live-feed" },
  { icon: Map, label: "Geo Map", href: "/map" },
  { icon: Users, label: "Attackers", href: "/attackers" },
  { icon: Key, label: "Credentials", href: "/credentials" },
  { icon: Terminal, label: "Commands", href: "/commands" },
  { icon: Package, label: "Payloads", href: "/payloads" },
  { icon: Server, label: "Services", href: "/services" },
  { icon: GitCommit, label: "Timeline", href: "/timeline" },
  { icon: Shield, label: "IP Reputation", href: "/ip-reputation" },
  { icon: Network, label: "Botnets", href: "/botnets" },
  { icon: Bell, label: "Alerts", href: "/alerts" },
  { icon: FileText, label: "Reports", href: "/reports" },
  { icon: Monitor, label: "Atrium Kiosk", href: "/atrium" },
  { icon: Activity, label: "Sessions", href: "/sessions" },
  { icon: Search, label: "Findings", href: "/findings" },
  { icon: Zap, label: "Enrichment", href: "/enrichment" },
  { icon: Settings, label: "Settings", href: "/settings", utility: true },
  { icon: Wand2, label: "Setup Wizard", href: "/setup-wizard", utility: true, badge: "GUIDED" as const },
];

export default function Sidebar() {
  const [location] = useLocation();

  return (
    <aside className="w-[220px] flex-shrink-0 border-r border-primary/25 bg-sidebar flex flex-col h-screen fixed left-0 top-0 z-30 overflow-hidden">
      {/* Background honeycomb decoration — bottom left */}
      <div
        className="absolute -bottom-6 -left-10 w-[260px] h-[260px] hex-pattern-lg opacity-25 pointer-events-none"
        aria-hidden
      />
      <div
        className="absolute -top-12 -right-16 w-[200px] h-[200px] hex-pattern opacity-15 pointer-events-none"
        aria-hidden
      />

      {/* Brand header */}
      <div className="relative px-4 py-4 flex items-center justify-between border-b border-primary/25 bg-black/30">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 flex items-center justify-center rounded-md bg-primary/15 border border-primary/40 text-primary shadow-[0_0_12px_rgba(212,160,23,0.4)]">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L2 7V17L12 22L22 17V7L12 2Z" />
            </svg>
          </div>
          <div className="leading-tight">
            <div className="text-sm font-bold text-foreground tracking-[0.18em]">MELI</div>
            <div className="text-[9px] tracking-[0.2em] uppercase text-primary/70 font-mono">V 2.3.0 HIVE</div>
          </div>
        </div>
        <div className="w-7 h-7 rounded-full bg-primary/15 text-primary border border-primary/40 flex items-center justify-center text-[10px] font-bold shadow-[0_0_8px_rgba(212,160,23,0.25)]">
          JS
        </div>
      </div>

      {/* Nav */}
      <nav className="relative flex-1 overflow-y-auto py-2">
        {NAV_ITEMS.map((item, i) => {
          const isActive = location === item.href;
          const isUtilityStart = (item as { utility?: boolean }).utility && !(NAV_ITEMS[i - 1] as { utility?: boolean })?.utility;
          return (
            <div key={item.href}>
              {isUtilityStart && (
                <div className="mx-4 my-2 border-t border-dashed border-primary/20" />
              )}
              <Link href={item.href} className="block group">
                <div
                  className={cn(
                    "flex items-center gap-3 px-4 py-[7px] text-[13px] transition-colors relative border-l-[3px]",
                    isActive
                      ? "text-primary bg-primary/10 border-primary shadow-[inset_0_0_18px_rgba(212,160,23,0.18)]"
                      : "text-muted-foreground border-transparent hover:text-foreground hover:bg-primary/5"
                  )}
                >
                  <item.icon className="w-[15px] h-[15px]" strokeWidth={1.75} />
                  <span className={cn(isActive && "text-foreground")}>{item.label}</span>
                  {item.badge ? (
                    <span className="ml-auto text-[9px] px-1.5 py-[2px] rounded uppercase font-bold tracking-wider bg-green-500/20 text-green-400 border border-green-500/35">
                      {item.badge}
                    </span>
                  ) : !isActive ? (
                    <span className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity text-[9px] px-1.5 py-[1px] rounded uppercase font-bold tracking-wider text-primary/60 border border-primary/25">
                      CLICK
                    </span>
                  ) : null}
                </div>
              </Link>
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="relative p-4 border-t border-primary/25 bg-black/30 space-y-3">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.7)]" />
          All systems nominal
        </div>
        <Link href="/atrium">
          <button className="w-full bg-primary text-primary-foreground font-semibold rounded text-[12px] py-2 tracking-wide shadow-[0_0_14px_rgba(212,160,23,0.45)] hover:bg-accent transition-colors">
            Launch Atrium
          </button>
        </Link>
        <button className="w-full flex items-center justify-center gap-1.5 text-[11px] py-1.5 rounded text-muted-foreground border border-primary/25 hover:text-foreground hover:border-primary/45 transition-colors">
          <Lock className="w-3 h-3" />
          Lock
        </button>
      </div>
    </aside>
  );
}
