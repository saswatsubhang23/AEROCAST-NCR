"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("inline-flex flex-wrap gap-1 rounded-lg border border-line bg-surface p-1", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "h-8 rounded-md px-3 text-sm text-muted transition-colors hover:text-fg data-[state=active]:bg-accent data-[state=active]:font-medium data-[state=active]:text-bg disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export const TabsContent = TabsPrimitive.Content;
