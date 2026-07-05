#!/usr/bin/env bash
#
# U1 — Acquire and stage the MusicBrainz core dump subset.
#
# Downloads the latest MusicBrainz core data dump (mbdump.tar.bz2) from a
# MetaBrainz mirror, then extracts ONLY the table files the graph build needs
# (per KTD6-as-amended / KTD10). Records dump version, URL, file sizes and row
# counts in docs/musicbrainz-ingest-notes.md so U2 has a known baseline.
#
# The core dump is CC0 (public domain) and has NO rate limit — this is a
# one-time bulk download, not a crawl.
#
# Safe to re-run: the download resumes (curl -C -) and extraction overwrites.
# Everything lands in data/mb_raw/ which is gitignored (do NOT commit it).
#
# Usage:
#   bash scripts/fetch_musicbrainz_dump.sh
#   MIRROR=https://data.metabrainz.org/pub/musicbrainz/data/fullexport \
#     bash scripts/fetch_musicbrainz_dump.sh     # override mirror
#
# Requires: curl, tar, bzip2 (all standard on macOS).

set -euo pipefail

# --- config ----------------------------------------------------------------

# MetaBrainz official mirror. Alternatives (if slow/unavailable):
#   https://mirrors.dotsrc.org/MusicBrainz/data/fullexport
#   https://data.mtnz.io/data/fullexport   (community mirrors vary)
MIRROR="${MIRROR:-https://data.metabrainz.org/pub/musicbrainz/data/fullexport}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAW_DIR="$REPO_ROOT/data/mb_raw"
NOTES="$REPO_ROOT/docs/musicbrainz-ingest-notes.md"
ARCHIVE="mbdump.tar.bz2"

# Table files to extract from the archive (tar members live under mbdump/).
# Edge derivation (KTD2): artist, artist_credit, artist_credit_name, recording
# Official-release filter (KTD10): recording->track->medium->release (release.status
#   is an int; 1 = Official) and release_group + secondary-type tables for the
#   Interview/Spokenword exclusion.
# Alias search: artist_alias maps alternate names (e.g. "Kanye West") to the
#   canonical artist node (e.g. "Ye"), so a search by any known name resolves.
TABLES=(
  artist
  artist_alias
  artist_credit
  artist_credit_name
  recording
  track
  medium
  release
  release_group
  release_status
  release_group_secondary_type
  release_group_secondary_type_join
)

# --- resolve latest dump ----------------------------------------------------

mkdir -p "$RAW_DIR"
cd "$RAW_DIR"

echo ">> Resolving latest export from $MIRROR ..."
LATEST="$(curl -fsSL "$MIRROR/LATEST")"
if [[ -z "$LATEST" ]]; then
  echo "!! Could not read LATEST from mirror. Check connectivity / MIRROR var." >&2
  exit 1
fi
DUMP_URL="$MIRROR/$LATEST/$ARCHIVE"
echo ">> Latest dump: $LATEST"
echo ">> Archive URL: $DUMP_URL"

# --- download (resumable) ---------------------------------------------------

# Skip re-downloading if the local file already matches the remote size.
# (Resuming a file that is already complete makes curl request a range past
# EOF, which errors under -f and aborts the script — so check size first.)
REMOTE_SIZE="$(curl -fsSLI "$DUMP_URL" | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r' | tail -1)"
LOCAL_SIZE=0
[[ -f "$ARCHIVE" ]] && LOCAL_SIZE="$(wc -c < "$ARCHIVE" | tr -d ' ')"
if [[ -n "$REMOTE_SIZE" && "$LOCAL_SIZE" == "$REMOTE_SIZE" ]]; then
  echo ">> $ARCHIVE already complete ($LOCAL_SIZE bytes); skipping download."
else
  echo ">> Downloading $ARCHIVE (multi-GB; resumable) ..."
  curl -fL -C - -o "$ARCHIVE" "$DUMP_URL"
fi

# Integrity check. MD5SUMS lines look like "<hash> *<file>" (binary marker) or
# "<hash>  <file>" — extract the hash for our archive by filename, and compare
# with md5sum (coreutils) or md5 (macOS built-in).
if curl -fsSL -o MD5SUMS "$MIRROR/$LATEST/MD5SUMS" 2>/dev/null; then
  EXPECTED="$(awk -v f="$ARCHIVE" 'index($0, f){print $1; exit}' MD5SUMS)"
  if [[ -z "$EXPECTED" ]]; then
    echo ">> (no MD5 entry for $ARCHIVE; skipping checksum verification)"
  else
    echo ">> Verifying MD5 (expected $EXPECTED) ..."
    if command -v md5sum >/dev/null 2>&1; then
      ACTUAL="$(md5sum "$ARCHIVE" | cut -d' ' -f1)"
    else
      ACTUAL="$(md5 -q "$ARCHIVE")"
    fi
    if [[ "$ACTUAL" != "$EXPECTED" ]]; then
      echo "!! MD5 mismatch (got $ACTUAL). Delete $ARCHIVE and re-run." >&2
      exit 1
    fi
    echo ">> MD5 OK."
  fi
fi

# --- extract only the needed table files ------------------------------------

echo ">> Extracting ${#TABLES[@]} table files ..."
MEMBERS=()
for t in "${TABLES[@]}"; do MEMBERS+=("mbdump/$t"); done
# Not all lookup tables exist in every export layout; tolerate missing members.
tar -xjf "$ARCHIVE" -C "$RAW_DIR" "${MEMBERS[@]}" 2>/dev/null || {
  echo ">> (some optional members absent; extracting available core tables)"
  for m in "${MEMBERS[@]}"; do
    tar -xjf "$ARCHIVE" -C "$RAW_DIR" "$m" 2>/dev/null || echo "   -- skipped missing: $m"
  done
}

# --- record row counts + notes ----------------------------------------------

echo ">> Counting rows and writing $NOTES ..."
{
  echo "# MusicBrainz ingest notes (U1)"
  echo
  echo "- **Dump version:** \`$LATEST\`"
  echo "- **Mirror:** $MIRROR"
  echo "- **Archive:** $DUMP_URL"
  echo "- **Staged at:** \`data/mb_raw/mbdump/\` (gitignored — not committed)"
  echo "- **License:** CC0 (MusicBrainz core data)"
  echo
  echo "## Row counts (per staged table)"
  echo
  echo "| table | rows | size |"
  echo "|---|---:|---:|"
  for t in "${TABLES[@]}"; do
    f="$RAW_DIR/mbdump/$t"
    if [[ -f "$f" ]]; then
      rows="$(wc -l < "$f" | tr -d ' ')"
      size="$(du -h "$f" | cut -f1)"
      printf "| %s | %s | %s |\n" "$t" "$rows" "$size"
    else
      printf "| %s | (absent) | - |\n" "$t"
    fi
  done
  echo
  echo "_Generated by scripts/fetch_musicbrainz_dump.sh on $(date '+%Y-%m-%d %H:%M %Z')._"
} > "$NOTES"

echo
echo ">> DONE. Staged tables in $RAW_DIR/mbdump/ ; notes in $NOTES"
echo ">> Sanity: recording/artist should be in the millions."
cat "$NOTES"
