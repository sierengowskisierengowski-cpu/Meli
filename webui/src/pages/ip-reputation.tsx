import { useState } from "react";
import { useLookupIpReputation, getLookupIpReputationQueryKey } from "@/api";
import PageShell from "@/components/layout/page-shell";

export default function IpReputation() {
  const [searchInput, setSearchInput] = useState("");
  const [ipToLookup, setIpToLookup] = useState("");
  
  const { data: rep, isLoading, isError } = useLookupIpReputation(
    { ip: ipToLookup }, 
    { query: { enabled: !!ipToLookup, queryKey: getLookupIpReputationQueryKey({ ip: ipToLookup }) } }
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchInput.trim()) {
      setIpToLookup(searchInput.trim());
    }
  };

  return (
    <PageShell title="IP Reputation Lookup" status="MULTI-SOURCE" statusTone="operational">
    <div className="space-y-6 max-w-4xl mx-auto">
      <p className="text-sm text-muted-foreground">Query multiple threat intelligence sources (AbuseIPDB, GreyNoise, VirusTotal, Shodan) for a single IP address.</p>

      <form onSubmit={handleSubmit} className="flex gap-4">
        <input 
          type="text" 
          placeholder="Enter IP address (e.g. 192.168.1.1)" 
          className="flex-1 bg-black/50 border border-primary/30 rounded px-4 py-3 text-foreground font-mono focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all placeholder:font-sans placeholder:text-muted-foreground"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <button 
          type="submit" 
          disabled={!searchInput.trim() || isLoading}
          className="bg-primary text-primary-foreground font-bold uppercase tracking-widest px-8 py-3 rounded hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {isLoading ? 'Querying...' : 'Lookup'}
        </button>
      </form>

      {isError && (
        <div className="hive-panel p-6 border-red-500/50 bg-red-500/5">
          <p className="text-red-500 font-bold">Error looking up IP address. Ensure it is a valid public IP.</p>
        </div>
      )}

      {rep && !isLoading && (
        <div className="space-y-6 animate-in fade-in zoom-in duration-500">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-6">
            
            {/* Score Gauge */}
            <div className="hive-panel p-6 flex flex-col items-center justify-center">
              <div className="text-xs font-bold text-primary tracking-widest mb-6">ABUSE CONFIDENCE</div>
              <div className="relative w-48 h-48 flex items-center justify-center">
                <svg viewBox="0 0 100 100" className="w-full h-full transform -rotate-90">
                  <circle cx="50" cy="50" r="40" fill="transparent" stroke="rgba(212,160,23,0.1)" strokeWidth="8" />
                  <circle 
                    cx="50" cy="50" r="40" fill="transparent" 
                    stroke={rep.abuseConfidenceScore && rep.abuseConfidenceScore > 80 ? '#ef4444' : rep.abuseConfidenceScore && rep.abuseConfidenceScore > 40 ? '#f97316' : '#f59e0b'} 
                    strokeWidth="8" strokeDasharray="251.2" strokeDashoffset={251.2 - (251.2 * (rep.abuseConfidenceScore || 0)) / 100}
                    className="transition-all duration-1000 ease-out"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="font-mono-num text-5xl font-bold text-foreground">{rep.abuseConfidenceScore || 0}%</span>
                </div>
              </div>
            </div>

            {/* General Info */}
            <div className="hive-panel p-6 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h2 className="font-mono text-3xl font-bold text-primary">{rep.ip}</h2>
                  {rep.isKnownAttacker && <span className="bg-red-500/20 text-red-500 border border-red-500/30 text-xs px-2 py-1 rounded font-bold uppercase tracking-widest">KNOWN ATTACKER</span>}
                </div>
                <div className="text-muted-foreground flex gap-4 text-sm mt-2">
                  <span>{rep.country || 'Unknown Country'}</span>
                  <span>•</span>
                  <span className="truncate">{rep.org || 'Unknown Org'}</span>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
                {[
                  { label: "TOR NODE", value: rep.isTor ? "YES" : "NO", alert: rep.isTor },
                  { label: "VPN", value: rep.isVpn ? "YES" : "NO", alert: rep.isVpn },
                  { label: "HOSTING", value: rep.isHosting ? "YES" : "NO", alert: rep.isHosting },
                  { label: "VT POSITIVES", value: rep.virusTotalPositives != null ? rep.virusTotalPositives.toString() : "-", alert: rep.virusTotalPositives ? rep.virusTotalPositives > 0 : false }
                ].map(item => (
                  <div key={item.label} className="bg-black/40 p-3 rounded border border-primary/10">
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-1">{item.label}</div>
                    <div className={`font-bold ${item.alert ? 'text-red-500' : 'text-foreground'}`}>{item.value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Deep Intel */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="hive-panel p-6">
              <div className="text-xs font-bold text-primary tracking-widest mb-4">GREYNOISE CLASSIFICATION</div>
              <div className="flex items-center gap-4">
                <span className={`px-4 py-2 rounded uppercase font-bold tracking-widest border ${
                  rep.greynoiseClassification === 'malicious' ? 'bg-red-500/20 text-red-500 border-red-500/30' :
                  rep.greynoiseClassification === 'benign' ? 'bg-green-500/20 text-green-500 border-green-500/30' :
                  'bg-stone-500/20 text-stone-400 border-stone-500/30'
                }`}>
                  {rep.greynoiseClassification || 'Unknown'}
                </span>
                <span className="text-sm text-muted-foreground">
                  {rep.greynoiseClassification === 'malicious' ? 'Verified mass-scanner or attacker.' :
                   rep.greynoiseClassification === 'benign' ? 'Known legitimate service (e.g. search engine).' :
                   'No definitive classification available.'}
                </span>
              </div>
            </div>

            <div className="hive-panel p-6">
              <div className="text-xs font-bold text-primary tracking-widest mb-4">SHODAN OPEN PORTS</div>
              {rep.shodanPorts ? (
                <div className="flex flex-wrap gap-2">
                  {rep.shodanPorts.split(',').map((port, i) => (
                    <span key={i} className="font-mono text-sm bg-black/60 border border-primary/20 text-primary px-3 py-1 rounded">
                      {port.trim()}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground italic">No open ports identified or scan data unavailable.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
    </PageShell>
  );
}