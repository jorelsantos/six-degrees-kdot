"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChainNode, DownArrow } from "@/app/components/chain-display";
import { SpotifyEmbed } from "@/app/components/spotify-embed";

/**
 * Tier A demo chain view (plan 2026-07-09-001, U5).
 *
 * Renders through the SAME chain components as the live app's
 * connection-view.tsx (ChainNode, DownArrow, SpotifyEmbed) — the plan's own
 * requirement that the demo "hydrate through the same rendering path as the
 * live app" — hydrated from a static JSON file instead of a live API call.
 * Unlike the live view, every hop's track id is already baked into the JSON,
 * so there's no lazy resolve-on-view step here.
 */
interface DemoPathNode {
  id: string;
  name: string;
  photo_url: string | null;
}

interface DemoHop {
  song_name: string | null;
  track_id: string | null;
  artists: string[];
}

interface DemoChain {
  degrees: number;
  path: DemoPathNode[];
  hops: DemoHop[];
}

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ok"; chain: DemoChain };

export function DemoChainView({ artistId }: { artistId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    fetch(`/demo/${encodeURIComponent(artistId)}.json`)
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((chain: DemoChain) => live && setState({ status: "ok", chain }))
      .catch(() => live && setState({ status: "error" }));
    return () => {
      live = false;
    };
  }, [artistId]);

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <Link href="/demo" className="text-caption text-content-secondary hover:text-content-primary">
        ← Back to demo
      </Link>

      <div className="mt-6">
        {state.status === "loading" && <LoadingSkeleton />}
        {state.status === "error" && <MissingChain />}
        {state.status === "ok" && <Chain chain={state.chain} />}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading chain">
      <div className="rh-skeleton mx-auto h-16 w-72" />
      <div className="rh-skeleton mx-auto mt-5 h-10 w-full max-w-sm" />
      <div className="rh-skeleton mx-auto mt-6 h-14 w-56" />
      <div className="rh-skeleton mx-auto mt-3 h-20 w-full max-w-sm" />
    </div>
  );
}

function MissingChain() {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-raised p-8 text-center">
      <h1 className="text-headingSm font-bold">Couldn&apos;t load this chain</h1>
      <p className="mt-2 text-content-secondary">
        This artist may not be part of the demo set. Pick a face from the demo grid instead.
      </p>
      <Link
        href="/demo"
        className="mt-6 inline-block rounded-pill bg-brand px-6 py-3 font-bold uppercase tracking-[0.1em] text-black"
      >
        Back to demo
      </Link>
    </div>
  );
}

function Chain({ chain }: { chain: DemoChain }) {
  const start = chain.path[0]?.name;
  const lastIndex = chain.path.length - 1;

  return (
    <div>
      <div className="text-center">
        <p className="text-bodySm text-content-secondary">
          <span className="font-bold text-content-primary">{start}</span>&rsquo;s{" "}
          <span className="font-bold text-brand">(k)dot score</span> is
        </p>
        <p className="text-[2.5rem] font-black leading-none tracking-tight text-brand/90">
          {chain.degrees}
        </p>
      </div>

      <div className="mt-8 flex flex-col items-center">
        {chain.path.map((artist, i) => (
          <div key={artist.id} className="flex w-full flex-col items-center">
            <ChainNode
              id={artist.id}
              name={artist.name}
              photoUrl={artist.photo_url}
              isBase={i === lastIndex}
            />
            {i < chain.hops.length && (
              <>
                <DownArrow />
                <SpotifyEmbed
                  trackId={chain.hops[i].track_id}
                  songName={chain.hops[i].song_name}
                  artistLine={chain.hops[i].artists.join(", ") || `${artist.name}, ${chain.path[i + 1]?.name ?? ""}`}
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
