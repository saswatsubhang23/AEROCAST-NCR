import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-accent text-bg hover:bg-accent/85",
        secondary: "border border-line bg-surface-2 text-fg hover:border-accent/60",
        ghost: "text-muted hover:bg-surface-2 hover:text-fg",
        danger: "border border-danger/50 text-danger hover:bg-danger/10",
      },
      size: { md: "h-9 px-3.5", sm: "h-8 px-2.5 text-xs", icon: "h-9 w-9" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ className, variant, size, asChild, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
