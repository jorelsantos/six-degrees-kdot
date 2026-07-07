"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { searchArtists, type Candidate } from "@/lib/api";

const DEBOUNCE_MS = 150;
const SHORT_QUERY_DEBOUNCE_MS = 260; // longer for <=3 chars (fuzzy path is ~190ms server-side)

/**
 * Accessible combobox typeahead (U4). Deliberately a *dumb renderer* of the
 * API's candidate order — there is no client-side filtering or sorting, so R2's
 * never-re-rank contract holds by construction. The "Showing results for X"
 * notice decision comes from the API's matches_query flag, never a client
 * string comparison (Unicode-divergent).
 */
export function SearchTypeahead() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [active, setActive] = useState(-1); // highlighted index; -1 = none
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [searched, setSearched] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const listId = "artist-suggestions";

  // Debounced search. Aborts the in-flight request on every keystroke so a slow
  // fuzzy response can never repaint a stale dropdown.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setCandidates([]);
      setSearched(false);
      setPending(false);
      abortRef.current?.abort();
      return;
    }
    const delay = q.length <= 3 ? SHORT_QUERY_DEBOUNCE_MS : DEBOUNCE_MS;
    setPending(true);
    const handle = setTimeout(async () => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const results = await searchArtists(q, ctrl.signal);
        setCandidates(results);
        setSearched(true);
        setActive(-1);
        setOpen(true);
      } catch (err) {
        if ((err as Error).name !== "AbortError") setCandidates([]);
      } finally {
        setPending(false);
      }
    }, delay);
    return () => clearTimeout(handle);
  }, [query]);

  const go = useCallback(
    (c: Candidate, viaNotice: boolean) => {
      // Suggestion click / exact match => pin the node, no notice.
      // Auto-run of a non-matching top result => carry the notice flag; the
      // connection page renders "Showing results for {name}".
      const suffix = viaNotice && !c.matches_query ? "?notice=1" : "";
      router.push(`/connection/${encodeURIComponent(c.id)}${suffix}`);
    },
    [router],
  );

  function onSubmit() {
    if (active >= 0 && candidates[active]) {
      go(candidates[active], false); // explicit pick, no notice
    } else if (candidates.length > 0) {
      go(candidates[0], true); // auto-run top match, notice if name differs
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, candidates.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      onSubmit();
    } else if (e.key === "Escape") {
      setOpen(false);
      setActive(-1);
    }
  }

  const showDropdown = open && query.trim().length >= 2;
  const showEmpty = showDropdown && searched && !pending && candidates.length === 0;

  return (
    <div className="relative mx-auto w-full max-w-md">
      <div className="relative">
        {/* Leading search icon (U5 — compact, icon-led). */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-content-tertiary"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.8" />
            <path
              d="m20 20-3.5-3.5"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
        </span>
        <input
          type="text"
          role="combobox"
          aria-expanded={showDropdown}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `sugg-${active}` : undefined}
          autoFocus
          value={query}
          placeholder="Search an artist — e.g. Drake, SZA…"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => candidates.length > 0 && setOpen(true)}
          className="w-full rounded-pill border border-border-subtle bg-surface-raised py-3 pl-11 pr-10 text-bodySm text-content-primary placeholder:text-content-tertiary focus:border-brand focus:outline-none"
        />
        {pending && (
          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-caption text-content-tertiary">
            …
          </span>
        )}
      </div>

      {showDropdown && (candidates.length > 0 || showEmpty) && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-10 mt-2 w-full overflow-hidden rounded-lg border border-border-subtle bg-surface-raised shadow-[var(--shadow-raised)]"
        >
          {candidates.map((c, i) => (
            <li
              key={c.id}
              id={`sugg-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault(); // keep focus; fire before blur
                go(c, false);
              }}
              className={`flex cursor-pointer items-center justify-between px-6 py-3 text-left ${
                i === active ? "bg-surface-overlay" : ""
              }`}
            >
              <span className="font-medium text-content-primary">{c.label}</span>
              {c.label === c.name && (
                // Only show the collab-count metadata when the label is the bare
                // name; disambiguated labels already carry the count.
                <span className="ml-3 shrink-0 text-caption text-content-tertiary">
                  {c.degree} collab{c.degree === 1 ? "" : "s"}
                </span>
              )}
            </li>
          ))}
          {showEmpty && (
            <li className="px-6 py-4 text-bodySm text-content-secondary">
              No artist by that name in the network. Try a different spelling.
            </li>
          )}
        </ul>
      )}

      <button
        type="button"
        onClick={onSubmit}
        className="mt-5 w-full rounded-pill bg-brand px-8 py-4 font-bold uppercase tracking-[0.1em] text-black transition-transform hover:scale-[1.02] active:scale-100 disabled:opacity-40"
        disabled={candidates.length === 0}
      >
        Find Connection
      </button>
    </div>
  );
}
