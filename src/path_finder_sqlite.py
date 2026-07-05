"""
SQLite Path Finder for Six Degrees of Kendrick Lamar

This module finds the shortest path between any artist and Kendrick Lamar
using BFS on the SQLite database.
"""

from collections import deque
from typing import Dict, List, Optional, Tuple
from database import CollaborationDatabase, build_adjacency_list


# Kendrick Lamar's Spotify ID
KENDRICK_ID = "2YZyLoL8N0Wb9xBt1NhZWg"


class PathFinder:
    """
    Finds shortest paths between artists in the collaboration network.
    Uses BFS for unweighted shortest path.
    """

    def __init__(self, db: CollaborationDatabase):
        """
        Initialize PathFinder with database.

        Args:
            db: CollaborationDatabase instance
        """
        self.db = db
        self._adjacency = None

    def _get_adjacency(self) -> Dict[str, List[str]]:
        """Get or build adjacency list (cached)."""
        if self._adjacency is None:
            self._adjacency = build_adjacency_list(self.db)
        return self._adjacency

    def find_path(
        self,
        from_artist_id: str,
        to_artist_id: str = KENDRICK_ID
    ) -> Optional[List[str]]:
        """
        Find shortest path between two artists using BFS.

        Args:
            from_artist_id: Starting artist's Spotify ID
            to_artist_id: Target artist's Spotify ID (default: Kendrick)

        Returns:
            List of artist IDs representing the path, or None if no path exists
        """
        if from_artist_id == to_artist_id:
            return [from_artist_id]

        adjacency = self._get_adjacency()

        # Check if artists exist in network
        if from_artist_id not in adjacency:
            return None
        if to_artist_id not in adjacency:
            return None

        # BFS
        visited = {from_artist_id}
        queue = deque([(from_artist_id, [from_artist_id])])

        while queue:
            current_id, path = queue.popleft()

            for neighbor_id in adjacency.get(current_id, []):
                if neighbor_id == to_artist_id:
                    return path + [neighbor_id]

                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, path + [neighbor_id]))

        return None

    def find_connection(
        self,
        from_artist_id: str,
        to_artist_id: str = KENDRICK_ID
    ) -> Optional[Dict]:
        """
        Find connection between two artists with full details.

        Args:
            from_artist_id: Starting artist's Spotify ID
            to_artist_id: Target artist's Spotify ID (default: Kendrick)

        Returns:
            Dictionary with path details, or None if no connection
        """
        path = self.find_path(from_artist_id, to_artist_id)

        if not path:
            return None

        # Build detailed path info
        path_details = []
        connections = []

        for i, artist_id in enumerate(path):
            artist = self.db.get_artist(artist_id)
            path_details.append({
                'id': artist_id,
                'name': artist['name'] if artist else 'Unknown'
            })

            # Add connection info for each edge
            if i > 0:
                prev_id = path[i - 1]
                songs = self.db.get_collaboration_songs(prev_id, artist_id)
                song_details = self.db.get_collaboration_song_details(prev_id, artist_id)
                connections.append({
                    'from': path_details[i - 1],
                    'to': path_details[i],
                    'songs': songs,
                    'song_details': song_details,
                })

        return {
            'degrees': len(path) - 1,
            'path': path_details,
            'connections': connections
        }

    def format_path_output(self, connection: Dict) -> str:
        """
        Format connection details for display.

        Args:
            connection: Connection dict from find_connection()

        Returns:
            Formatted string for display
        """
        if not connection:
            return "No connection found."

        lines = []
        degrees = connection['degrees']

        # Header
        start = connection['path'][0]['name']
        end = connection['path'][-1]['name']

        if degrees == 0:
            lines.append(f"{start} IS {end}!")
        else:
            lines.append(f"Connection: {start} → {end}")
            lines.append(f"Degrees of separation: {degrees}")
            lines.append("")

            # Path visualization
            lines.append("Path:")
            for i, artist in enumerate(connection['path']):
                prefix = "  → " if i > 0 else "    "
                lines.append(f"{prefix}{artist['name']}")

            # Connection details with songs
            lines.append("")
            lines.append("Collaborations:")
            for conn in connection['connections']:
                lines.append(f"  {conn['from']['name']} ↔ {conn['to']['name']}")
                for song in conn['songs'][:5]:  # Limit to 5 songs
                    lines.append(f"    • {song}")
                if len(conn['songs']) > 5:
                    lines.append(f"    • ... and {len(conn['songs']) - 5} more")

        return "\n".join(lines)


def find_kendrick_number(db: CollaborationDatabase, artist_name: str) -> Optional[Dict]:
    """
    Convenience function to find an artist's Kendrick number.

    Args:
        db: CollaborationDatabase instance
        artist_name: Name of artist to search for

    Returns:
        Connection dict or None if not found
    """
    # Search for artist
    artist = db.get_artist_by_name(artist_name)

    if not artist:
        # Try partial search
        results = db.search_artists(artist_name, limit=1)
        if results:
            artist = results[0]
        else:
            return None

    # Find path
    finder = PathFinder(db)
    return finder.find_connection(artist['id'], KENDRICK_ID)
