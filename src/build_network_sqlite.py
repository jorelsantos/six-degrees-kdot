"""
SQLite Network Builder for Six Degrees of Kendrick Lamar

This script builds the artist collaboration network and stores it in SQLite.
Run this once to populate the database, then use the Streamlit app to query it.

Features:
- Parallel processing using ThreadPoolExecutor
- Smart rate limiting to maximize speed without hitting API limits
- Full pagination to capture all artist collaborations
"""

import sys
import time
import threading
from pathlib import Path
from typing import Set, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from data_fetcher import SpotifyAPIClient, get_rate_limiter, RateLimitPenaltyError
from database import CollaborationDatabase


# Kendrick Lamar's Spotify ID
KENDRICK_ID = "2YZyLoL8N0Wb9xBt1NhZWg"

# Thread-safe lock for database writes
db_lock = threading.Lock()

# Thread-safe sets for tracking progress
processed_lock = threading.Lock()


def process_single_artist(
    artist_id: str,
    client: SpotifyAPIClient,
    db: CollaborationDatabase,
    max_albums: int,
    processed: Set[str]
) -> Tuple[str, List[str], int]:
    """
    Process a single artist: fetch info, find collaborators, save to database.

    Args:
        artist_id: Spotify artist ID to process
        client: SpotifyAPIClient instance
        db: CollaborationDatabase instance
        max_albums: Maximum albums to analyze
        processed: Set of already processed artist IDs

    Returns:
        Tuple of (artist_name, list of collaborator IDs, collaborator count)
    """
    # Check if already processed
    with processed_lock:
        if artist_id in processed:
            return ("", [], 0)
        processed.add(artist_id)

    # Resume support: if this artist was already crawled in a prior (interrupted)
    # run, skip the live API work entirely and return its existing neighbors.
    with db_lock:
        already_crawled = db.is_artist_crawled(artist_id)
        if already_crawled:
            artist = db.get_artist(artist_id)
            neighbors = db.get_artist_neighbors(artist_id)
    if already_crawled:
        artist_name = artist['name'] if artist else artist_id
        return (artist_name, neighbors, len(neighbors))

    try:
        # Get artist info
        artist_info = client._make_request(f"/artists/{artist_id}")
        artist_name = artist_info['name']

        # Add artist to database
        with db_lock:
            db.add_artist(
                artist_id=artist_id,
                name=artist_name,
                popularity=artist_info.get('popularity', 0),
                genres=artist_info.get('genres', [])
            )

        # Get collaborators
        collaborators = client.get_artist_collaborators(artist_id, max_albums)

        # Collect collaborator IDs for next level
        collaborator_ids = []

        # Add each collaborator to database
        with db_lock:
            for collab_key, collab_info in collaborators.items():
                collab_id = collab_info.get('id')
                collab_name = collab_info['name']

                # Skip collaborators without IDs
                if not collab_id:
                    continue

                # Add collaborator to database
                db.add_artist(
                    artist_id=collab_id,
                    name=collab_name
                )

                # Add edges for each song
                for song in collab_info['tracks']:
                    db.add_collaboration(artist_id, collab_id, song)

                collaborator_ids.append(collab_id)

            # Mark crawled only after all edges for this artist are recorded,
            # so a crash mid-processing leaves it correctly un-crawled for retry.
            db.mark_artist_crawled(artist_id)

        return (artist_name, collaborator_ids, len(collaborators))

    except RateLimitPenaltyError:
        # Do not swallow this as an ordinary per-artist failure -- a large
        # rate-limit penalty means the whole crawl should stop, not just this
        # artist. Re-raise so it reaches build_network's collection loop.
        raise
    except Exception as e:
        print(f"  Error processing artist {artist_id}: {e}")
        return ("", [], 0)


