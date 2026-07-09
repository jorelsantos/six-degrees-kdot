"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchConnection, resolveTrack, type Connection, type ConnectionResult } from "@/lib/api";
import { ChainNode, DownArrow } from "./chain-display";
import { SpotifyEmbed } from "./spotify-embed";

export function ConnectionView({
  artistId,
  showNotice,
}: {
  artistId: string;
  showNotice: boolean;
}) {
  const [result, setResult] = useState<ConnectionResult | null>(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let live = true;
    setResult(null);
    fetchConnection(artistId).then((r) => live && setResult(r));
    return () => {
      live = false;
    };
  }, [artistId, retryCount]);

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <Link href="/" className="text-caption text-content-secondary hover:text-content-primary">
        ← New search
      </Link>

      <div className="mt-6">
        {result === null && <LoadingSkeleton />}
        {result?.status === "not_found" && <NotFound />}
        {result?.status === "no_path" && <NoPath />}
        {result?.status === "error" && <Busy onRetry={() => setRetryCount((c) => c + 1)} />}
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

// R7: a busy/error backend must never look like "artist not found" — this is
// what a rate-limited or momentarily-down Worker actually shows, with a real
// retry action (not just descriptive copy).
function Busy({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-8 text-center">
      <h1 className="text-headingSm font-bold">We&apos;re busy</h1>
      <p className="mt-2 text-content-secondary">
        Something went wrong on our end. This usually clears up fast.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-6 inline-block rounded-pill bg-brand px-6 py-3 font-bold uppercase tracking-[0.1em] text-black"
      >
        Try again
      </button>
    </div>
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

      {/* Six-degrees chain: artist → Spotify embed → arrow → next → Kendrick
          (plan 2026-07-09-001, U8 — the official embed replaces the scraped
          preview waterfall; same rendering path as the Tier A demo). */}
      <div className="mt-8 flex flex-col items-center">
        {connection.path.map((artist, i) => (
          <div key={artist.id} className="flex w-full flex-col items-center">
            <ChainNode
              id={artist.id}
              name={artist.name}
              photoUrl={artist.photo_url}
              isBase={i === lastIndex}
            />
            {i < connection.hops.length && (
              <>
                <DownArrow />
                <ResolvingSpotifyEmbed
                  artistId={artist.id}
                  trackId={connection.hops[i].track_id}
                  songName={connection.hops[i].song_name}
                  artistLine={
                    connection.hops[i].artists.join(", ") ||
                    `${artist.name}, ${connection.path[i + 1]?.name ?? ""}`
                  }
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

// Wires SpotifyEmbed to the lazy resolve-on-view flow (KTD5): a hop whose
// via-song has never been checked (track_id null) triggers one resolve-track
// call on mount; a hop already resolved — real id OR confirmed no-match —
// renders straight through with zero network cost.
function ResolvingSpotifyEmbed({
  artistId,
  trackId,
  songName,
  artistLine,
}: {
  artistId: string;
  trackId: string | null;
  songName: string | null;
  artistLine: string;
}) {
  const [resolved, setResolved] = useState<string | null>(trackId);
  const [checked, setChecked] = useState(trackId !== null);

  useEffect(() => {
    if (checked) return;
    let live = true;
    resolveTrack(artistId).then((id) => {
      if (live) {
        setResolved(id);
        setChecked(true);
      }
    });
    return () => {
      live = false;
    };
  }, [artistId, checked]);

  if (!checked) {
    return <div className="rh-skeleton mx-auto my-2 h-[152px] w-full max-w-md rounded-xl" aria-label="Finding a preview" />;
  }

  return <SpotifyEmbed trackId={resolved} songName={songName} artistLine={artistLine} />;
}
