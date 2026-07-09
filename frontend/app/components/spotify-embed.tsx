"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Official Spotify embed iframe (plan 2026-07-09-001, KTD3).
 *
 * The public app's ONLY preview mechanism: the visitor's browser talks to
 * Spotify directly (open.spotify.com/embed/track/{id}), so the server never
 * fetches or scrapes any audio. Verified working unauthenticated, and this is
 * exactly the design sixdegreesofkanyewest.com has run since 2016.
 *
 * Lazy-loaded via IntersectionObserver (not a tap-to-load button — committed
 * choice, doc review D5 P3): the iframe only mounts once scrolled into view,
 * keeping a multi-hop chain page light without an extra tap for every visitor.
 *
 * Runtime-failure fallback (doc review D3 P2): an <iframe> has no onError the
 * way <img> does, so a valid track id whose embed is blocked in the visitor's
 * browser (sporadic 2025 reports) would otherwise render a silent blank box.
 * A short load-timeout swaps to the same no-player card used for unresolved
 * ids, so the failure mode is identical either way.
 */
const LOAD_TIMEOUT_MS = 4000;

export function SpotifyEmbed({
  trackId,
  songName,
  artistLine,
}: {
  trackId: string | null;
  songName: string | null;
  artistLine: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [inView, setInView] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (!trackId || inView) return;
    const el = containerRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [trackId, inView]);

  useEffect(() => {
    if (!inView || loaded) return;
    const handle = setTimeout(() => setTimedOut(true), LOAD_TIMEOUT_MS);
    return () => clearTimeout(handle);
  }, [inView, loaded]);

  if (!trackId || timedOut) {
    return <NoPlayerCard songName={songName} artistLine={artistLine} />;
  }

  return (
    <div ref={containerRef} className="mx-auto my-2 w-full max-w-md">
      {inView ? (
        <iframe
          title={songName ? `Spotify: ${songName}` : "Spotify preview"}
          src={`https://open.spotify.com/embed/track/${trackId}?utm_source=generator`}
          width="100%"
          height="152"
          style={{ borderRadius: 12 }}
          frameBorder="0"
          allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
          loading="lazy"
          onLoad={() => setLoaded(true)}
        />
      ) : (
        <div className="rh-skeleton h-[152px] w-full rounded-xl" aria-label="Loading preview" />
      )}
    </div>
  );
}

function NoPlayerCard({
  songName,
  artistLine,
}: {
  songName: string | null;
  artistLine: string;
}) {
  return (
    <div className="mx-auto my-2 w-full max-w-md">
      <div className="rounded-xl border border-border-subtle bg-surface-raised p-3.5 shadow-[var(--shadow-card)]">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-brand/15 text-brand">
            ♪
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{songName ?? "This collaboration"}</p>
            <p className="truncate text-caption text-content-tertiary">{artistLine}</p>
          </div>
          <span className="shrink-0 text-caption text-content-tertiary">Preview unavailable</span>
        </div>
      </div>
    </div>
  );
}
