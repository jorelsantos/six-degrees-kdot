import { beforeEach, describe, expect, it } from "vitest";
import { _resetForTests, checkResolveTrackRateLimit } from "../src/ratelimit";

describe("checkResolveTrackRateLimit", () => {
  beforeEach(() => {
    _resetForTests();
  });

  it("allows requests under the cap", () => {
    for (let i = 0; i < 20; i++) {
      expect(checkResolveTrackRateLimit("1.2.3.4")).toBe(true);
    }
  });

  it("rejects requests once the global cap is exceeded", () => {
    for (let i = 0; i < 20; i++) checkResolveTrackRateLimit("1.2.3.4");
    expect(checkResolveTrackRateLimit("1.2.3.4")).toBe(false);
  });

  it("caps globally, not per-IP (the shared resource is Spotify quota)", () => {
    for (let i = 0; i < 20; i++) checkResolveTrackRateLimit("1.1.1.1");
    // A different IP does not get its own fresh budget.
    expect(checkResolveTrackRateLimit("9.9.9.9")).toBe(false);
  });
});
