"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { avatarColor, initials } from "@/app/components/chain-display";

/**
 * Showcase grid (plan 2026-07-09-001, U5 — doc review D1, P1).
 *
 * The Tier A demo's primary entry surface. Fetches the static index once
 * (no live API, no search backend — a client-side name filter over 16
 * known entries is plenty), renders a responsive card grid, and filters
 * in place. A miss shows demo-specific copy (doc review D2, P2): this is
 * NOT the live app's "not in our network" claim — most artists really are
 * in the network, just not in this small curated set.
 */
interface ShowcaseEntry {
  id: string;
  name: string;
  photo_url: string | null;
  degrees: number;
}

export function ShowcaseGrid() {
  const [entries, setEntries] = useState<ShowcaseEntry[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let live = true;
    fetch("/demo/index.json")
      .then((r) => r.json())
      .then((data: ShowcaseEntry[]) => live && setEntries(data))
      .catch(() => live && setEntries([]));
    return () => {
      live = false;
    };
  }, []);

  if (entries === null) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading showcase"
        className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4"
      >
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="rh-skeleton h-40 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  const filtered = query.trim()
    ? entries.filter((e) => e.name.toLowerCase().includes(query.trim().toLowerCase()))
    : entries;

  return (
    <div>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter this demo's artists"
        className="w-full rounded-pill border border-border-subtle bg-surface-raised px-5 py-3 text-bodySm text-content-primary placeholder:text-content-tertiary focus:border-brand focus:outline-none"
      />

      {filtered.length === 0 ? (
        <div className="mt-8 rounded-lg border border-border-subtle bg-surface-raised p-8 text-center">
          <h2 className="text-headingSm font-bold">Not in this demo</h2>
          <p className="mt-2 text-content-secondary">
            This is a small curated preview, not the full 119k-artist network — the
            full app almost certainly has this artist. Pick one of the faces below instead.
          </p>
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
          {filtered.map((entry) => (
            <ShowcaseCard key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}

function ShowcaseCard({ entry }: { entry: ShowcaseEntry }) {
  const [broken, setBroken] = useState(false);
  const hasPhoto = entry.photo_url && !broken;

  return (
    <Link
      href={`/demo/${encodeURIComponent(entry.id)}`}
      className="group flex flex-col items-center rounded-lg border border-border-subtle bg-surface-raised p-4 text-center transition-colors hover:border-brand/60 hover:bg-surface-raised-hover"
    >
      {hasPhoto ? (
        // eslint-disable-next-line @next/next/no-img-element -- remote CDN photo
        <img
          src={entry.photo_url ?? undefined}
          alt=""
          onError={() => setBroken(true)}
          className="h-20 w-20 rounded-full object-cover object-top shadow-[0_2px_6px_rgba(0,0,0,0.35)]"
        />
      ) : (
        <div
          aria-hidden="true"
          style={{ background: avatarColor(entry.id) }}
          className="flex h-20 w-20 items-center justify-center rounded-full text-body font-bold text-white/90"
        >
          {initials(entry.name)}
        </div>
      )}
      <p className="mt-3 truncate text-bodySm font-bold text-content-primary">{entry.name}</p>
      <p className="mt-1 text-caption text-content-tertiary">
        {entry.degrees} degree{entry.degrees === 1 ? "" : "s"} away
      </p>
    </Link>
  );
}
