/**
 * Port of src/database.py's disambiguate_labels (plan 2026-07-09-001, U7).
 *
 * Unique names stay bare. Duplicate names get a collab-count qualifier
 * ("The Game · 573 collabs"); candidates that STILL tie (same name AND same
 * count) get a stable numbered suffix ordered by node id, so labels are
 * always distinct and deterministic — matching the Python engine exactly so
 * the frontend's typeahead behaves identically pre- and post-cutover.
 */
export interface SearchRow {
  id: string;
  name: string;
  degree: number;
  popularity: number;
}

export function disambiguateLabels(candidates: SearchRow[]): string[] {
  const nameCounts = new Map<string, number>();
  for (const c of candidates) {
    const key = c.name.toLowerCase();
    nameCounts.set(key, (nameCounts.get(key) ?? 0) + 1);
  }

  const qualified = candidates.map((c) => {
    const key = c.name.toLowerCase();
    if ((nameCounts.get(key) ?? 0) === 1) return c.name;
    const n = c.degree ?? 0;
    return `${c.name} · ${n} collab${n !== 1 ? "s" : ""}`;
  });

  const labelPositions = new Map<string, number[]>();
  qualified.forEach((label, i) => {
    const key = label.toLowerCase();
    const positions = labelPositions.get(key) ?? [];
    positions.push(i);
    labelPositions.set(key, positions);
  });

  for (const positions of labelPositions.values()) {
    if (positions.length <= 1) continue;
    positions.sort((a, b) => (candidates[a]!.id < candidates[b]!.id ? -1 : 1));
    positions.slice(1).forEach((i, idx) => {
      qualified[i] = `${qualified[i]} (${idx + 2})`;
    });
  }

  return qualified;
}

/**
 * Sanitize free-text user input into a safe FTS5 MATCH query (doc review
 * finding, P1 — feasibility + security agreement): FTS5 treats its query
 * string as a small query LANGUAGE (quotes, `-`, `*`, `AND`/`OR`/`NOT`,
 * column filters), so routine search input like "AC/DC" or "P!nk" would
 * otherwise throw a parse error. Splitting on non-token characters and
 * wrapping each token as an escaped, quoted prefix term makes every input a
 * valid MATCH expression — punctuation just disappears, which is the
 * correct behavior for an artist-name search.
 */
export function toFts5PrefixQuery(raw: string): string {
  const tokens = raw
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);
  if (tokens.length === 0) return '""'; // matches nothing; caller short-circuits on empty input anyway
  return tokens.map((t) => `"${t.replace(/"/g, '""')}"*`).join(" ");
}
