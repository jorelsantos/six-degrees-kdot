import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        wrangler: { configPath: "./wrangler.jsonc" },
        // Keep tests hermetic: force Spotify creds empty in the test env so the
        // suite is deterministic regardless of a local .dev.vars (which the pool
        // otherwise loads). The resolve-track tests cover cached-id, sentinel,
        // unknown-id, and the credentials-absent degrade path — none need real
        // creds, and a developer's local .dev.vars must not flip the last one.
        miniflare: {
          bindings: { SPOTIFY_CLIENT_ID: "", SPOTIFY_CLIENT_SECRET: "" },
        },
      },
    },
  },
});
