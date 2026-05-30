import Link from "next/link";

/**
 * Wordmark used in both the sidebar (when expanded) and the landing/auth pages.
 * The icon is a stylized "neural node" — three orbiting dots around a centre.
 */
export function BrandMark({
  size = "md",
  href = "/",
  className = "",
}: {
  size?: "sm" | "md" | "lg";
  href?: string;
  className?: string;
}) {
  const dim = size === "lg" ? "size-9" : size === "sm" ? "size-6" : "size-8";
  const textSz = size === "lg" ? "text-lg" : size === "sm" ? "text-xs" : "text-sm";

  return (
    <Link
      href={href}
      className={`inline-flex items-center gap-2 ${className}`}
      data-testid="brand-mark"
    >
      <span
        aria-hidden="true"
        className={`${dim} grid place-items-center rounded-lg bg-gradient-brand glow-brand text-brand-foreground`}
      >
        <svg
          viewBox="0 0 24 24"
          className="size-[60%]"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
          <circle cx="5" cy="6" r="1.5" />
          <circle cx="19" cy="7" r="1.5" />
          <circle cx="17.5" cy="18.5" r="1.5" />
          <path d="M6.3 7 11 10.8" />
          <path d="M17.7 8 13 10.8" />
          <path d="M16.3 17.2 12.5 13.7" />
        </svg>
      </span>
      <span className={`${textSz} font-semibold tracking-tight`}>
        <span className="text-gradient-brand">MMAP</span>
      </span>
    </Link>
  );
}
