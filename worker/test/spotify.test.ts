import { describe, expect, it } from "vitest";
import { buildQuery, pickAcceptedTrack, type SpotifyTrack } from "../src/spotify";

function track(id: string, name: string, artists: string[]): SpotifyTrack {
  return { id, name, artists: artists.map((n) => ({ name: n })) };
}

describe("buildQuery", () => {
  it("joins song name and artists", () => {
    expect(buildQuery("Sing About Me", ["Kendrick Lamar", "Drake"])).toBe(
      "Sing About Me Kendrick Lamar Drake",
    );
  });
});

describe("pickAcceptedTrack", () => {
  it("accepts the first candidate whose title and artist both match", () => {
    const winner = pickAcceptedTrack("Sing About Me", ["Kendrick Lamar", "Drake"], [
      track("real-id", "Sing About Me", ["Kendrick Lamar", "Drake"]),
    ]);
    expect(winner?.id).toBe("real-id");
  });

  it("rejects a same-titled song by an unrelated artist (wrong-face guard)", () => {
    const winner = pickAcceptedTrack("Really Doe", ["Kendrick Lamar", "Earl Sweatshirt"], [
      track("wrong-id", "Really Doe", ["Ice Cube"]),
    ]);
    expect(winner).toBeNull();
  });

  it("matches a title with a parenthetical remaster tag", () => {
    const winner = pickAcceptedTrack("Sing About Me", ["Kendrick Lamar"], [
      track("id", "Sing About Me (Remastered 2015)", ["Kendrick Lamar"]),
    ]);
    expect(winner?.id).toBe("id");
  });

  it("returns null when nothing in the candidate list matches", () => {
    const winner = pickAcceptedTrack("Sing About Me", ["Kendrick Lamar", "Drake"], [
      track("id", "Some Other Song", ["Somebody Else"]),
    ]);
    expect(winner).toBeNull();
  });

  it("skips an earlier non-matching candidate to accept a later matching one", () => {
    const winner = pickAcceptedTrack("Sing About Me", ["Kendrick Lamar", "Drake"], [
      track("wrong", "Unrelated Track", ["Nobody"]),
      track("right", "Sing About Me", ["Kendrick Lamar", "Drake"]),
    ]);
    expect(winner?.id).toBe("right");
  });
});
