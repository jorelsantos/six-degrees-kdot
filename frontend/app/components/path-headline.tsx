import type { ArtistRef } from "@/lib/api";

/**
 * Transit-line node viz (plan 2026-07-06-004 U4; enhanced in plan 008 U5).
 * Stations are artist chips threaded left→right, with **Kendrick anchored as the
 * base node**: larger and solid brand-green, while the searched artist and any
 * intermediates are smaller outline pills. The connectors are directional
 * arrowheads that **flow into** the next station, so the whole line visibly
 * converges on Kendrick — no crown/iconography, the weight + direction do it.
 *
 * Long chains / small screens: scrolls horizontally (chips never wrap) so a
 * 3-degree path stays legible at 375px.
 */
export function PathHeadline({ path }: { path: ArtistRef[] }) {
  if (path.length < 2) return null;
  const lastIndex = path.length - 1;

  return (
    <nav aria-label="Connection path" className="overflow-x-auto pb-2 text-center">
      <ol className="inline-flex items-center gap-0 align-middle">
        {path.map((artist, i) => {
          const isBase = i === lastIndex; // Kendrick — the anchor
          return (
            <li key={artist.id} className="flex items-center">
              {i > 0 && (
                // Connector flows INTO the next station (arrowhead points right,
                // toward the base). Thicker/brighter on the final hop into Kendrick.
                <span aria-hidden="true" className="flex shrink-0 items-center">
                  <span className={`h-[3px] bg-brand ${isBase ? "w-6 sm:w-9" : "w-5 sm:w-8"}`} />
                  <span
                    className={`-ml-[2px] border-y-[5px] border-l-[7px] border-y-transparent border-l-brand ${
                      isBase ? "border-y-[6px] border-l-[9px]" : ""
                    }`}
                  />
                </span>
              )}
              <span
                className={
                  isBase
                    ? "flex items-center gap-2 whitespace-nowrap rounded-pill bg-brand px-4 py-2 text-body font-black text-black shadow-[0_0_0_3px_rgba(30,215,96,0.25)]"
                    : "flex items-center gap-2 whitespace-nowrap rounded-pill border border-border-strong bg-surface-raised px-3 py-1.5 text-bodySm font-bold text-content-primary"
                }
              >
                <span
                  aria-hidden="true"
                  className={`shrink-0 rounded-full ${isBase ? "h-2.5 w-2.5 bg-black" : "h-2 w-2 bg-brand"}`}
                />
                {artist.name}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
