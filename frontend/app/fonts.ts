import localFont from "next/font/local";

// Figtree (OFL, committed under frontend/fonts/) — a free Circular-alike, loaded
// locally so there is zero network dependency at build or runtime (KTD4). The
// files are variable fonts spanning weights 400–900. Latin covers the common
// music-name diacritics (é, ñ, ü, ç); latin-ext is included for broader coverage.
export const figtree = localFont({
  src: [
    { path: "../fonts/Figtree-latin.woff2", weight: "400 900", style: "normal" },
    { path: "../fonts/Figtree-latinext.woff2", weight: "400 900", style: "normal" },
  ],
  variable: "--font-figtree",
  display: "swap",
  fallback: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
});
