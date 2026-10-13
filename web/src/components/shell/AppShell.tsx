"use client";

import { MotionConfig } from "framer-motion";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { HealthProvider } from "@/lib/health";
import { LocationProvider } from "@/lib/location";
import { WindowProvider } from "@/lib/window";
import { WIDE_PAGES } from "@/lib/nav";
import { SectionTabs } from "./SectionTabs";
import { WeatherProvider } from "@/lib/weather/context";
import { NotificationProvider } from "@/components/ui/Notifications";
import { Sheet } from "@/components/ui/Dialog";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const wide = WIDE_PAGES.some((p) => pathname.startsWith(p));

  return (
    <MotionConfig reducedMotion="user">
    <NotificationProvider>
      <HealthProvider>
        <LocationProvider>
          <WindowProvider>
          <WeatherProvider>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-bg"
          >
            Skip to content
          </a>
          <div className="flex min-h-dvh">
            <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 border-r border-line bg-surface lg:block">
              <Sidebar />
            </aside>

            <Sheet open={open} onClose={() => setOpen(false)} label="Navigation">
              <Sidebar onNavigate={() => setOpen(false)} />
            </Sheet>

            <div className="flex min-w-0 flex-1 flex-col">
              <header className="sticky top-0 z-20">
                <TopBar onMenu={() => setOpen(true)} menuOpen={open} />
              </header>
              <main id="main" className={`mx-auto w-full flex-1 px-4 py-6 lg:px-8 ${wide ? "max-w-[1560px]" : "max-w-6xl"}`}>
                <SectionTabs />
                {children}
              </main>
            </div>
          </div>
          </WeatherProvider>
          </WindowProvider>
        </LocationProvider>
      </HealthProvider>
    </NotificationProvider>
    </MotionConfig>
  );
}
