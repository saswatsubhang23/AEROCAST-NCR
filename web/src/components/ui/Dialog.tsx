"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { Button } from "./Button";

/** Modal dialog on Radix: focus trap, Escape, scroll lock, labelled title and restored focus on close. Same props as before. */
export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="tw-fade fixed inset-0 z-50 bg-black/60" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="tw-pop fixed left-1/2 top-1/2 z-50 max-h-[85dvh] w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-line bg-surface p-5 text-fg shadow-xl"
        >
          <div className="flex items-start justify-between gap-3">
            <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Close aria-label="Close dialog" className="rounded-md p-1 text-muted hover:text-fg">
              <X className="h-4 w-4" aria-hidden="true" />
            </DialogPrimitive.Close>
          </div>
          <div className="mt-3 text-sm">{children}</div>
          <div className="mt-5 flex justify-end">
            <DialogPrimitive.Close asChild>
              <Button>Close</Button>
            </DialogPrimitive.Close>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** Slide-in navigation panel for small screens, on the same primitive. */
export function Sheet({ open, onClose, label, children }: { open: boolean; onClose: () => void; label: string; children: React.ReactNode }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="tw-fade fixed inset-0 z-40 bg-black/60 lg:hidden" />
        <DialogPrimitive.Content aria-describedby={undefined} className="tw-slide fixed inset-y-0 left-0 z-50 w-64 border-r border-line bg-surface lg:hidden">
          <DialogPrimitive.Title className="sr-only">{label}</DialogPrimitive.Title>
          <DialogPrimitive.Close aria-label="Close navigation" className="absolute right-3 top-3.5 rounded-md p-1 text-muted hover:text-fg">
            <X className="h-4 w-4" aria-hidden="true" />
          </DialogPrimitive.Close>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
