/**
 * PaperNoise
 * ---------------------------------------------------------------------------
 * A fixed overlay that adds a very subtle fractal-noise texture across the
 * viewport, giving the site a tactile "expensive paper" quality.
 *
 * The SVG is encoded as a data URI so there is no extra network request.
 * `mix-blend-multiply` bakes the grain into the background tint rather than
 * washing it grey, and `pointer-events-none` keeps it inert.
 */
export function PaperNoise() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[60] mix-blend-multiply opacity-[0.05]"
      style={{
        // baseFrequency 0.92 = finer grain (denser, smaller particles),
        // feels like printed paper rather than rough cardboard.
        backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.92' numOctaves='3' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.55 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>")`,
      }}
    />
  );
}
