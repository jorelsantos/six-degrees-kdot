// Footer carries the non-affiliation disclaimer (KTD5/R3), the data
// attribution ported verbatim-in-spirit from the Streamlit app, and photo
// attribution (plan 2026-07-09-001, R8 — Wikimedia Commons images are
// CC-BY/CC-BY-SA and require credit; TheAudioDB/Deezer images are used
// as-is from their public artist APIs).
export function SiteFooter() {
  return (
    <footer className="mt-12 border-t border-border-subtle px-6 py-6 text-center text-caption leading-relaxed text-content-tertiary">
      <p className="mb-1 text-content-secondary">
        An unofficial concept by Jor-El Santos — not affiliated with Spotify.
      </p>
      <p>
        Collaboration data from{" "}
        <a
          href="https://musicbrainz.org"
          target="_blank"
          rel="noreferrer"
          className="text-brand hover:underline"
        >
          MusicBrainz
        </a>{" "}
        (CC0). Artist photos from Wikimedia Commons, TheAudioDB, and Deezer. Song
        previews via Spotify. Not affiliated with Spotify, Wikimedia, TheAudioDB,
        Deezer, or the artists.
      </p>
    </footer>
  );
}
