"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchConnection, type Connection, type ConnectionResult } from "@/lib/api";
import { PreviewCard } from "./preview-player";

export function ConnectionView({
  artistId,
  showNotice,
}: {
  artistId: string;
  showNotice: boolean;
}) {
  const [result, setResult] = useState<ConnectionResult | null>(null);

  useEffect(() => {
    let live = true;
    setResult(null);
    fetchConnection(artistId)
      .then((r) => live && setResult(r))
      .catch(() => live && setResult({ status: "not_found" }));
    return () => {
      live = false;
    };
  }, [artistId]);

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <Link href="/" className="text-caption text-content-secondary hover:text-content-primary">
        ← New search
      </Link>

      <div className="mt-6">
        {result === null && <LoadingSkeleton />}
        {result?.status === "not_found" && <NotFound />}
        {result?.status === "no_path" && <NoPath />}
        {result?.status === "ok" && (
          <ConnectionResult connection={result.connection} showNotice={showNotice} />
        )}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div aria-busy="true" aria-label="Finding connection">
      <div className="rh-skeleton mx-auto h-16 w-72" />
      <div className="rh-skeleton mx-auto mt-5 h-10 w-full max-w-sm" />
      <div className="rh-skeleton mx-auto mt-6 h-14 w-56" />
      <div className="rh-skeleton mx-auto mt-3 h-20 w-full max-w-sm" />
    </div>
  );
}

function NotFound() {
  return (
    <Empty
      title="Not in our network yet"
      body="We couldn't find that artist. Try searching again with a different spelling."
    />
  );
}

function NoPath() {
  return (
    <Empty
      title="No connection found"
      body="This artist exists in our data but doesn't have a collaboration path to Kendrick Lamar."
    />
  );
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-8 text-center">
      <h1 className="text-headingSm font-bold">{title}</h1>
      <p className="mt-2 text-content-secondary">{body}</p>
      <Link
        href="/"
        className="mt-6 inline-block rounded-pill bg-brand px-6 py-3 font-bold uppercase tracking-[0.1em] text-black"
      >
        Search again
      </Link>
    </div>
  );
}

function ConnectionResult({
  connection,
  showNotice,
}: {
  connection: Connection;
  showNotice: boolean;
}) {
  if (connection.is_kendrick) {
    return (
      <div className="rounded-lg border border-brand bg-gradient-to-br from-brand/20 to-transparent p-8 text-center">
        <p className="text-headingSm font-bold text-brand">That&apos;s Kendrick Lamar himself.</p>
        <p className="mt-1 text-content-secondary">A (k)dot score of zero.</p>
      </div>
    );
  }

  const start = connection.path[0]?.name;
  const lastIndex = connection.path.length - 1;

  return (
    <div>
      {showNotice && start && (
        <p className="mb-3 text-center text-bodySm text-content-secondary">
          Showing results for <span className="font-bold text-brand">{start}</span>
        </p>
      )}

      {/* K.Dot score — the degree count, above the viz (plan 008 U5 copy). */}
      <div className="text-center">
        <p className="text-bodySm text-content-secondary">
          <span className="font-bold text-content-primary">{start}</span>&rsquo;s{" "}
          <span className="font-bold text-brand">(k)dot score</span> is
        </p>
        <p className="text-[2.5rem] font-black leading-none tracking-tight text-brand/90">
          {connection.degrees}
        </p>
      </div>

      {/* Six-degrees chain: artist → one preview card → arrow → next → Kendrick.
          The vertical chain is the sole path viz now (the top transit-line was
          removed in plan 010, R2 — it duplicated this). */}
      <div className="mt-8 flex flex-col items-center">
        {connection.path.map((artist, i) => (
          <div key={artist.id} className="flex w-full flex-col items-center">
            <ChainNode
              id={artist.id}
              name={artist.name}
              photoUrl={artist.photo_url ?? null}
              isBase={i === lastIndex}
            />
            {i < connection.connections.length && (
              <>
                <DownArrow />
                <PreviewCard
                  fromId={connection.connections[i].from.id}
                  toId={connection.connections[i].to.id}
                  fromName={connection.connections[i].from.name}
                  toName={connection.connections[i].to.name}
                />
                <DownArrow />
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ChainNode({
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
          ? "flex items-center gap-2.5 rounded-pill bg-brand/90 py-1.5 pl-1.5 pr-5 text-body font-bold text-black"
          : "flex items-center gap-2 rounded-pill border border-border-strong bg-surface-raised py-1.5 pl-1.5 pr-4 text-bodySm font-medium text-content-primary"
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
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const w = words[0] ?? "";
  return (w.slice(0, 2) || "?").toUpperCase();
}

// Deterministic muted background for the initials circle, hashed from the MBID
// so a given artist is always the same color (Q3). Dark/desaturated to sit
// under white text and not fight the brand green.
function avatarColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 42%, 32%)`;
}

// Artist photo (plan 010, R3). Shows the resolved photo, falling back to the
// initials circle both when there's no URL AND when a persisted URL fails to
// load at runtime (onError) — Commons/Deezer/TheAudioDB hotlinks can rot, and
// KTD3 requires we never render a broken image.
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
  const size = isBase ? "h-9 w-9" : "h-8 w-8";

  if (photoUrl && !broken) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- remote CDN photos
      // (Commons/TheAudioDB/Deezer) aren't in images.remotePatterns; plain <img>
      // mirrors the preview-player.tsx pattern and adds onError (which it lacks).
      <img
        src={photoUrl}
        alt=""
        onError={() => setBroken(true)}
        className={`${size} shrink-0 rounded-full object-cover shadow-[0_2px_6px_rgba(0,0,0,0.35)]`}
      />
    );
  }

  return (
    <div
      aria-hidden="true"
      style={{ background: avatarColor(id) }}
      className={`${size} flex shrink-0 items-center justify-center rounded-full text-caption font-bold text-white/90`}
    >
      {initials(name)}
    </div>
  );
}

function DownArrow() {
  return <div aria-hidden="true" className="my-1 h-4 w-[2px] rounded bg-brand/30" />;
}
