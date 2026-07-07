"use client";

import { useEffect, useState } from "react";
import { fetchEdgePreview, type EdgePreview } from "@/lib/api";

/**
 * Compact preview card for one hop of the six-degrees chain (plan 008, U4).
 *
 * On mount it resolves the edge via /api/edge-preview — the API returns the
 * first song on the edge that has a *playable* preview (Spotify-scrape → iTunes
 * → Deezer) plus a directly-playable audio URL, or an Apple Music search
 * fallback. Because resolution happens before the player renders, there are no
 * dead Play buttons (R1): we show a real inline <audio> player, or the Apple
 * link — never an empty button.
 */
const SOURCE_LABEL: Record<string, string> = {
  spotify: "Spotify",
  itunes: "Apple Music",
  deezer: "Deezer",
};

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
      .catch(() => live && setEp({ song: null, source: null, audio_url: null, artwork_url: null, store_url: null, fallback_url: null }));
    return () => {
      live = false;
    };
  }, [fromId, toId]);

  return (
    <div className="mx-auto my-2 w-full max-w-sm">
      <p className="mb-1 text-center text-caption text-content-tertiary">
        {fromName} <span className="text-content-tertiary/60">×</span> {toName}
      </p>
      <div className="rounded-lg border border-border-subtle bg-surface-raised p-3 shadow-[var(--shadow-card)]">
        {ep === null && <div className="rh-skeleton h-14 w-full" aria-label="Finding a preview" />}

        {ep && ep.audio_url && (
          <div className="flex items-center gap-3">
            {ep.artwork_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={ep.artwork_url} alt="" width={44} height={44} className="shrink-0 rounded" />
            ) : (
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded bg-brand/15 text-brand">♪</div>
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate font-medium">{ep.song}</span>
                <span className="shrink-0 text-caption text-content-tertiary">
                  {SOURCE_LABEL[ep.source ?? ""] ?? ep.source}
                </span>
              </div>
              {/* Native player: uniform across sources, compact, controllable. */}
              <audio src={ep.audio_url} controls className="mt-1.5 h-8 w-full">
                <track kind="captions" />
              </audio>
            </div>
          </div>
        )}

        {ep && !ep.audio_url && (
          <div className="flex items-center gap-2 text-bodySm">
            <span className="text-brand">♪</span>
            <span className="font-medium">{ep.song ?? "This collaboration"}</span>
            {ep.fallback_url ? (
              <a
                href={ep.fallback_url}
                target="_blank"
                rel="noreferrer"
                className="ml-auto shrink-0 text-caption text-brand hover:underline"
              >
                Search on Apple Music ▸
              </a>
            ) : (
              <span className="ml-auto shrink-0 text-caption text-content-tertiary">Preview unavailable</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
