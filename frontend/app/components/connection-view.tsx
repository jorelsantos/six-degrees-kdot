"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchConnection, type Connection, type ConnectionResult } from "@/lib/api";
import { PathHeadline } from "./path-headline";
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

      {/* Node viz — Kendrick anchored as the base. */}
      <div className="mt-4">
        <PathHeadline path={connection.path} />
      </div>

      {/* Six-degrees chain: artist → one preview card → arrow → next → Kendrick. */}
      <div className="mt-6 flex flex-col items-center">
        {connection.path.map((artist, i) => (
          <div key={artist.id} className="flex w-full flex-col items-center">
            <ChainNode name={artist.name} isBase={i === lastIndex} />
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

function ChainNode({ name, isBase }: { name: string; isBase: boolean }) {
  return (
    <div
      className={
        isBase
          ? "rounded-pill bg-brand/90 px-6 py-2.5 text-center text-body font-bold text-black"
          : "rounded-pill border border-border-strong bg-surface-raised px-5 py-2 text-center text-bodySm font-medium text-content-primary"
      }
    >
      {name}
    </div>
  );
}

function DownArrow() {
  return <div aria-hidden="true" className="my-1 h-4 w-[2px] rounded bg-brand/30" />;
}
