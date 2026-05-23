import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/not-found";

import MainLayout from "@/components/layout/main-layout";
import Dashboard from "@/pages/dashboard";
import LiveFeed from "@/pages/live-feed";
import Attackers from "@/pages/attackers";
import Credentials from "@/pages/credentials";
import Commands from "@/pages/commands";
import Payloads from "@/pages/payloads";
import Services from "@/pages/services";
import Sessions from "@/pages/sessions";
import Alerts from "@/pages/alerts";
import Reports from "@/pages/reports";
import Botnets from "@/pages/botnets";
import IpReputation from "@/pages/ip-reputation";
import SetupWizard from "@/pages/setup-wizard";

import { MapPage, AtriumPage, TimelinePage, FindingsPage, EnrichmentPage, SettingsPage } from "@/pages/placeholders";

const queryClient = new QueryClient();

function Router() {
  return (
    <MainLayout>
      <Switch>
        <Route path="/" component={Dashboard} />
        <Route path="/live-feed" component={LiveFeed} />
        <Route path="/map" component={MapPage} />
        <Route path="/attackers" component={Attackers} />
        <Route path="/credentials" component={Credentials} />
        <Route path="/commands" component={Commands} />
        <Route path="/payloads" component={Payloads} />
        <Route path="/services" component={Services} />
        <Route path="/timeline" component={TimelinePage} />
        <Route path="/ip-reputation" component={IpReputation} />
        <Route path="/botnets" component={Botnets} />
        <Route path="/alerts" component={Alerts} />
        <Route path="/reports" component={Reports} />
        <Route path="/atrium" component={AtriumPage} />
        <Route path="/sessions" component={Sessions} />
        <Route path="/findings" component={FindingsPage} />
        <Route path="/enrichment" component={EnrichmentPage} />
        <Route path="/settings" component={SettingsPage} />
        <Route path="/setup-wizard" component={SetupWizard} />
        <Route component={NotFound} />
      </Switch>
    </MainLayout>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
          <Router />
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;