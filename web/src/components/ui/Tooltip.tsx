"use client";

import * as TooltipPrimitive from "@radix-ui/react-tooltip";

/**
 * Accessible tooltip on Radix. The structure follows the free Skiper UI "Custom tooltip" (skiper101): a bordered content box
 * with an arrow. It opens on hover and on keyboard focus, closes with Escape, is announced through aria-describedby, and is
 * portalled so it can never widen the page. Keeps the previous API (`text`, `align`).
 */
export function Tooltip({
  text,
  children,
  align = "center",
}: {
  text: string;
  children: React.ReactNode;
  align?: "center" | "end";
}) {
  return (
    <TooltipPrimitive.Provider delayDuration={150}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>
          <span className="inline-flex">{children}</span>
        </TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side="bottom"
            align={align === "end" ? "end" : "center"}
            sideOffset={6}
            collisionPadding={12}
            className="tw-pop z-50 max-w-64 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-xs font-normal text-fg shadow-lg"
          >
            {text}
            <TooltipPrimitive.Arrow className="fill-surface-2 stroke-line" width={12} height={6} />
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
