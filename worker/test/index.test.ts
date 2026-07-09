import { env } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";

const KENDRICK = "kdot";

async function seed() {
  // D1's .exec() is line-based (one statement per line, no embedded
  // newlines) — unlike a normal SQLite multi-statement script.
  await env.DB.exec(
    `CREATE TABLE IF NOT EXISTS artists (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_norm TEXT, popularity INTEGER, degree INTEGER, photo_url TEXT, kendrick_distance INTEGER, predecessor_id TEXT, via_song_title TEXT, via_song_collaborators TEXT, via_track_id TEXT);`,
  );
  await env.DB.exec(
    `CREATE TABLE IF NOT EXISTS aliases (artist_id TEXT NOT NULL, alias TEXT NOT NULL, alias_norm TEXT);`,
  );
  await env.DB.exec(`DROP TABLE IF EXISTS search_fts;`);
  await env.DB.exec(`CREATE VIRTUAL TABLE search_fts USING fts5(artist_id UNINDEXED, term);`);
  // Clear any rows left from a prior test (belt-and-suspenders alongside
  // vitest-pool-workers' isolated storage).
  await env.DB.exec(`DELETE FROM artists;`);
  await env.DB.exec(`DELETE FROM aliases;`);
  await env.DB.exec(`DELETE FROM search_fts;`);

  const rows: [string, string, string, number, number, string | null, number | null, string | null, string | null, string | null, string | null][] = [
    [KENDRICK, "Kendrick Lamar", "kendrick lamar", 100, 293, "https://commons.wikimedia.org/kdot.jpg", 0, null, null, null, null],
    ["drake", "Drake", "drake", 90, 263, "https://commons.wikimedia.org/drake.jpg", 1, KENDRICK, "Sing About Me", JSON.stringify(["Kendrick Lamar", "Drake"]), "real-track-id"],
    ["sza", "SZA", "sza", 80, 53, null, 1, KENDRICK, "luther", JSON.stringify(["Kendrick Lamar", "SZA"]), null],
    ["future", "Future", "future", 70, 381, null, 2, "drake", "Jumpman", JSON.stringify(["Drake", "Future"]), "none"],
    ["island", "Islander", "islander", 0, 0, null, null, null, null, null, null],
  ];
  for (const r of rows) {
    await env.DB.prepare(
      `INSERT INTO artists (id, name, name_norm, popularity, degree, photo_url,
        kendrick_distance, predecessor_id, via_song_title, via_song_collaborators, via_track_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(...r).run();
    await env.DB.prepare(`INSERT INTO search_fts(artist_id, term) VALUES (?, ?)`).bind(r[0], r[1]).run();
  }
  await env.DB.prepare(`INSERT INTO aliases (artist_id, alias, alias_norm) VALUES (?, ?, ?)`)
    .bind("drake", "Drizzy", "drizzy").run();
  await env.DB.prepare(`INSERT INTO search_fts(artist_id, term) VALUES (?, ?)`).bind("drake", "Drizzy").run();
}

beforeEach(async () => {
  await seed();
});

function req(path: string, init?: RequestInit): Request {
  return new Request(`https://worker.test${path}`, init);
}

describe("GET /api/search", () => {
  it("returns Drake first for a matching query", async () => {
    const res = await worker.fetch(req("/api/search?q=drake"), env);
    expect(res.status).toBe(200);
    const body = await res.json<any>();
    expect(body.candidates[0].name).toBe("Drake");
    expect(body.candidates[0].degree).toBe(263);
  });

  it("finds an artist by alias", async () => {
    const res = await worker.fetch(req("/api/search?q=Drizzy"), env);
    const body = await res.json<any>();
    expect(body.candidates.map((c: any) => c.id)).toContain("drake");
  });

  it("handles punctuation-heavy input without a 500 (doc review P1)", async () => {
    const res = await worker.fetch(req("/api/search?q=" + encodeURIComponent("AC/DC")), env);
    expect(res.status).toBe(200);
    const body = await res.json<any>();
    expect(Array.isArray(body.candidates)).toBe(true);
  });

  it("returns empty candidates for a query under the minimum length", async () => {
    const res = await worker.fetch(req("/api/search?q=a"), env);
    const body = await res.json<any>();
    expect(body.candidates).toEqual([]);
  });
});

describe("GET /api/connection", () => {
  it("returns a full chain for a distance-2 artist", async () => {
    const res = await worker.fetch(req("/api/connection?artist_id=future"), env);
    const body = await res.json<any>();
    expect(body.connection.degrees).toBe(2);
    expect(body.connection.path.map((p: any) => p.name)).toEqual(["Future", "Drake", "Kendrick Lamar"]);
    expect(body.connection.hops[0].song_name).toBe("Jumpman");
    expect(body.connection.hops[0].track_id).toBeNull(); // "none" sentinel -> null for display
    expect(body.connection.hops[1].track_id).toBe("real-track-id");
  });

  it("returns is_kendrick for Kendrick himself", async () => {
    const res = await worker.fetch(req(`/api/connection?artist_id=${KENDRICK}`), env);
    const body = await res.json<any>();
    expect(body.connection.is_kendrick).toBe(true);
    expect(body.connection.degrees).toBe(0);
  });

  it("returns 404 for an unknown artist id, not a fake not_found body", async () => {
    const res = await worker.fetch(req("/api/connection?artist_id=nonexistent"), env);
    expect(res.status).toBe(404);
  });

  it("returns 200 with a null connection for a known but unreachable artist", async () => {
    const res = await worker.fetch(req("/api/connection?artist_id=island"), env);
    expect(res.status).toBe(200);
    const body = await res.json<any>();
    expect(body.connection).toBeNull();
  });

  it("caches a complete chain long and a pending chain short", async () => {
    const complete = await worker.fetch(req("/api/connection?artist_id=drake"), env);
    expect(complete.headers.get("cache-control")).toContain("86400");

    const pending = await worker.fetch(req("/api/connection?artist_id=sza"), env); // via_track_id NULL
    expect(pending.headers.get("cache-control")).toContain("60");
  });
});

describe("POST /api/resolve-track", () => {
  it("returns the already-resolved id without any Spotify call", async () => {
    const res = await worker.fetch(req("/api/resolve-track?artist_id=drake", { method: "POST" }), env);
    const body = await res.json<any>();
    expect(body.spotify_track_id).toBe("real-track-id");
  });

  it("returns null (not the raw sentinel) for an artist already confirmed to have no player", async () => {
    const res = await worker.fetch(req("/api/resolve-track?artist_id=future", { method: "POST" }), env);
    const body = await res.json<any>();
    expect(body.spotify_track_id).toBeNull();
  });

  it("returns 404 for an unknown artist id", async () => {
    const res = await worker.fetch(req("/api/resolve-track?artist_id=nonexistent", { method: "POST" }), env);
    expect(res.status).toBe(404);
  });

  it("degrades to null when Spotify credentials are absent", async () => {
    const res = await worker.fetch(req("/api/resolve-track?artist_id=sza", { method: "POST" }), env);
    const body = await res.json<any>();
    expect(body.spotify_track_id).toBeNull();
  });
});
