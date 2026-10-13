"use client";

import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Scrollable region that fades its top and bottom edge only while there is more to scroll (the idea of the free Skiper UI
 * "Scroll with fade effect", skiper87, on a Radix ScrollArea). The fade is a mask, so nothing is hidden from assistive technology.
 */
export function ScrollFade({ className, children }: { className?: string; children: React.ReactNode }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [edge, setEdge] = useState({ top: false, bottom: false });

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const update = () => setEdge({ top: el.scrollTop > 2, bottom: el.scrollTop + el.clientHeight < el.scrollHeight - 2 });
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      ro.disconnect();
    };
  }, []);

  const mask = `linear-gradient(to bottom, ${edge.top ? "transparent, #000 24px" : "#000, #000"}, ${edge.bottom ? "#000 calc(100% - 24px), transparent" : "#000, #000"})`;
  return (
    <ScrollAreaPrimitive.Root className={cn("relative overflow-hidden", className)}>
      <ScrollAreaPrimitive.Viewport ref={viewport} className="h-full w-full" style={{ maskImage: mask, WebkitMaskImage: mask }}>
        {children}
      </ScrollAreaPrimitive.Viewport>
      <ScrollAreaPrimitive.Scrollbar orientation="vertical" className="flex w-1.5 touch-none select-none p-px">
        <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-line" />
      </ScrollAreaPrimitive.Scrollbar>
    </ScrollAreaPrimitive.Root>
  );
}
