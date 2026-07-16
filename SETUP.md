# NEXARA9 README — Setup (5 minutes)

Everything auto-updates from your GitHub once installed. You only touch it to swap in real project images.

## 1. Create your profile repo
Make a **public** repo named exactly `KARTHIK1749` (same as your username). GitHub shows its README on your profile.

## 2. Add the files
Copy into the repo, keeping this structure:
```
KARTHIK1749/
├── README.md
├── assets/
│   ├── banner.svg          ← animated NEXARA9 hero (done)
│   ├── project-drone.png   ← REPLACE with your drone image
│   ├── project-two.png     ← REPLACE with your 2nd project
│   └── metrics.svg         ← auto-generated, don't edit
└── .github/workflows/
    └── metrics.yml         ← the auto-logger
```

## 3. Turn on auto-logging (the "live data" part)
The stat cards (commits, streak, languages, activity graph, trophies) update **automatically** with no setup — they read your public GitHub in real time.

For the richer `metrics.svg` (lines of code, commit habits, isometric calendar):
1. Create a token: GitHub → Settings → Developer settings → **Fine-grained token** (or classic with `repo` + `read:user` scope).
2. In the `KARTHIK1749` repo → Settings → Secrets and variables → Actions → **New secret**.
3. Name it `METRICS_TOKEN`, paste the token.
4. Go to the **Actions** tab → run "NEXARA9 Metrics" once. Done — it now refreshes every 12 hours.

## 4. Swap in your real images
Drop your drone/car/project screenshots into `assets/` and update the paths + captions in `README.md` under `> deployed`. For your secret company logo, just replace `banner.svg`'s glyph section or add it as another project card.

## Notes
- The banner "9" self-draws, terminal types out, and gold sweeps — animation plays on every page load. GitHub renders animated SVG.
- Everything numeric (stats, streak, languages, activity, lines of code) is pulled from your GitHub. You never edit numbers by hand.
- If a stat card ever shows blank, it's a temporary rate-limit on the free public services — refreshes on its own.
