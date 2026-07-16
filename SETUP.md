# SUJAL NEGI — GitHub Profile README · Setup

Everything auto-updates from your GitHub. You only swap in real project photos.

## Step 1 — Create your profile repo
1. Go to https://github.com/new
2. Repository name: **sujal128005** (exactly your username — this makes it special)
3. Set **Public**, check "Add a README file", click **Create repository**
4. You'll see a note: "sujal128005/sujal128005 is a special repository ✨"

## Step 2 — Upload the WHOLE folder at once (the part that tripped you up)

The GitHub web uploader DOES accept folders — the trick is you must **drag the folder's *contents*, and drag actual folders (not files one by one).**

1. In your repo click **Add file → Upload files**
2. Open the unzipped `sujal-readme` folder on your computer
3. **Select everything inside it** (README.md, SETUP.md, the `assets` folder, the `.github` folder) and **drag them all together** onto the upload box
4. Drag the **folders themselves** — GitHub reads the folder structure and uploads everything inside automatically. You do NOT open each folder.
5. Commit.

### Why yours only uploaded README + setup last time
You dragged loose files. When you drag a **folder icon**, GitHub keeps the path (`assets/banner.svg`). When you drag loose files, nested ones get skipped. So: drag the `assets` and `.github` folders as folders.

### If the browser STILL won't take .github (it hides dotfolders sometimes)
Create that one file by hand:
- **Add file → Create new file**
- In the name box type: `.github/workflows/metrics.yml` (the `/` makes the folders)
- Paste the contents of metrics.yml → Commit

## Step 3 — Turn on live data
- **Instant, no setup:** stats cards, streak, languages, activity graph, trophies — they read your public GitHub the moment the README is live.
- **Rich metrics.svg** (lines of code, commit habits, calendar):
  1. GitHub → Settings → Developer settings → Personal access tokens → generate one with read access to your repos + profile
  2. Your repo → Settings → Secrets and variables → Actions → New repository secret → name it `METRICS_TOKEN`, paste token
  3. Actions tab → run "Metrics" once. It refreshes every 12h after.

## Step 4 — Add your real project photos
Replace `assets/project-navya.png` and `assets/project-navyam.png` with real screenshots/renders (keep the same filenames). Same Upload files flow.

---

## Easiest method overall: Git command line (recommended for an engineer)
This uploads folders perfectly every time — no drag-and-drop guessing:
```bash
git clone https://github.com/sujal128005/sujal128005.git
# copy all the unzipped files INTO that folder
cd sujal128005
git add .
git commit -m "Autonomous systems profile"
git push
```
Done. Everything, folders included, in one push.
