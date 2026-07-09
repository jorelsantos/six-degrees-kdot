# Rabbit Hole — Demo Recording Guide

*A shot list + safe-artist list for capturing portfolio stills and a demo video of "Six Degrees of Kendrick Lamar," running locally. Created 2026-07-09.*

> This is a recording guide, not a code plan. Goal: capture a polished demo with **zero surprises on camera** — no initials-only avatars, no "preview unavailable" cards, no spinners in frame.

---

## 1. Bring the app up

```bash
cd /Users/jojo/Documents/projects/six-degrees-kdot
./scripts/run_local_demo.sh      # reseeds local D1, starts Worker :8787 + UI :3000 (~15s)
```

Open **http://localhost:3000**. Ctrl-C in that terminal stops both servers when you're done.

Data baked in: **~2,008 artist photos** and **~1,387 song previews** (top ~2k popular artists). Coverage is deep for famous artists; the long tail is intentionally not baked.

---

## 2. The money shots (what to capture)

1. **The search → reveal.** Type a famous artist, pick the top suggestion. The chain animates in (staggered fade/rise), each artist a large centered photo with a soft photo-glow behind the pill, the "(k)dot score" up top.
2. **A playing preview.** Scroll to a hop and let the Spotify embed play its 30s preview — shows the app is really wired to Spotify, not mocked.
3. **The rabbit hole (the interactive hook).** Click an **intermediate** artist in the chain → it navigates into *their* six-degrees path. Do this 2–3 times to show the "fall down the rabbit hole" loop. (Kendrick and the artist you searched are intentionally not clickable.)
4. **A still of a clean, photo-rich chain** for the portfolio thumbnail.

---

## 3. Bulletproof artists (verified: photos + baked preview)

These searched artists have a real photo and a baked preview on their connecting song, at 2 degrees. Safe to type on camera:

| Search this | Chain | Why it's nice |
|---|---|---|
| **Eric Clapton** | Eric Clapton → Paul McCartney → Kendrick | Rock legends → Kendrick; great "wait, really?" moment |
| **Nicki Minaj** | Nicki Minaj → Rich Gang → Kendrick | Big mainstream name, 2 degrees |
| **Timbaland** | Timbaland → Brandy → Kendrick | Recognizable producer |
| **Swae Lee** | Swae Lee → Pharrell Williams → Kendrick | Two big names in the chain |
| **Juvenile** | Juvenile → The Game → Kendrick | Clean hip-hop chain |
| **Count Basie** | Count Basie → Busta Rhymes → Kendrick | Jazz-era → Kendrick, fun spread |

**Do a 30-second dry run of each before recording** — confirm photos render and the preview plays. Pick your 2–3 favorites for the final cut.

---

## 4. What to avoid on camera

- **Don't search obscure/long-tail artists.** Deep-cut session musicians still show an initials circle (no photo) and often "Preview unavailable." That's by design (only the top ~2k are baked) but it looks unfinished on video. Stick to household names.
- **First view of an un-baked hop shows a brief spinner** while it lazy-resolves a preview, then either an embed or a no-player card. Avoid by sticking to the verified list above (already resolved → instant).
- **Photos are hotlinked** from Deezer/Wikimedia/TheAudioDB CDNs — record with a live internet connection so images load.

---

## 5. Suggested flow for the video (~60–90s)

1. Land on the home page, type **Eric Clapton**, hit the top result → let the chain animate in.
2. Let one preview play for a few seconds.
3. Click **Paul McCartney** → his chain loads (the rabbit hole).
4. From there, click another intermediate artist → one more hop.
5. Back to home, search a second favorite (e.g. **Nicki Minaj**) for variety.
6. End on a clean, photo-rich chain as the closing still.

---

## 6. Optional: pre-warm an exact set

Want specific artists (beyond the list above) to be 100% bulletproof — every hop photo'd and every preview pre-resolved? Give the names and they can be pre-baked with a seeded run so there are zero initials/spinners in frame:

```bash
# resolve photos + previews for a specific set of artist ids, then re-export + reseed
python3 src/photo_prebake.py  --db data/collaboration_network_mb.db --seed-ids <ids>
python3 src/track_prebake.py  --db data/collaboration_network_mb.db --seed-ids <ids>
python3 scripts/export_serving_db.py --db data/collaboration_network_mb.db
./scripts/run_local_demo.sh
```

---

## Notes / caveats
- This is the **local** demo — nothing is deployed. Public deployment (Cloudflare + Vercel) is planned but deferred (see `docs/plans/2026-07-09-001-...` and `-002-...`).
- The inert Spotify-style chrome (sidebar/top bar) is still present; whether to strip it for the portfolio piece is an open design call (plan 002, OQ1).
- The app's design is a deliberate "a feature I'd love to see in Spotify" concept — the footer carries the non-affiliation disclaimer.
