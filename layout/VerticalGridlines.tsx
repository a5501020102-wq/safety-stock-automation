/**
 * VerticalGridlines
 * ---------------------------------------------------------------------------
 * Fixed 1px vertical lines that span the full viewport height, aligned with
 * the 12-column layout edges and middle thirds. Creates an architectural
 * editorial feel — the page looks like it was "set" on a printing grid.
 *
 * Hidden on mobile where they'd feel cluttered; only visible from md+.
 * Pointer-events disabled so they never block interaction.
 *
 * Opacity intentionally low (12%) so they're a whisper, not a shout.
 */
export function VerticalGridlines() {
  // Four lines positioned at 1/6, 2/6, 4/6, 5/6 approximate the 12-column
  // outer edges plus the two middle-third dividers.
  const positions = ["16.666%", "33.333%", "66.666%", "83.333%"];

  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-[55] hidden md:block">
      {positions.map((left) => (
        <div key={left} className="absolute top-0 h-full w-px bg-foreground/10" style={{ left }} />
      ))}
    </div>
  );
}
