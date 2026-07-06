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
        (CC0). Song previews and links via the{" "}
        <a
          href="https://www.apple.com/apple-music/"
          target="_blank"
          rel="noreferrer"
          className="text-brand hover:underline"
        >
          Apple Music / iTunes
        </a>{" "}
        and{" "}
        <a
          href="https://www.deezer.com"
          target="_blank"
          rel="noreferrer"
          className="text-brand hover:underline"
        >
          Deezer
        </a>{" "}
        APIs. Not affiliated with Apple, Deezer, or the artists.
      </p>
    </footer>
  );
}
