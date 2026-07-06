"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchConnection, type Connection, type ConnectionResult } from "@/lib/api";
import { AudioPreview } from "./audio-preview";

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
  // Skeleton matches the final layout so the page assembles rather than pops.
  return (
    <div aria-busy="true" aria-label="Finding connection">
      <div className="rh-skeleton mx-auto h-20 w-full max-w-sm" />
      <div className="rh-skeleton mx-auto mt-5 h-14 w-64" />
      <div className="rh-skeleton mx-auto mt-4 h-40 w-full" />
      <div className="rh-skeleton mx-auto mt-4 h-14 w-64" />
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
        <p className="mt-1 text-content-secondary">Zero degrees of separation.</p>
      </div>
    );
  }

  const start = connection.path[0]?.name;
  const label = connection.degrees === 1 ? "Degree" : "Degrees";

  return (
    <div>
      {showNotice && start && (
        <p className="mb-4 text-center text-bodySm text-content-secondary">
          Showing results for{" "}
          <span className="font-bold text-brand">{start}</span>
        </p>
      )}

      {/* Degree header — compact, no emoji (carries today's decisions). */}
      <div className="rounded-lg border border-brand bg-gradient-to-br from-brand/15 to-transparent px-6 py-5 text-center">
        <span className="text-display font-black tracking-tight">{connection.degrees}</span>
        <span className="ml-2 align-middle text-bodySm text-content-secondary">
          {label} of separation
        </span>
      </div>

      {/* Path: artist card, then the Collaborated-On block, alternating. */}
      <div className="mt-6 space-y-4">
        {connection.path.map((artist, i) => (
          <div key={artist.id}>
            <ArtistCard name={artist.name} />
            {i < connection.connections.length && (
              <CollabSection edge={connection.connections[i]} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ArtistCard({ name }: { name: string }) {
  return (
    <div className="mx-auto max-w-sm rounded-lg border border-brand bg-surface-raised px-5 py-4 text-center shadow-[var(--shadow-card)]">
      <p className="text-headingSm font-black">{name}</p>
      <div className="mx-auto mt-1.5 h-0.5 w-8 rounded-full bg-brand" />
    </div>
  );
}

function CollabSection({
  edge,
}: {
  edge: Connection["connections"][number];
}) {
  const from = edge.from.name;
  const to = edge.to.name;
  const details = edge.song_details.length
    ? edge.song_details
    : edge.songs.map((s) => ({ name: s, collaborators: [] as string[] }));
  const shown = details.slice(0, 3);
  const more = details.length - shown.length;

  return (
    <div className="my-4">
      <div className="text-center">
        <span className="inline-block rounded-pill border border-brand bg-brand/10 px-4 py-1.5 text-caption font-bold uppercase tracking-[0.1em] text-brand">
          Collaborated On
        </span>
        <p className="mt-2 text-bodySm text-content-secondary">
          {from} <span className="text-content-tertiary">×</span> {to}
        </p>
      </div>

      <div className="mt-3 rounded-lg bg-surface-raised p-4 shadow-[var(--shadow-card)]">
        {shown.map((song, i) => {
          const endpoints = new Set([from.toLowerCase(), to.toLowerCase()]);
          const others = song.collaborators.filter((c) => !endpoints.has(c.toLowerCase()));
          return (
            <div
              key={song.name + i}
              className="border-b border-border-subtle py-3 last:border-b-0"
            >
              <div className="flex items-center gap-2">
                <span className="text-brand">♪</span>
                <span className="font-medium">{song.name}</span>
              </div>
              {others.length > 0 && (
                <p className="ml-6 mt-0.5 text-caption text-content-tertiary">
                  with {others.slice(0, 6).join(", ")}
                  {others.length > 6 ? "…" : ""}
                </p>
              )}
              <AudioPreview song={song.name} artists={[from, to]} />
            </div>
          );
        })}
        {more > 0 && (
          <p className="mt-3 text-center text-caption italic text-content-tertiary">
            +{more} more collaboration{more > 1 ? "s" : ""}
          </p>
        )}
      </div>
    </div>
  );
}
