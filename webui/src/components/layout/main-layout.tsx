import { ReactNode } from "react";
import Sidebar from "./sidebar";

export default function MainLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar />
      <main className="flex-1 ml-[220px] min-h-screen flex flex-col">
        {children}
      </main>
    </div>
  );
}
