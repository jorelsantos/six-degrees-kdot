"use client";

import { useState } from "react";

/**
 * Shared six-degrees chain rendering pieces (plan 2026-07-09-001, U5).
 *
 * Extracted out of connection-view.tsx so the Tier A static demo can render
 * an IDENTICAL chain from static JSON — the plan's own requirement that the
 * demo "hydrate through the same rendering path as the live app." Nothing
 * here talks to the network; every prop is data the caller already has.
 */

export function ChainNode({
  id,
  name,
  photoUrl,
  isBase,
}: {
  id: string;
  name: string;
  photoUrl: string | null;
  isBase: boolean;
}) {
  return (
    <div
      className={
        isBase
          ? "flex items-center gap-3.5 rounded-pill bg-brand/90 py-2 pl-2 pr-7 text-headingSm font-bold text-black"
          : "flex items-center gap-3 rounded-pill border border-border-strong bg-surface-raised py-2 pl-2 pr-6 text-body font-semibold text-content-primary"
      }
    >
      <ArtistAvatar id={id} name={name} photoUrl={photoUrl} isBase={isBase} />
      <span>{name}</span>
    </div>
  );
}

// Deterministic initials for the no-photo fallback: first letters of the first
// two words, or the first two chars of a single-word stage name ("Drake" → DR,
// "SZA" → SZ). Never empty — degrades to "?" for a blank name.
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const w = words[0] ?? "";
  return (w.slice(0, 2) || "?").toUpperCase();
}

// Deterministic muted background for the initials circle, hashed from the MBID
// so a given artist is always the same color (Q3). Dark/desaturated to sit
// under white text and not fight the brand green.
export function avatarColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 42%, 32%)`;
}

// Artist photo (plan 010, R3). Shows the resolved photo, falling back to the
// initials circle both when there's no URL AND when a persisted URL fails to
// load at runtime (onError) — Commons/Deezer/TheAudioDB hotlinks can rot, and
// KTD3 requires we never render a broken image.
//
// Larger avatars (plan 2026-07-09-002, U3): the earlier 32-36px circles were
// too small to read the face — the whole point of the photos. At 56-64px the
// photo is clearly visible, and centered `object-cover` (no upward bias) keeps
// the subject framed without wasting the circle. `object-position: 50% 40%`
// nudges slightly above dead-center so headshots (face in the upper half) sit
// right without the old object-top hack that clipped foreheads on wider crops.
function ArtistAvatar({
  id,
  name,
  photoUrl,
  isBase,
}: {
  id: string;
  name: string;
  photoUrl: string | null;
  isBase: boolean;
}) {
  const [broken, setBroken] = useState(false);
  const size = isBase ? "h-16 w-16" : "h-14 w-14";

  if (photoUrl && !broken) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- remote CDN photos
      // (Commons/TheAudioDB/Deezer) aren't in images.remotePatterns; plain <img>
      // adds the onError fallback that next/image would not.
      <img
        src={photoUrl}
        alt=""
        onError={() => setBroken(true)}
        style={{ objectPosition: "50% 40%" }}
        className={`${size} shrink-0 rounded-full object-cover shadow-[0_2px_8px_rgba(0,0,0,0.4)]`}
      />
    );
  }

  return (
    <div
      aria-hidden="true"
      style={{ background: avatarColor(id) }}
      className={`${size} flex shrink-0 items-center justify-center rounded-full ${isBase ? "text-xl" : "text-lg"} font-bold text-white/90`}
    >
      {initials(name)}
    </div>
  );
}

export function DownArrow() {
  return <div aria-hidden="true" className="my-1 h-4 w-[2px] rounded bg-brand/30" />;
}
