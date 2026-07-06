"use client";

import { useRef, useState } from "react";
import { fetchPreview } from "@/lib/api";

/**
 * A 30s preview player that fetches its URL on FIRST play, never on mount
 * (KTD/U5) — a many-song connection page mounting would otherwise burst-hit
 * iTunes' rate limit and previews would silently vanish. Degrades to a
 * store-search link when no preview exists.
 */
export function AudioPreview({
  song,
  artists,
}: {
  song: string;
  artists: string[];
}) {
  const [state, setState] = useState<"idle" | "loading" | "ready" | "none">("idle");
  const [url, setUrl] = useState<string | null>(null);
  const [storeUrl, setStoreUrl] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  async function onPlay() {
    if (state === "ready" && audioRef.current) {
      audioRef.current.play();
      return;
    }
    if (state === "loading") return;
    setState("loading");
    const res = await fetchPreview(song, artists);
    setStoreUrl(res.store_url);
    if (res.preview_url) {
      setUrl(res.preview_url);
      setState("ready");
      // Play once the element has the src (next tick).
      requestAnimationFrame(() => audioRef.current?.play());
    } else {
      setState("none");
    }
  }

  const storeLabel = storeUrl
    ? "Listen on Apple Music"
    : "Search on Apple Music";
  const storeHref =
    storeUrl ??
    `https://music.apple.com/us/search?term=${encodeURIComponent(
      `${song} ${artists[0] ?? ""}`,
    )}`;

  return (
    <div className="mt-2 flex items-center gap-3">
      {state !== "none" && (
        <button
          type="button"
          onClick={onPlay}
          aria-label={`Play a preview of ${song}`}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand text-black transition-transform hover:scale-105"
        >
          {state === "loading" ? (
            <span className="text-caption">…</span>
          ) : (
            <span aria-hidden className="ml-0.5">▶</span>
          )}
        </button>
      )}
      {url && (
        <audio ref={audioRef} src={url} controls className="h-9 max-w-full">
          <track kind="captions" />
        </audio>
      )}
      <a
        href={storeHref}
        target="_blank"
        rel="noreferrer"
        className="text-caption text-brand hover:underline"
      >
        ▸ {storeLabel}
      </a>
    </div>
  );
}
