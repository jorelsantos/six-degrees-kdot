"use client";

import { useState } from "react";
import { resolvePreview } from "@/lib/api";

/**
 * Spotify embed player (plan 004, U2) + lazy resolve-on-Play (plan 007, Path B).
 *
 * The iframe plays a 30s preview from a track id alone (no dead `preview_url`).
 * `allow="encrypted-media"` is MANDATORY — omitting it silently downgrades the
 * embed to no playback (documented Spotify gotcha).
 *
 * Two paths, both lazy (nothing fires until the user clicks Play):
 *  - `trackId` already known (resolved earlier) → mount the iframe on click.
 *  - `trackId` null → on click, hit /api/resolve-preview once; the API searches
 *    Spotify, persists the id, and returns it (or null). Plan 007 measured this
 *    lazy path at ~78% coverage on displayed songs vs ~15% for the best offline
 *    source, so it's the workhorse — not a batch pre-bake. Each song resolves at
 *    most once, ever (cached server-side); a no-match degrades to no player.
 */
export function SpotifyEmbed({
  trackId,
  songId,
  song,
}: {
  trackId: string | null;
  songId: number;
  song: string;
}) {
  const [resolvedId, setResolvedId] = useState<string | null>(trackId);
  const [status, setStatus] = useState<"idle" | "resolving" | "open" | "none">("idle");

  async function onPlay() {
    if (resolvedId) {
      setStatus("open");
      return;
    }
    setStatus("resolving");
    const id = await resolvePreview(songId);
    if (id) {
      setResolvedId(id);
      setStatus("open");
    } else {
      setStatus("none");
    }
  }

  if (status === "open" && resolvedId) {
    return (
      <div className="mt-2">
        <iframe
          title={`Spotify preview of ${song}`}
          src={`https://open.spotify.com/embed/track/${resolvedId}`}
          width="100%"
          height={152}
          loading="lazy"
          allow="encrypted-media"
          className="rounded-lg border-0"
        />
      </div>
    );
  }

  if (status === "none") {
    // Searched, no acceptable match — degrade to a quiet note, no broken link.
    return (
      <p className="mt-2 text-caption text-content-tertiary">Preview unavailable</p>
    );
  }

  const resolving = status === "resolving";
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={onPlay}
        disabled={resolving}
        aria-label={`Play a preview of ${song} on Spotify`}
        className="inline-flex items-center gap-2 rounded-pill bg-brand px-4 py-1.5 text-caption font-bold uppercase tracking-[0.08em] text-black transition-transform hover:scale-[1.03] active:scale-100 disabled:opacity-70"
      >
        <span aria-hidden className="ml-0.5">{resolving ? "…" : "▶"}</span>
        {resolving ? "Finding…" : "Play preview"}
      </button>
    </div>
  );
}
