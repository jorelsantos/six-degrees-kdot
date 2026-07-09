import { describe, expect, it } from "vitest";
import { disambiguateLabels, toFts5PrefixQuery } from "../src/disambiguate";

describe("disambiguateLabels", () => {
  it("leaves unique names bare", () => {
    const labels = disambiguateLabels([
      { id: "a", name: "Drake", degree: 263, popularity: 0 },
      { id: "b", name: "SZA", degree: 53, popularity: 0 },
    ]);
    expect(labels).toEqual(["Drake", "SZA"]);
  });

  it("qualifies duplicate names with a collab-count", () => {
    const labels = disambiguateLabels([
      { id: "a", name: "The Game", degree: 573, popularity: 0 },
      { id: "b", name: "The Game", degree: 12, popularity: 0 },
    ]);
    expect(labels).toEqual(["The Game · 573 collabs", "The Game · 12 collabs"]);
  });

  it("numbers still-tied candidates (same name AND count) by id order", () => {
    const labels = disambiguateLabels([
      { id: "z-id", name: "Hana", degree: 5, popularity: 0 },
      { id: "a-id", name: "Hana", degree: 5, popularity: 0 },
    ]);
    // a-id sorts before z-id -> a-id gets the bare qualified label, z-id gets "(2)"
    expect(labels).toEqual(["Hana · 5 collabs (2)", "Hana · 5 collabs"]);
  });

  it("collides on the casefolded display form", () => {
    const labels = disambiguateLabels([
      { id: "a", name: "HANA", degree: 3, popularity: 0 },
      { id: "b", name: "Hana", degree: 7, popularity: 0 },
    ]);
    expect(labels[0]).toContain("collabs");
    expect(labels[1]).toContain("collabs");
  });
});

describe("toFts5PrefixQuery", () => {
  it("wraps a simple query as a quoted prefix term", () => {
    expect(toFts5PrefixQuery("drake")).toBe('"drake"*');
  });

  it("splits punctuation into separate tokens instead of erroring", () => {
    // The exact case that would crash a raw FTS5 MATCH: "AC/DC" contains a
    // syntax-significant character.
    expect(toFts5PrefixQuery("AC/DC")).toBe('"ac"* "dc"*');
  });

  it("handles exclamation marks (P!nk)", () => {
    expect(toFts5PrefixQuery("P!nk")).toBe('"p"* "nk"*');
  });

  it("handles ampersands (Florence + the Machine)", () => {
    expect(toFts5PrefixQuery("Florence + the Machine")).toBe('"florence"* "the"* "machine"*');
  });

  it("escapes embedded quotes", () => {
    expect(toFts5PrefixQuery('"quoted"')).toBe('"quoted"*');
  });

  it("returns a never-matching expression for input with no tokens", () => {
    expect(toFts5PrefixQuery("***")).toBe('""');
  });
});
