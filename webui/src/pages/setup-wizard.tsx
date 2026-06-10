import PageShell from "@/components/layout/page-shell";

export default function SetupWizard() {
  return (
    <PageShell title="First-Run Setup Wizard" status="GUIDED" statusTone="guided">
    <div className="flex flex-col items-center pt-6 pb-24 px-4">
      <div className="text-center mb-10 max-w-2xl">
        <div className="relative w-32 h-36 mx-auto mb-8">
          <div className="absolute inset-0 rounded-full amber-glow opacity-50"></div>
          <div className="relative w-full h-full border-2 border-primary/40 rounded-b-3xl rounded-t-xl overflow-hidden bg-black/50">
            <div 
              className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-accent to-primary/80"
              style={{ height: '78%' }}
            >
              <div className="absolute inset-0 opacity-20" style={{ 
                backgroundImage: `url("data:image/svg+xml,%3Csvg width='20' height='34.64101615137754' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M10 0l10 5.773502691896258v11.547005383792516l-10 5.773502691896258l-10-5.773502691896258V5.773502691896258L10 0zM10 11.547005383792516l10 5.773502691896258v11.547005383792516l-10 5.773502691896258l-10-5.773502691896258v-11.547005383792516L10 11.547005383792516z' fill='%23000' fill-rule='evenodd'/%3E%3C/svg%3E")`,
                backgroundSize: '20px 34.64px'
              }}></div>
            </div>
          </div>
        </div>

        <div className="inline-block bg-primary/10 text-primary border border-primary/20 px-3 py-1 rounded-full text-xs font-bold tracking-widest uppercase mb-4 shadow-[0_0_15px_rgba(212,160,23,0.15)]">
          FIRST-RUN SETUP
        </div>
        <h1 className="text-4xl font-bold text-foreground mb-4">Welcome to the Hive</h1>
        <p className="text-muted-foreground text-lg mb-6">
          Six guided steps to a fully-armed honeypot command center...
        </p>
        <div className="inline-block bg-black/40 text-muted-foreground border border-muted-foreground/30 px-3 py-1 rounded text-xs font-mono">
          ~5 min
        </div>
      </div>

      <div className="w-full max-w-4xl space-y-8">
        {/* Progress Tracker */}
        <div className="flex items-center justify-between relative px-8">
          <div className="absolute left-8 right-8 top-1/2 h-[1.5px] bg-primary/20 -translate-y-1/2 z-0"></div>
          <div className="absolute left-8 w-[20%] top-1/2 h-[1.5px] bg-primary -translate-y-1/2 z-0"></div>
          
          {[
            { num: 1, label: "Welcome", state: "done" },
            { num: 2, label: "Authorization", state: "active" },
            { num: 3, label: "Master Password", state: "pending" },
            { num: 4, label: "Honeypots", state: "pending" },
            { num: 5, label: "Enrichment", state: "pending" },
            { num: 6, label: "Alerts & Notifications", state: "pending" }
          ].map((step, i) => (
            <div key={i} className="relative z-10 flex flex-col items-center gap-2">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm border-2 ${
                step.state === 'done' ? 'bg-green-500 border-green-500 text-black shadow-[0_0_10px_rgba(34,197,94,0.4)]' :
                step.state === 'active' ? 'bg-primary border-primary text-black shadow-[0_0_15px_rgba(212,160,23,0.5)]' :
                'bg-[#100a04] border-primary/30 text-muted-foreground'
              }`}>
                {step.state === 'done' ? <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> : step.num}
              </div>
              <div className={`text-[10px] uppercase tracking-widest absolute -bottom-6 w-32 text-center -ml-12 ${
                step.state === 'active' ? 'text-primary font-bold' : 'text-muted-foreground'
              }`}>
                {step.label}
              </div>
            </div>
          ))}
        </div>

        {/* Current Step Panel */}
        <div className="hive-panel p-8 mt-12">
          <h2 className="text-xl font-bold text-foreground mb-2">Step 2 - Authorization & Intended Use</h2>
          <p className="text-muted-foreground mb-6">Meli collects live attack data, credentials, and potentially harmful payloads. You must authorize this software to run on your network.</p>
          
          <div className="bg-black/60 border border-primary/30 rounded p-4 h-48 overflow-y-auto mb-6 text-sm text-muted-foreground font-mono leading-relaxed custom-scrollbar">
            DISCLAIMER OF LIABILITY AND INTENDED USE
            <br/><br/>
            This software (Meli) is provided "as is", without warranty of any kind, express or implied. In no event shall the authors or copyright holders be liable for any claim, damages or other liability, whether in an action of contract, tort or otherwise, arising from, out of or in connection with the software or the use or other dealings in the software.
            <br/><br/>
            By proceeding, you acknowledge that running honeypots inherently involves attracting malicious traffic to your network. You agree that you are solely responsible for securing your own infrastructure and isolating the honeypot environment from production systems.
          </div>

          <label className="flex items-start gap-3 cursor-pointer group">
            <div className="mt-1 w-5 h-5 rounded border border-primary/50 bg-black/40 flex items-center justify-center group-hover:border-primary transition-colors">
              {/* Fake checkbox checked state for visual match */}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="text-primary"><polyline points="20 6 9 17 4 12"></polyline></svg>
            </div>
            <span className="text-foreground text-sm leading-relaxed">
              I understand and will use Meli only on systems and networks I am authorized to monitor. I accept full responsibility for any consequences of running this software.
            </span>
          </label>
        </div>

        <div className="flex items-center justify-between pt-4">
          <button className="text-muted-foreground hover:text-foreground px-4 py-2 text-sm font-bold tracking-widest uppercase transition-colors">
            ← Back
          </button>
          <a href="#" className="text-primary hover:text-primary/80 text-sm border-b border-primary/30 pb-0.5 transition-colors">
            Read full DISCLAIMER.md →
          </a>
          <button className="bg-primary text-primary-foreground font-bold px-8 py-3 rounded tracking-widest uppercase hover:bg-primary/90 transition-colors shadow-[0_0_15px_rgba(212,160,23,0.3)]">
            I Agree →
          </button>
        </div>
      </div>
    </div>
    </PageShell>
  );
}