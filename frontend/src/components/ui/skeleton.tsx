import { cn } from "@/lib/utils";

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-testid="skeleton"
      className={cn(
        "animate-pulse rounded-md bg-foreground/10 dark:bg-foreground/[0.07]",
        className,
      )}
      {...props}
    />
  );
}
