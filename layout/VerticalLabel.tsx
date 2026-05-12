"use client";

import { cn } from "@/lib/cn";

interface VerticalLabelProps {
  children: React.ReactNode;
  side?: "left" | "right";
  className?: string;
}

/**
 * VerticalLabel
 * ---------------------------------------------------------------------------
 * Rotated 90-degree editorial overline. Examples:
 *   "01 / SOURCES"
 *   "VOL. 04 / 2026"
 *
 * Uses CSS `writing-mode: vertical-rl` (right-to-left vertical). The text
 * reads top-to-bottom on the right side of a container — a signature
 * magazine-spread detail.
 *
 * Hidden on small screens to avoid overlap.
 */
export function VerticalLabel({ children, side = "left", className }: VerticalLabelProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "hidden lg:inline-block",
        "text-[10px] uppercase tracking-[0.3em] text-muted-foreground",
        "select-none",
        className
      )}
      style={{
        writingMode: "vertical-rl",
        transform: side === "left" ? "rotate(180deg)" : undefined,
      }}
    >
      {children}
    </span>
  );
}
