"""Debug script to see which albums are being analyzed"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from data_fetcher import get_spotify_client
from collections import Counter

client = get_spotify_client()

# Search for Kendrick Lamar
artist = client.search_artist("Kendrick Lamar")
print(f"Artist: {artist['name']} (ID: {artist['id']})")
print()

# Get ALL albums (including guest appearances)
all_albums = client.get_artist_albums(artist['id'], limit=50, own_albums_only=False)

print(f"Total albums found (including guest appearances): {len(all_albums)}")
print("\nAll albums (in order returned by Spotify):")
print("=" * 80)

for i, album in enumerate(all_albums, 1):
    primary = "✓" if album.get('is_primary_artist', False) else "✗"
    print(f"{i:2}. {primary} [{album['type']:10}] {album['name'][:45]:45} ({album['release_date']:10}) - {album['total_tracks']} tracks")

print("\n" + "=" * 80)
print("\nAlbum type counts:")
type_counts = Counter(album['type'] for album in all_albums)
for album_type, count in type_counts.items():
    print(f"  {album_type}: {count}")

# Get ONLY Kendrick's own albums (what the fixed version uses)
own_albums = client.get_artist_albums(artist['id'], limit=50, own_albums_only=True)

print("\n" + "=" * 80)
print(f"\nKendrick's OWN albums only (own_albums_only=True): {len(own_albums)}")
print("=" * 80)

for i, album in enumerate(own_albums, 1):
    print(f"{i:2}. [{album['type']:10}] {album['name'][:45]:45} ({album['release_date']:10}) - {album['total_tracks']} tracks")

# Show what the prioritization algorithm would select
print("\n" + "=" * 80)
print("\nTop 15 albums after prioritization (what get_artist_collaborators uses):")
print("=" * 80)

type_priority = {"album": 0, "single": 1, "compilation": 2}
sorted_albums = sorted(
    own_albums,
    key=lambda x: (type_priority.get(x['type'], 3), x.get('release_date', ''))
)

for i, album in enumerate(sorted_albums[:15], 1):
    print(f"{i:2}. [{album['type']:10}] {album['name'][:45]:45} ({album['release_date']:10}) - {album['total_tracks']} tracks")