def build_network(
    db: CollaborationDatabase,
    client: SpotifyAPIClient,
    starting_artist_id: str = KENDRICK_ID,
    depth: int = 2,
    max_albums: int = 15,
    max_workers: int = 10
) -> None:
    """
    Build the collaboration network using parallel BFS from a starting artist.

    Args:
        db: CollaborationDatabase instance
        client: SpotifyAPIClient instance
        starting_artist_id: Artist ID to start from (default: Kendrick Lamar)
        depth: How many degrees of separation to build
        max_albums: Maximum albums to analyze per artist
        max_workers: Number of parallel threads to use
    """
    print(f"\n{'='*70}")
    print(f"Building {depth}-degree network from starting artist...")
    print(f"Using {max_workers} parallel workers")
    print(f"{'='*70}")

    start_time = time.time()

    # Track processed artists (thread-safe via processed_lock)
    processed: Set[str] = set()

    # Current level of artists to process
    current_level = {starting_artist_id}

    for level in range(depth):
        level_start = time.time()
        artists_to_process = [aid for aid in current_level if aid not in processed]

        print(f"\n--- Processing Degree {level + 1} ({len(artists_to_process)} artists) ---")

        if not artists_to_process:
            print("  No new artists to process at this level.")
            continue

        next_level: Set[str] = set()
        completed_count = 0

        # Process artists in parallel. A stuck worker (e.g. a socket that never
        # times out at the OS/library level despite our own timeout= settings)
        # must not block the whole level indefinitely -- Python threads can't be
        # force-killed, and ThreadPoolExecutor's own `with`-block shutdown waits
        # for every submitted task. So this loop bounds total wait time itself:
        # it polls for completions with a per-wait timeout, and gives up on
        # whatever's still pending after too many consecutive stalled polls,
        # moving on to the next level rather than hanging forever. Any
        # abandoned (never-crawled) artists simply stay eligible for a future
        # --resume run, since they're never marked `crawled`.
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_artist = {
                executor.submit(
                    process_single_artist,
                    artist_id,
                    client,
                    db,
                    max_albums,
                    processed
                ): artist_id
                for artist_id in artists_to_process
            }

            pending = set(future_to_artist.keys())
            poll_timeout = 90  # seconds to wait for at least one completion
            max_consecutive_stalls = 3  # ~4.5 minutes of zero progress before giving up on this level

            stall_streak = 0
            while pending:
                done, pending = wait(pending, timeout=poll_timeout, return_when=FIRST_COMPLETED)

                if not done:
                    stall_streak += 1
                    print(f"  WARNING: no artists completed in the last {poll_timeout}s "
                          f"({len(pending)} still pending; stall {stall_streak}/{max_consecutive_stalls}) "
                          f"-- a worker may be stuck on a hung connection.")
                    if stall_streak >= max_consecutive_stalls:
                        print(f"  Giving up on {len(pending)} stuck artist(s) for this level; "
                              f"they remain uncrawled and will be retried on the next --resume run.")
                        break
                    continue

                stall_streak = 0
                for future in done:
                    artist_id = future_to_artist[future]
                    try:
                        artist_name, collaborator_ids, collab_count = future.result()
                        if artist_name:
                            completed_count += 1
                            # Add collaborators to next level
                            next_level.update(collaborator_ids)

                            # Progress update every 10 artists
                            if completed_count % 10 == 0:
                                rate_stats = get_rate_limiter().get_stats()
                                print(f"  Processed {completed_count}/{len(artists_to_process)} artists "
                                      f"(API: {rate_stats['requests_in_window']}/{rate_stats['max_requests']} req/30s)")

                    except RateLimitPenaltyError:
                        # Re-raise past this loop, the `while pending` loop, and the
                        # `for level` loop -- a large penalty stops the entire
                        # multi-level crawl, not just this artist or this level.
                        # The enclosing `finally: executor.shutdown(...)` still runs
                        # during this unwind before the exception reaches main().
                        raise
                    except Exception as e:
                        print(f"  Error with artist {artist_id}: {e}")
        finally:
            # Don't block on any leaked/stuck threads -- cancel unstarted work
            # and return immediately; abandoned threads die with the process.
            executor.shutdown(wait=False, cancel_futures=True)

        level_time = time.time() - level_start
        print(f"  Level {level + 1} completed in {level_time:.1f} seconds")
        print(f"  Found {len(next_level)} potential artists for next level")

        # Move to next level (excluding already processed)
        current_level = next_level - processed

    total_time = time.time() - start_time

    # Print final stats
    stats = db.get_stats()
    print(f"\n{'='*70}")
    print(f"Network built successfully in {total_time:.1f} seconds!")
    print(f"  Total artists: {stats['total_artists']}")
    print(f"  Total collaborations: {stats['total_collaborations']}")
    print(f"  Total songs: {stats['total_songs']}")
    print(f"{'='*70}\n")


