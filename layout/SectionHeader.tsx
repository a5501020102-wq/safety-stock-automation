import { cn } from "@/lib/cn";

interface SectionHeaderProps {
  /** Roman or arabic numeral, e.g. "01" or "I" */
  numeral: string;
  /** Short uppercase category, e.g. "SOURCES" */
  overline: string;
  /** The spread's headline — plain serif text */
  title: React.ReactNode;
  /** Optional italic word that gets the accent color inside the title */
  italicAccent?: string;
  /** Optional deck (subtitle / dek in magazine parlance) */
  deck?: React.ReactNode;
  /** Optional right-aligned meta block (dates, edit notes) */
  meta?: React.ReactNode;
  className?: string;
}

/**
 * SectionHeader
 * ---------------------------------------------------------------------------
 * Editorial-style section opener. Produces the classic magazine "chapter"
 * spread:
 *
 *   ─────────────   01  /  SOURCES              PRINTED · MMXXVI · APR
 *
 *     Materials.
 *     Selected.
 *
 *     Three inputs set the foundation for every analysis that follows.
 *
 * Composition follows the SPEC:
 *  - Thin top rule spans the content width
 *  - Overline uses all-caps tracking-[0.3em]
 *  - Headline is Playfair Display, dramatic size, leading-[0.9]
 *  - Optional italic accent word is rendered in the gold accent color
 *  - Deck uses Inter, muted color, generous line-height
 *
 * Intentionally asymmetric: the number lives on the LEFT rule, the meta
 * (if provided) floats to the far right. Desktop only; stacks on mobile.
 */
export function SectionHeader({ numeral, overline, title, italicAccent, deck, meta, className }: SectionHeaderProps) {
  return (
    <header className={cn("w-full", className)}>
      {/* Top rule + metadata row */}
      <div className="flex items-center justify-between gap-6 border-t border-foreground/25 pt-6">
        <div className="flex items-center gap-6">
          <span className="font-sans text-[10px] uppercase tracking-[0.3em] text-foreground">{numeral}</span>
          <span className="h-px w-6 md:w-10 bg-foreground/40" />
          <span className="font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">{overline}</span>
        </div>
        {meta ? (
          <div className="hidden md:block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
            {meta}
          </div>
        ) : null}
      </div>

      {/* Headline */}
      <h2 className="mt-14 md:mt-20 font-serif leading-[0.9] tracking-tight text-foreground text-4xl sm:text-5xl md:text-7xl">
        {title}
        {italicAccent ? (
          <>
            {" "}
            <em className="italic text-accent">{italicAccent}</em>
          </>
        ) : null}
      </h2>

      {/* Deck / subtitle */}
      {deck ? (
        <p className="mt-8 max-w-xl font-sans text-base md:text-lg leading-relaxed text-muted-foreground">{deck}</p>
      ) : null}
    </header>
  );
}
