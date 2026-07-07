"use client";

import { useEffect, useState } from "react";
import { fetchEdgePreview, type EdgePreview } from "@/lib/api";

/**
 * Rich preview card for one hop of the six-degrees chain (plan 008 + 009).
 *
 * Resolves the edge via /api/edge-preview on mount — the API returns the first
 * song with a *playable* preview plus rich metadata (credited artists, album,
 * year, artwork, and a dominant album color), or an Apple Music fallback.
 * Because resolution happens before render, there are no dead Play buttons (R1).
 * The card mimics a Spotify card: a big cover, full details, and an
 * album-color-adaptive background (dominant color under a dark scrim for text
 * contrast) with a subtle shadow so it pops.
 */
const SOURCE_LABEL: Record<string, string> = {
  spotify: "Spotify",
  itunes: "Apple Music",
  deezer: "Deezer",
};

function metaLine(ep: EdgePreview): string {
  // "Album · 2022" — omit whichever parts are missing.
  return [ep.album, ep.year ? String(ep.year) : null].filter(Boolean).join(" · ");
}

function cardBackground(color: string | null): string | undefined {
  if (!color) return undefined;
  // Album hue under a dark scrim so white text stays legible for any color
  // (light or dark cover) — the Spotify-card trick.
  return `linear-gradient(180deg, rgba(0,0,0,0.30), rgba(0,0,0,0.58)), ${color}`;
}

export function PreviewCard({
  fromId,
  toId,
  fromName,
  toName,
}: {
  fromId: string;
  toId: string;
  fromName: string;
  toName: string;
}) {
  const [ep, setEp] = useState<EdgePreview | null>(null);

  useEffect(() => {
    let live = true;
    setEp(null);
    fetchEdgePreview(fromId, toId)
      .then((r) => live && setEp(r))
      .catch(
        () =>
          live &&
          setEp({
            song: null, source: null, audio_url: null, artwork_url: null,
            store_url: null, fallback_url: null, artists: [], album: null,
            year: null, dominant_color: null,
          }),
      );
    return () => {
      live = false;
    };
  }, [fromId, toId]);

  const artistLine = ep?.artists?.length ? ep.artists.join(", ") : `${fromName}, ${toName}`;

  return (
    <div className="mx-auto my-2 w-full max-w-md">
      {ep === null && <div className="rh-skeleton h-24 w-full rounded-xl" aria-label="Finding a preview" />}

      {ep && ep.audio_url && (
        <div
          className="rounded-xl p-3.5 shadow-[0_10px_30px_-8px_rgba(0,0,0,0.6)]"
          style={{ background: cardBackground(ep.dominant_color) }}
        >
          <div className="flex items-center gap-3.5">
            {ep.artwork_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={ep.artwork_url}
                alt=""
                width={72}
                height={72}
                className="h-[72px] w-[72px] shrink-0 rounded-md shadow-[0_4px_12px_rgba(0,0,0,0.45)]"
              />
            ) : (
              <div className="flex h-[72px] w-[72px] shrink-0 items-center justify-center rounded-md bg-white/10 text-2xl text-white/80">
                ♪
              </div>
            )}
            <div className="min-w-0 flex-1 text-white">
              <p className="truncate text-body font-bold leading-tight">{ep.song}</p>
              <p className="truncate text-bodySm text-white/85">{artistLine}</p>
              {metaLine(ep) && (
                <p className="truncate text-caption text-white/65">{metaLine(ep)}</p>
              )}
              <p className="mt-0.5 text-caption text-white/50">
                {SOURCE_LABEL[ep.source ?? ""] ?? ep.source}
              </p>
            </div>
          </div>
          <audio src={ep.audio_url} controls className="mt-2.5 h-9 w-full">
            <track kind="captions" />
          </audio>
        </div>
      )}

      {ep && !ep.audio_url && (
        <div className="rounded-xl border border-border-subtle bg-surface-raised p-3.5 shadow-[var(--shadow-card)]">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-brand/15 text-brand">♪</div>
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{ep.song ?? "This collaboration"}</p>
              <p className="truncate text-caption text-content-tertiary">{artistLine}</p>
            </div>
            {ep.fallback_url ? (
              <a
                href={ep.fallback_url}
                target="_blank"
                rel="noreferrer"
                className="shrink-0 text-caption text-brand hover:underline"
              >
                Search on Apple Music ▸
              </a>
            ) : (
              <span className="shrink-0 text-caption text-content-tertiary">Preview unavailable</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