def main():
    """Main entry point for building the network. Exits non-zero on failure
    so an unattended/background run signals failure clearly rather than
    silently exiting 0."""
    import argparse

    parser = argparse.ArgumentParser(description="Build the Six Degrees of Kendrick Lamar collaboration network.")
    parser.add_argument(
        "--fresh", action="store_true",
        help="Clear existing network data and rebuild from scratch, non-interactively "
             "(required for unattended/background runs; skips the y/n prompt)."
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Keep existing network data and continue crawling non-interactively "
             "(skips the y/n prompt without wiping progress; already-crawled "
             "artists are skipped via the `crawled` marker)."
    )
    parser.add_argument(
        "--depth", type=int, default=2,
        help="Degrees of separation to crawl from the starting artist (default: 2)."
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Six Degrees of Kendrick Lamar - Network Builder (Parallel)")
    print("=" * 70)
    print(f"\nThis will build a {args.depth}-degree collaboration network starting from Kendrick Lamar.")
    print("Estimated time varies with depth and existing progress.\n")

    # Initialize database
    db_path = Path(__file__).parent.parent / "data" / "collaboration_network.db"
    print(f"Database: {db_path}")

    db = CollaborationDatabase(str(db_path))

    # Check existing data
    stats = db.get_stats()
    if stats['total_artists'] > 0:
        print(f"\nExisting database found:")
        print(f"  - {stats['total_artists']} artists")
        print(f"  - {stats['total_collaborations']} collaborations")

        if args.fresh:
            response = 'y'
        elif args.resume:
            print("Resuming: keeping existing data, continuing to crawl unprocessed artists.")
            response = 'n'
        else:
            response = input("\nRebuild from scratch? (y/n): ").strip().lower()

        if response == 'y':
            # Clear existing data
            print("Clearing existing data...")
            with db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM songs")
                cursor.execute("DELETE FROM collaborations")
                cursor.execute("DELETE FROM artists")
        elif not args.resume:
            print("Keeping existing database. Exiting.")
            return

    if args.fresh:
        # Clear the JSON API-response cache too, so a fresh rebuild can't
        # silently reuse responses cached by older (e.g. pre-pagination-fix) code.
        cache_dir = Path(__file__).parent.parent / "data"
        cache_files = list(cache_dir.glob("*.json"))
        if cache_files:
            print(f"Clearing {len(cache_files)} cached API response file(s)...")
            for f in cache_files:
                f.unlink()

    # Initialize Spotify client
    print("\nInitializing Spotify client...")
    try:
        client = SpotifyAPIClient()
    except Exception as e:
        print(f"\nError: Could not initialize Spotify client.")
        print(f"Make sure you have a .env file with SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET")
        print(f"Error details: {e}")
        sys.exit(1)

    # Verify Kendrick exists
    print("Verifying Kendrick Lamar...")
    kendrick = client.search_artist("Kendrick Lamar")
    if not kendrick:
        print("Error: Could not find Kendrick Lamar on Spotify!")
        sys.exit(1)

    print(f"Found: {kendrick['name']} (ID: {kendrick['id']})")

    # Build the network with parallel processing
    # Using 5 workers to be conservative with Spotify's rate limits
    build_network(
        db=db,
        client=client,
        starting_artist_id=kendrick['id'],
        depth=args.depth,
        max_albums=15,
        max_workers=5  # Reduced from 10 to avoid rate limiting
    )

    print("Done! Your network is ready in the SQLite database.")
    print(f"Database location: {db_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nFATAL: rebuild failed with an unhandled error: {e}")
        raise
