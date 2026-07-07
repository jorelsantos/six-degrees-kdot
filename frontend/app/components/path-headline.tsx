import type { ArtistRef } from "@/lib/api";

/**
 * Path headline / transit-line (plan 2026-07-06-004, U4 / KTD4). Leads the
 * connection page with the full chain — "Larry June → Dom Kennedy → Kendrick
 * Lamar" — rendered as a linear metro transit-line (echooo.me-inspired):
 * stations are artist chips, threaded on a brand-green line, with Kendrick as
 * the destination. A linear path suits a single shortest path far better than a
 * node-graph hairball; the card + "Collaborated On" detail stays below as the
 * expandable substance.
 *
 * Long chains / small screens: the line scrolls horizontally (the chips never
 * wrap) so a 3-degree path stays legible at 375px.
 */
export function PathHeadline({ path }: { path: ArtistRef[] }) {
  if (path.length < 2) return null;
  const lastIndex = path.length - 1;

  return (
    <nav
      aria-label="Connection path"
      className="mb-6 overflow-x-auto pb-2 text-center"
    >
      <ol className="inline-flex items-center gap-0 align-middle">
        {path.map((artist, i) => {
          const isDestination = i === lastIndex;
          return (
            <li key={artist.id} className="flex items-center">
              {i > 0 && (
                <span
                  aria-hidden="true"
                  className="h-[3px] w-6 shrink-0 bg-brand sm:w-10"
                />
              )}
              <span
                className={`flex items-center gap-2 whitespace-nowrap rounded-pill border px-3 py-1.5 text-bodySm font-bold ${
                  isDestination
                    ? "border-brand bg-brand text-black"
                    : "border-border-strong bg-surface-raised text-content-primary"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    isDestination ? "bg-black" : "bg-brand"
                  }`}
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
