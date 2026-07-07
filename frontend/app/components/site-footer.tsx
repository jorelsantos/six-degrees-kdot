// Footer carries the non-affiliation disclaimer (KTD5/R3) and the data
// attribution ported verbatim-in-spirit from the Streamlit app.
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
        (CC0). Song previews via Spotify, Apple Music, and Deezer. Not
        affiliated with Spotify, Apple, Deezer, or the artists.
      </p>
    </footer>
  );
}
