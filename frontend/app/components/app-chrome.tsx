import type { ReactNode } from "react";
import { SiteFooter } from "./site-footer";

/**
 * Inert Spotify-web-app chrome (plan 2026-07-06-004, U3 / KTD3). Recreates the
 * shape of a music-app shell — left sidebar, top bar, profile avatar — so the
 * live feature reads as "a feature living inside Spotify" (the portfolio memo).
 *
 * Everything here is INTENTIONALLY inert and decorative: nav items don't route,
 * arrows don't navigate, the sidebar search is an echo. Rabbit Hole (`children`)
 * is the one live surface. That's standard and honest for a single-feature
 * concept pitch.
 *
 * Clean-room (DESIGN-NOTES): shapes/spacing recreated from observation with the
 * existing tokens; NO Spotify logo/wordmark/assets — icons are simple original
 * SVGs. Responsive: the sidebar is hidden below `md` so the 375px feature work
 * from plan 003 is never squeezed.
 */
export function AppChrome({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen gap-2 bg-black p-2">
      <Sidebar />
      <div className="flex min-h-[calc(100vh-1rem)] flex-1 flex-col overflow-hidden rounded-lg bg-surface-base">
        <TopBar />
        <div className="flex flex-1 flex-col overflow-y-auto">
          <div className="flex-1">{children}</div>
          <SiteFooter />
        </div>
      </div>
    </div>
  );
}

/* --- Left sidebar (decorative) --------------------------------------------- */
function Sidebar() {
  return (
    <aside
      aria-hidden="true"
      className="hidden w-[244px] shrink-0 cursor-default select-none flex-col gap-2 md:flex"
    >
      {/* Primary nav card */}
      <nav className="rounded-lg bg-surface-raised px-3 py-4">
        <NavItem icon={<HomeIcon />} label="Home" active />
        <NavItem icon={<SearchIcon />} label="Search" />
      </nav>

      {/* Library card — with a few inert "playlist" rows for texture */}
      <div className="flex flex-1 flex-col rounded-lg bg-surface-raised px-3 py-4">
        <NavItem icon={<LibraryIcon />} label="Your Library" />
        <ul className="mt-3 space-y-3 px-1">
          {["Liked Songs", "Discover Weekly", "Kendrick & Friends", "Deep Cuts"].map(
            (name) => (
              <li key={name} className="flex items-center gap-3">
                <span className="h-10 w-10 shrink-0 rounded-md bg-surface-overlay" />
                <span className="truncate text-bodySm text-content-secondary">
                  {name}
                </span>
              </li>
            ),
          )}
        </ul>
      </div>
    </aside>
  );
}

function NavItem({
  icon,
  label,
  active = false,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-4 py-2 text-bodySm font-bold ${
        active ? "text-content-primary" : "text-content-secondary"
      }`}
    >
      <span className="shrink-0">{icon}</span>
      <span>{label}</span>
    </div>
  );
}

/* --- Top bar --------------------------------------------------------------- */
function TopBar() {
  return (
    <header className="flex items-center justify-between gap-3 px-4 py-3">
      {/* Back / forward chevrons — inert */}
      <div aria-hidden="true" className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-black/60 text-content-secondary">
          <ChevronIcon dir="left" />
        </span>
        <span className="hidden h-8 w-8 items-center justify-center rounded-full bg-black/60 text-content-tertiary sm:flex">
          <ChevronIcon dir="right" />
        </span>
      </div>

      {/* Profile avatar — top-right per the user's ask */}
      <img
        src="/avatar.svg"
        alt="Profile"
        width={32}
        height={32}
        className="h-8 w-8 shrink-0 rounded-full"
      />
    </header>
  );
}

/* --- Clean-room icons (original SVGs, no lifted assets) --------------------- */
function HomeIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 11 12 4l9 7v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="1.8" />
      <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function LibraryIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 4v16M10 4v16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path
        d="m15 6 4 1v13l-4-1z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChevronIcon({ dir }: { dir: "left" | "right" }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d={dir === "left" ? "m14 6-6 6 6 6" : "m10 6 6 6-6 6"}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
