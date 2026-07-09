// Cloudflare's documented pattern for @cloudflare/vitest-pool-workers: merge
// the generated global Env (worker-configuration.d.ts) into cloudflare:test's
// ProvidedEnv, so `import { env } from "cloudflare:test"` is fully typed.
declare module "cloudflare:test" {
  interface ProvidedEnv extends Env {}
}
