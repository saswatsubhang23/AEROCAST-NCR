import Link from "next/link";
import { EmptyState, btnSecondary } from "@/components/ui/states";

export default function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      message="This address does not match any section of AEROCAST NCR."
      action={
        <Link href="/" className={btnSecondary}>
          Go to Overview
        </Link>
      }
    />
  );
}
