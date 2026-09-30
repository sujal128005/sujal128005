#!/usr/bin/env python3
"""
Profile builder for github.com/sujal128005
==========================================

Regenerates the whole profile README from two live sources:

  1. The portfolio (sujalnegi.tech)  -> copy, projects, proof, crew, playbook,
                                        workbench, contact, colours, portrait
  2. The GitHub API                  -> repo telemetry per project, contribution
                                        calendar, languages, recent pushes

So when the portfolio changes, or a repo gets a new commit, the profile follows
on the next run. Standard library only (no pip install). Every source is cached
in data/, so a failed fetch keeps the last good version instead of breaking.

Run locally:   python scripts/build_profile.py            (uses GH_TOKEN if set)
               python scripts/build_profile.py --offline  (cache only, no network)
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "profile.config.json").read_text(encoding="utf-8"))
OUT = ROOT / "assets" / "generated"
DATA = ROOT / "data"
FONTS = json.loads((ROOT / "assets" / "fonts" / "archivo.json").read_text())
METRICS = json.loads((ROOT / "assets" / "fonts" / "metrics.json").read_text())
OFFLINE = "--offline" in sys.argv
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
USER = os.environ.get("GH_USER") or CFG["user"]
TZ = dt.timezone(dt.timedelta(minutes=CFG.get("utc_offset_minutes", 330)))
NOW = dt.datetime.now(TZ)

# Portfolio palette. Overwritten by the :root variables read from the live site.
C = {
    "frame": "#D5D9D1", "paper": "#ECEEEA", "sheet": "#F7F8F5", "ink": "#17202E",
    "ink-2": "#2A3850", "graphite": "#4E5866", "rule": "#C5CAD0", "hivis": "#FFC61A",
    "link": "#1F4FD1", "ok": "#1C7A4B", "on-ink": "#ECEEEA", "on-ink-dim": "#B3BBC6",
    "ink-rule": "#3A4557", "up": "#3CCB7F",
}

W = 1000          # canvas width of every full-width plate
M = 14            # frame margin around the sheet
SH = 6            # hard offset shadow, same as the portfolio's cards
PAD = 46          # padding inside a sheet


# ─────────────────────────────────────────────────────────────── network ──

def http(url: str, *, token: str = "", data: bytes | None = None, accept: str = "",
         tries: int = 3) -> tuple[int, dict, bytes]:
    if OFFLINE:
        raise RuntimeError("offline")
    headers = {"User-Agent": f"{USER}-profile-builder"}
    if accept:
        headers["Accept"] = accept
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 409, 451):
                return e.code, dict(e.headers), b""
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def cache_load(name: str) -> dict:
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def cache_save(name: str, obj: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def log(msg: str) -> None:
    print(f"[profile] {msg}", flush=True)


# ─────────────────────────────────────────────────── portfolio parsing ──

def strip(frag: str) -> str:
    s = re.sub(r"<[^>]+>", "", frag or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def to_md(frag: str, base: str) -> str:
    """HTML fragment -> GitHub markdown (bold, italics, links)."""
    s = frag or ""
    s = re.sub(r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>",
               lambda m: f"[{strip(m.group(2))}]({urllib.parse.urljoin(base, m.group(1))})", s, flags=re.S)
    s = re.sub(r"</?(b|strong)>", "**", s)
    s = re.sub(r"</?(em|i)>", "*", s)
    return strip(s)


def to_runs(frag: str) -> list[tuple[str, str]]:
    """HTML fragment -> [(word, style)] with style n=normal, b=bold, a=accent."""
    s = frag or ""
    s = re.sub(r"<(b|strong)\b[^>]*>", "\x01", s)
    s = re.sub(r"</(b|strong)>", "\x02", s)
    s = re.sub(r"<(em|i)\b[^>]*>", "\x03", s)
    s = re.sub(r"</(em|i)>", "\x04", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    out, style, word = [], "n", ""
    def push():
        nonlocal word
        if word:
            out.append((word, style))
            word = ""
    for ch in s:
        if ch in "\x01\x03":
            push(); style = "b" if ch == "\x01" else "a"
        elif ch in "\x02\x04":
            push(); style = "n"
        elif ch.isspace():
            push(); out.append((" ", "n"))
        else:
            word += ch
    push()
    # collapse spaces, drop leading/trailing
    res: list[tuple[str, str]] = []
    for w, st in out:
        if w == " ":
            if res and res[-1][0] != " ":
                res.append((" ", "n"))
        else:
            res.append((w, st))
    while res and res[-1][0] == " ":
        res.pop()
    return res


def plain_runs(text: str) -> list[tuple[str, str]]:
    return to_runs(html.escape(text))


def grab(block: str, pat: str, default: str = "") -> str:
    m = re.search(pat, block or "", re.S)
    return m.group(1) if m else default


def sections(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r"<section\b([^>]*)>(.*?)</section>", page, re.S):
        attrs, body = m.group(1), m.group(2)
        out.append({
            "id": grab(attrs, r'id="([^"]+)"'),
            "cls": grab(attrs, r'class="([^"]+)"'),
            "title": html.unescape(grab(attrs, r'data-title="([^"]+)"')),
            "body": body,
        })
    return out


def parse_portfolio(page: str, base: str) -> dict:
    secs = sections(page)
    total = len(secs)
    P: dict = {"total": total, "base": base}

    # palette
    root = grab(page, r":root\{(.*?)\}")
    P["palette"] = {k: v for k, v in re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{3,8})", root)}

    def find(pred):
        for i, s in enumerate(secs):
            if pred(s):
                return i, s
        return None, None

    # cover
    i, s = find(lambda s: 'class="board"' in s["body"] or "cover" in s["id"])
    if s:
        b = s["body"]
        rows = []
        for r in re.finditer(r'<a class="row"([^>]*)>(.*?)</a>', b, re.S):
            a, inner = r.group(1), r.group(2)
            nm = grab(inner, r'<span class="nm">(.*?)<span class="ds">')
            rows.append({
                "anchor": grab(a, r'href="#([^"]+)"'),
                "state": grab(a, r'data-s="([^"]+)"'),
                "ping": grab(a, r'data-ping="([^"]+)"'),
                "name": strip(nm),
                "desc": strip(grab(inner, r'<span class="ds">(.*?)</span>')),
                "status": strip(grab(inner, r'<span class="st">(.*?)</span>')),
            })
        P["cover"] = {
            "index": i + 1,
            "who": strip(grab(b, r'<p class="who">(.*?)</p>')),
            "name": [strip(x) for x in re.findall(r"<span>(.*?)</span>", grab(b, r"<h1>(.*?)</h1>"))]
                    or [strip(grab(b, r"<h1>(.*?)</h1>"))],
            "claim": [strip(x) for x in re.findall(r"<span>(.*?)</span>", grab(b, r'<p class="claim">(.*?)</p>'))],
            "sub": strip(grab(b, r'<p class="sub">(.*?)</p>')),
            "board_title": strip(grab(b, r'<div class="board".*?<b[^>]*>(.*?)</b>')),
            "board": rows,
            "board_note": strip(grab(b, r'<div class="board".*?<footer>(.*?)</footer>')),
        }

    # about
    i, s = find(lambda s: 'class="about"' in s["body"])
    if s:
        b = s["body"]
        img = grab(b, r'<figure class="portrait"><img[^>]*src="([^"]+)"')
        P["about"] = {
            "index": i + 1,
            "title": strip(grab(b, r"<h2>(.*?)</h2>")),
            "paras": re.findall(r"<p>(.*?)</p>", grab(b, r'<div class="about-copy">(.*?)</div>'), re.S),
            "facts": [(strip(dt_), dd) for dt_, dd in re.findall(r"<dt>(.*?)</dt><dd>(.*?)</dd>", b, re.S)],
            "portrait_src": img,
        }

    # projects
    projects = []
    for i, s in enumerate(secs):
        b = s["body"]
        if 'class="split prod"' not in b and 'class="what"' not in b:
            continue
        meta = grab(b, r'<div class="meta">(.*?)</div>')
        stage_cls = grab(meta, r'<span class="(stage[^"]*)"')
        spans = re.findall(r"<span([^>]*)>(.*?)</span>", meta, re.S)
        dates = next((strip(t) for a, t in spans if "class" not in a), "")
        flag = next((strip(t) for a, t in spans if "flag" in a), "")
        links = []
        for a in re.finditer(r'<a class="btn ([a-z]+)"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                             grab(b, r'<div class="links">(.*?)</div>'), re.S):
            links.append({"kind": a.group(1), "href": urllib.parse.urljoin(base, a.group(2)),
                          "label": strip(a.group(3))})
        repos = []
        for l in links:
            m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)", l["href"])
            if m:
                repos.append(f"{m.group(1)}/{m.group(2)}")
        projects.append({
            "slug": (s["id"] or s["title"]).replace("s-", "", 1).lower(),
            "index": i + 1,
            "name": strip(grab(b, r"<h2>(.*?)</h2>")),
            "what": strip(grab(b, r'<p class="what">(.*?)</p>')),
            "stage": strip(grab(meta, r'<span class="stage[^"]*">(.*?)</span>')),
            "live": "build" not in stage_cls,
            "dates": dates,
            "flag": flag,
            "links": links,
            "repos": repos,
            "bullets": re.findall(r"<li>(.*?)</li>", grab(b, r'<ul class="pts">(.*?)</ul>'), re.S),
            "stack": strip(grab(b, r'<p class="stack">(.*?)</p>')),
            "anchor": s["id"],
        })
    P["projects"] = projects

    # proof / traction
    i, s = find(lambda s: 'class="score"' in s["body"])
    if s:
        b = s["body"]
        head = grab(b, r'<div class="trac-head">(.*?)</div>\s*<div class="score">')
        P["proof"] = {
            "index": i + 1,
            "yr": strip(grab(head, r'<p class="yr">(.*?)</p>')),
            "title": strip(grab(head, r"<h2>(.*?)</h2>")),
            "text": strip(grab(head, r"</div>\s*<p>(.*?)</p>")),
            "score": [(strip(x), strip(y)) for x, y in
                      re.findall(r"<div><b>(.*?)</b><span>(.*?)</span></div>", grab(b, r'<div class="score">(.*?)</div>\s*<div class="more">'), re.S)],
            "more": [(strip(y), strip(h), strip(p)) for y, h, p in
                     re.findall(r'<div><p class="yr">(.*?)</p><h3>(.*?)</h3><p>(.*?)</p></div>', grab(b, r'<div class="more">(.*)'), re.S)],
        }

    # crew
    i, s = find(lambda s: 'class="log"' in s["body"])
    if s:
        b = s["body"]
        P["crew"] = {
            "index": i + 1,
            "title": strip(grab(b, r"<h2>(.*?)</h2>")),
            "lede": strip(grab(b, r'<p class="lede">(.*?)</p>')),
            "items": [(strip(t), strip(h), strip(r), p) for t, h, r, p in re.findall(
                r'<li><time>(.*?)</time><div><h3>(.*?)</h3><p class="role">(.*?)</p><p>(.*?)</p></div></li>', b, re.S)],
        }

    # playbook
    i, s = find(lambda s: 'class="rules"' in s["body"])
    if s:
        b = s["body"]
        P["playbook"] = {
            "index": i + 1,
            "title": strip(grab(b, r"<h2>(.*?)</h2>")),
            "lede": strip(grab(b, r'<p class="lede">(.*?)</p>')),
            "rules": [(strip(h), p) for h, p in re.findall(r'<div class="rule"><h3>(.*?)</h3><p>(.*?)</p></div>', b, re.S)],
        }

    # workbench
    i, s = find(lambda s: 'class="kit"' in s["body"])
    if s:
        b = s["body"]
        P["toolkit"] = {
            "index": i + 1,
            "title": strip(grab(b, r"<h2>(.*?)</h2>")),
            "lede": strip(grab(b, r'<p class="lede">(.*?)</p>')),
            "rows": [(strip(h), strip(d)) for h, d in re.findall(r'<tr><th[^>]*>(.*?)</th><td>(.*?)</td></tr>', b, re.S)],
        }

    # contact
    i, s = find(lambda s: 'class="titleblock"' in s["body"] or "contact" in s["cls"])
    if s:
        b = s["body"]
        P["contact"] = {
            "index": i + 1,
            "title": strip(grab(b, r"<h2>(.*?)</h2>")),
            "lede": strip(grab(b, r'<p class="lede">(.*?)</p>')),
            "reach": [{"kind": k, "href": urllib.parse.urljoin(base, h), "label": strip(t)} for k, h, t in
                      re.findall(r'<a class="btn ([a-z]+)" href="([^"]+)"[^>]*>(.*?)</a>', grab(b, r'<div class="reach">(.*?)</div>'), re.S)],
            "titleblock": [(strip(k), strip(v)) for k, v in re.findall(
                r"<div><span>(.*?)</span>(?:<b>|<a[^>]*>)(.*?)(?:</b>|</a>)</div>", grab(b, r'<div class="titleblock"[^>]*>(.*?</div>)\s*</div>'), re.S)],
        }
    return P


def load_portfolio() -> dict:
    cached = cache_load("portfolio.json")
    for src in CFG["portfolio_sources"]:
        try:
            status, _, body = http(src)
            if status != 200:
                continue
            page = body.decode("utf-8", "replace")
            fresh = parse_portfolio(page, CFG["portfolio_url"])
            if not fresh.get("projects"):
                log(f"{src}: parsed no projects, skipping")
                continue
            # keep any section the new markup no longer yields
            for k, v in cached.items():
                if k not in fresh or not fresh[k]:
                    fresh[k] = v
            fresh["source"] = src
            # portrait is embedded, so fetch it once per change
            fresh["portrait_data"] = cached.get("portrait_data", "")
            rel = fresh.get("about", {}).get("portrait_src")
            if rel and CFG.get("embed_portrait", True):
                for base in (src, CFG["portfolio_url"]):
                    try:
                        st, hd, img = http(urllib.parse.urljoin(base, rel), tries=1)
                        if st == 200 and len(img) < 400_000:
                            ctype = hd.get("Content-Type", "image/jpeg").split(";")[0]
                            if not ctype.startswith("image/"):
                                ctype = "image/jpeg"
                            fresh["portrait_data"] = f"data:{ctype};base64," + base64.b64encode(img).decode()
                            break
                    except Exception as e:  # noqa: BLE001
                        log(f"portrait: {e}")
            cache_save("portfolio.json", fresh)
            log(f"portfolio synced from {src}: {len(fresh['projects'])} projects")
            return fresh
        except Exception as e:  # noqa: BLE001
            log(f"portfolio source failed ({src}): {e}")
    if not cached:
        sys.exit("No portfolio data available and no cache in data/portfolio.json")
    log("using cached portfolio snapshot")
    return cached


# ───────────────────────────────────────────────────────── github data ──

API = "https://api.github.com"


def gh(path: str) -> tuple[object, dict]:
    status, headers, body = http(API + path, token=TOKEN, accept="application/vnd.github+json")
    if status in (404, 409, 451):
        return None, headers
    return (json.loads(body) if body else None), headers


def gh_graphql(query: str, variables: dict) -> dict | None:
    if not TOKEN:
        return None
    status, _, body = http(API + "/graphql", token=TOKEN,
                           data=json.dumps({"query": query, "variables": variables}).encode())
    j = json.loads(body) if body else {}
    if j.get("errors"):
        log(f"graphql: {j['errors'][0].get('message')}")
    return j.get("data")


def commit_count(full: str) -> tuple[int, dict | None]:
    data, headers = gh(f"/repos/{full}/commits?per_page=1")
    if not data:
        return 0, None
    link = headers.get("Link") or headers.get("link") or ""
    m = re.search(r'[?&]page=(\d+)>; rel="last"', link)
    n = int(m.group(1)) if m else len(data)
    c = data[0]
    latest = {
        "sha": c["sha"][:7],
        "message": (c["commit"]["message"] or "").splitlines()[0][:140],
        "date": c["commit"]["committer"]["date"] or c["commit"]["author"]["date"],
        "url": c.get("html_url", ""),
    }
    return n, latest


def participation(full: str) -> list[int]:
    for _ in range(5):
        status, _, body = http(f"{API}/repos/{full}/stats/participation", token=TOKEN,
                               accept="application/vnd.github+json")
        if status == 200 and body:
            return (json.loads(body).get("all") or [])[-12:]
        time.sleep(3)  # 202 = GitHub is still computing
    return []


def repo_stats(full: str) -> dict:
    r, _ = gh(f"/repos/{full}")
    if not r:
        return {"full": full, "private": True}
    n, latest = commit_count(full)
    langs, _ = gh(f"/repos/{full}/languages")
    return {
        "full": r["full_name"], "url": r["html_url"], "private": False,
        "description": r.get("description") or "", "homepage": r.get("homepage") or "",
        "stars": r["stargazers_count"], "forks": r["forks_count"], "issues": r["open_issues_count"],
        "language": r.get("language") or "", "pushed_at": r["pushed_at"], "created_at": r["created_at"],
        "commits": n, "latest": latest, "weekly": participation(full),
        "languages": langs or {}, "topics": r.get("topics") or [],
    }


CAL_Q = """
query($login:String!){ user(login:$login){
  followers{totalCount}
  contributionsCollection{
    totalCommitContributions totalPullRequestContributions totalIssueContributions
    totalPullRequestReviewContributions restrictedContributionsCount
    contributionCalendar{ totalContributions weeks{ contributionDays{ date contributionCount weekday } } }
  }
}}"""


def streaks(days: list[dict]) -> tuple[int, int]:
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    cur = 0
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1  # today not counted yet
    while i >= 0 and counts[i]:
        cur += 1
        i -= 1
    return cur, longest


def load_github(portfolio: dict) -> dict:
    cached = cache_load("github.json")
    if OFFLINE:
        return cached
    try:
        user, _ = gh(f"/users/{USER}")
        repos, _ = gh(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed")
        repos = [r for r in (repos or []) if not r.get("private")]
        own = [r for r in repos if not r["fork"]]

        featured = {}
        for p in portfolio["projects"]:
            for full in p["repos"]:
                if full not in featured:
                    featured[full] = repo_stats(full)
                    log(f"repo {full}: {featured[full].get('commits', 'private')} commits")

        # languages across own repos (bytes)
        ignore = set(CFG.get("language_ignore", []))
        lang_total: dict[str, int] = {}
        for r in own[: CFG.get("language_repo_limit", 40)]:
            full = r["full_name"]
            langs = featured.get(full, {}).get("languages")
            if langs is None:
                langs, _ = gh(f"/repos/{full}/languages")
            for k, v in (langs or {}).items():
                if k not in ignore:
                    lang_total[k] = lang_total.get(k, 0) + v

        # recent pushes: latest commit per recently pushed repo
        skip = {s.lower() for s in CFG.get("exclude_repos", [])} | {USER.lower()}
        recent = []
        for r in own:
            if r["name"].lower() in skip or len(recent) >= CFG.get("recent_limit", 6):
                continue
            full = r["full_name"]
            st = featured.get(full)
            if st and st.get("latest"):
                latest, n = st["latest"], st["commits"]
            else:
                n, latest = commit_count(full)
            if latest:
                recent.append({"name": r["name"], "full": full, "url": r["html_url"],
                               "commits": n, "latest": latest, "pushed_at": r["pushed_at"]})

        feat_names = {f.lower() for f in featured}
        bench = [{
            "name": r["name"], "url": r["html_url"], "description": r.get("description") or "",
            "language": r.get("language") or "", "stars": r["stargazers_count"],
            "homepage": r.get("homepage") or "", "pushed_at": r["pushed_at"], "archived": r.get("archived", False),
        } for r in own if r["full_name"].lower() not in feat_names and r["name"].lower() not in skip]

        cal = gh_graphql(CAL_Q, {"login": USER}) or {}
        cc = ((cal.get("user") or {}).get("contributionsCollection")) or {}
        days = [d for w in cc.get("contributionCalendar", {}).get("weeks", []) for d in w["contributionDays"]]
        cur, longest = streaks(days) if days else (0, 0)

        data = {
            "fetched_at": NOW.isoformat(timespec="minutes"),
            "user": {"login": USER, "followers": (user or {}).get("followers", 0),
                     "public_repos": (user or {}).get("public_repos", len(repos)),
                     "created_at": (user or {}).get("created_at", "")},
            "stars": sum(r["stargazers_count"] for r in own),
            "featured": featured,
            "languages": sorted(lang_total.items(), key=lambda kv: -kv[1]),
            "recent": recent,
            "bench": bench[: CFG.get("bench_limit", 8)],
            "calendar": {
                "total": cc.get("contributionCalendar", {}).get("totalContributions"),
                "commits": cc.get("totalCommitContributions"),
                "prs": cc.get("totalPullRequestContributions"),
                "issues": cc.get("totalIssueContributions"),
                "reviews": cc.get("totalPullRequestReviewContributions"),
                "private": cc.get("restrictedContributionsCount"),
                "streak": cur, "longest": longest,
                "days": [[d["date"], d["contributionCount"]] for d in days],
            } if days else cached.get("calendar"),
        }
        cache_save("github.json", data)
        return data
    except Exception as e:  # noqa: BLE001
        log(f"GitHub fetch failed, keeping cache: {e}")
        return cached


# ──────────────────────────────────────────────────────────── svg kit ──

FAMILY = {
    "AK": "'SN-AK','Archivo Black','Arial Black',sans-serif",
    "AW": "'SN-AW','Archivo','Arial',sans-serif",
    "AB": "'SN-AB','Archivo','Arial',sans-serif",
    "AT": "'SN-AT','Archivo','Arial',sans-serif",
}
WEIGHT = {"AK": 900, "AW": 800, "AB": 700, "AT": 500}


def font_css(used: set[str]) -> str:
    return "".join(
        f"@font-face{{font-family:'SN-{k}';src:url(data:font/woff2;base64,{FONTS[k]}) format('woff2');font-weight:{WEIGHT[k]}}}"
        for k in sorted(used))


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def mw(s: str, font: str, size: float) -> float:
    m = METRICS[font]
    return sum(m.get(ch, 0.56) for ch in s) * size


def fit(s: str, font: str, size: float, maxw: float) -> str:
    if mw(s, font, size) <= maxw:
        return s
    while s and mw(s + "…", font, size) > maxw:
        s = s[:-1]
    return s.rstrip() + "…"


def words_of(runs: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Group tokens into words. A word can mix styles, e.g. '**days**.' stays glued."""
    words: list[list[tuple[str, str]]] = [[]]
    for t, st in runs:
        if t == " ":
            if words[-1]:
                words.append([])
        else:
            words[-1].append((t, st))
    return [w for w in words if w]


def word_w(word: list[tuple[str, str]], size: float, fn: str, fb: str) -> float:
    return sum(mw(t, fn if st == "n" else fb, size) for t, st in word)


def wrap(runs: list[tuple[str, str]], maxw: float, size: float, fn: str = "AT", fb: str = "AB") -> list[list[list[tuple[str, str]]]]:
    """Returns lines; each line is a list of words; each word a list of (text, style)."""
    lines: list[list] = [[]]
    width = 0.0
    space = mw(" ", fn, size)
    for word in words_of(runs):
        ww = word_w(word, size, fn, fb)
        if lines[-1] and width + space + ww > maxw:
            lines.append([])
            width = 0.0
        if lines[-1]:
            width += space
        lines[-1].append(word)
        width += ww
    return [l for l in lines if l]


def line_text(line) -> str:
    return " ".join("".join(t for t, _ in w) for w in line)


class Svg:
    def __init__(self, title: str):
        self.title = title
        self.parts: list[str] = []
        self.used: set[str] = set()
        self.css = ""

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x, y, s, size, font="AT", fill=None, anchor="start", extra="") -> None:
        self.used.add(font)
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FAMILY[font]}" font-weight="{WEIGHT[font]}" '
                 f'font-size="{size}" fill="{fill or C["ink"]}"{a}{extra}>{esc(s)}</text>')

    def runs(self, x, y, line, size, fn="AT", fb="AB", fill=None, bold_fill=None, accent_fill=None, extra="") -> None:
        self.used.update({fn, fb})
        segs: list[tuple[str, str]] = []
        for i, word in enumerate(line):
            for j, (t, st) in enumerate(word):
                t = (" " if i and j == 0 else "") + t
                if segs and segs[-1][1] == st:
                    segs[-1] = (segs[-1][0] + t, st)
                else:
                    segs.append((t, st))
        spans = []
        for t, st in segs:
            f = fn if st == "n" else fb
            col = fill if st == "n" else (bold_fill if st == "b" else accent_fill)
            spans.append(f'<tspan font-family="{FAMILY[f]}" font-weight="{WEIGHT[f]}" fill="{col}">{esc(t)}</tspan>')
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" xml:space="preserve"{extra}>{"".join(spans)}</text>')

    def para(self, x, y, runs, maxw, size, lh, **kw) -> float:
        """Draw wrapped rich text with first baseline at y. Returns the y after the block."""
        lines = wrap(runs, maxw, size, kw.get("fn", "AT"), kw.get("fb", "AB"))
        for i, line in enumerate(lines):
            self.runs(x, y + i * lh, line, size, **kw)
        return y + (len(lines) - 1) * lh if lines else y - lh

    def render(self, w: int, h: int) -> str:
        style = font_css(self.used) + "text{text-rendering:geometricPrecision}" + self.css + "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
                f'role="img" aria-label="{esc(self.title)}"><title>{esc(self.title)}</title>'
                f"<style>{style}</style>{''.join(self.parts)}</svg>")


def plate(svg: Svg, h: float, kind: str = "sheet", w: int = W) -> tuple[float, float, float, float]:
    """Frame + sheet with the portfolio's 2px ink border and hard offset shadow."""
    fill = {"sheet": C["sheet"], "paper": C["paper"], "ink": C["ink"], "hivis": C["hivis"]}[kind]
    shadow = C["hivis"] if kind == "ink" else C["ink"]
    x0, y0 = M, M
    sw, shh = w - 2 * M - SH, h - 2 * M - SH
    svg.parts.insert(0,
        f'<rect width="{w}" height="{h}" rx="16" fill="{C["frame"]}"/>'
        f'<rect x="{x0 + SH}" y="{y0 + SH}" width="{sw}" height="{shh}" rx="10" fill="{shadow}"/>'
        f'<rect x="{x0 + 1}" y="{y0 + 1}" width="{sw - 2}" height="{shh - 2}" rx="10" fill="{fill}" stroke="{C["ink"]}" stroke-width="2"/>')
    return x0, y0, x0 + sw, y0 + shh


def deck_count(svg: Svg, x_right: float, y: float, index: int, total: int, on_ink=False) -> None:
    dim = C["on-ink-dim"] if on_ink else C["graphite"]
    strong = C["on-ink"] if on_ink else C["ink"]
    svg.used.add("AB")
    svg.add(f'<text x="{x_right:.1f}" y="{y:.1f}" text-anchor="end" font-size="14" font-family="{FAMILY["AB"]}" '
            f'font-weight="700" fill="{dim}"><tspan fill="{strong}">{index:02d}</tspan> / {total:02d}</text>')


def logo(svg: Svg, x: float, y: float, size: float) -> None:
    s = size / 64
    svg.add(f'<g transform="translate({x},{y}) scale({s:.4f})"><rect width="64" height="64" rx="15" fill="{C["ink"]}"/>'
            f'<path d="M45 17H27.5a7.5 7.5 0 0 0 0 15h9a7.5 7.5 0 0 1 0 15H19" fill="none" stroke="{C["hivis"]}" stroke-width="10"/>'
            f'<path d="M45 17H27.5a7.5 7.5 0 0 0 0 15h9a7.5 7.5 0 0 1 0 15H19" fill="none" stroke="{C["ink"]}" stroke-width="2.6"/>'
            f'<circle cx="46.5" cy="17" r="5" fill="{C["paper"]}"/></g>')


def halo(cx: float, cy: float, col: str, r0: float, r1: float) -> str:
    """Pulsing ring, SMIL so it animates in every browser that renders GitHub images."""
    return (f'<circle cx="{cx}" cy="{cy}" r="{r0}" fill="none" stroke="{col}" stroke-width="1.5">'
            f'<animate attributeName="r" values="{r0};{r1}" dur="1.8s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values=".7;0" dur="1.8s" repeatCount="indefinite"/></circle>')


def ago(iso: str) -> str:
    if not iso:
        return ""
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    d = NOW - t.astimezone(TZ)
    s = d.total_seconds()
    if s < 3600:
        return f"{max(1, int(s // 60))} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    if d.days < 30:
        return f"{d.days} d ago"
    if d.days < 365:
        return f"{d.days // 30} mo ago"
    return f"{d.days // 365} y ago"


def fmt_n(n) -> str:
    if n is None:
        return "–"
    n = int(n)
    return f"{n / 1000:.1f}k" if n >= 10000 else f"{n:,}"


def heading(svg: Svg, x: float, y: float, title: str, size: float, maxw: float, fill: str) -> float:
    lines = wrap(plain_runs(title), maxw, size, "AW", "AW")
    for i, line in enumerate(lines):
        svg.text(x, y + i * size * 1.0, line_text(line), size, "AW", fill,
                 extra=' letter-spacing="-0.5"')
    return y + (len(lines) - 1) * size * 1.0


# ─────────────────────────────────────────────────────────── plates ──

def svg_banner(P: dict, G: dict) -> str:
    cv = P["cover"]
    svg = Svg(f"{' '.join(cv['name'])}. {' '.join(cv['claim'])}")
    total = P["total"]
    x0, y0 = M, M
    L = x0 + PAD
    top = y0 + 40
    logo(svg, L, top - 24, 30)
    svg.text(L + 42, top - 3, CFG.get("portfolio_label", "sujalnegi.tech"), 15, "AW", C["on-ink"])
    # left column
    y = top + 46
    svg.text(L, y, cv["who"], 15, "AT", C["on-ink-dim"])
    y += 12
    size = 104
    for i, part in enumerate(cv["name"]):
        y += size * 0.86
        svg.text(L - 4, y, part, size, "AK", C["on-ink"], extra=' letter-spacing="-3.6"')
    y += 20
    for part in cv["claim"]:
        y += 31
        svg.text(L, y, part, 26, "AW", C["hivis"])
    y += 34
    y = svg.para(L, y, plain_runs(cv["sub"]), 460, 15.5, 23, fill=C["on-ink-dim"], bold_fill=C["on-ink"])
    left_bottom = y

    # right column: "Running right now" board, synced from the portfolio
    bx = 566
    bw = W - M - SH - PAD - bx + 6
    by = top + 36
    rows = cv["board"]
    rh = 64
    head_h = 50
    note_lines = wrap(plain_runs(CFG.get("board_note") or cv["board_note"]), bw - 36, 12.5)
    sync = G.get("fetched_at") or NOW.isoformat()
    foot_h = 22 + 17 * len(note_lines) + 18
    bh = head_h + rh * len(rows) + foot_h
    svg.add(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8" fill="none" stroke="{C["ink-rule"]}" stroke-width="1.5"/>')
    svg.text(bx + 18, by + 31, cv["board_title"] or "Running right now", 16.5, "AW", C["on-ink"])
    svg.text(bx + bw - 18, by + 31, "synced from the deck", 12.5, "AT", C["on-ink-dim"], anchor="end")
    svg.add(f'<line x1="{bx}" x2="{bx + bw}" y1="{by + head_h}" y2="{by + head_h}" stroke="{C["ink-rule"]}" stroke-width="1.5"/>')
    svg.css += ("@keyframes rin{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:none}}"
                ".r{opacity:0;animation:rin .7s cubic-bezier(.22,.8,.26,1) forwards}"
                "@keyframes blink{50%{opacity:.25}}.bl{animation:blink 1.2s steps(2) infinite}")
    for i, r in enumerate(rows):
        ry = by + head_h + i * rh
        live = r["state"] not in ("dev", "build")
        dot = C["up"] if live else C["hivis"]
        g = [f'<g class="r" style="animation-delay:{0.35 + i * 0.18:.2f}s">']
        if i:
            g.append(f'<line x1="{bx}" x2="{bx + bw}" y1="{ry}" y2="{ry}" stroke="{C["ink-rule"]}" stroke-width="1"/>')
        cy = ry + rh / 2
        if live:
            g.append(halo(bx + 24, cy, dot, 5, 15))
        g.append(f'<circle cx="{bx + 24}" cy="{cy}" r="5" fill="{dot}"/>')
        svg.parts.append("".join(g))
        svg.text(bx + 42, cy - 3, r["name"], 17, "AW", C["on-ink"])
        svg.text(bx + 42, cy + 16, fit(r["desc"], "AT", 13, bw - 42 - 118), 13, "AT", C["on-ink-dim"])
        svg.text(bx + bw - 18, cy + 5, r["status"], 13, "AB", C["up"] if live else C["on-ink"], anchor="end")
        svg.add("</g>")
    fy = by + head_h + rh * len(rows)
    svg.add(f'<line x1="{bx}" x2="{bx + bw}" y1="{fy}" y2="{fy}" stroke="{C["ink-rule"]}" stroke-width="1.5"/>')
    for i, line in enumerate(note_lines):
        svg.runs(bx + 18, fy + 24 + i * 17, line, 12.5, fill=C["on-ink-dim"], bold_fill=C["on-ink"])
    right_bottom = by + bh

    h = int(max(left_bottom, right_bottom) + PAD + 4 + SH + M)
    # blueprint grid + registration ticks on the ink sheet
    grid = [f'<g stroke="{C["ink-rule"]}" stroke-width="0.6" opacity="0.45">']
    for gx in range(int(x0) + 40, W - M - SH, 40):
        grid.append(f'<line x1="{gx}" x2="{gx}" y1="{y0 + 2}" y2="{h - M - SH - 2}"/>')
    for gy in range(int(y0) + 40, h - M - SH, 40):
        grid.append(f'<line x1="{x0 + 2}" x2="{W - M - SH - 2}" y1="{gy}" y2="{gy}"/>')
    grid.append("</g>")
    svg.parts[0:0] = grid
    deck_count(svg, W - M - SH - PAD + 6, top - 3, cv["index"], total, on_ink=True)
    plate(svg, h, "ink")
    return svg.render(W, h)


def svg_about(P: dict) -> str:
    a = P["about"]
    svg = Svg(a["title"])
    L = M + PAD
    has_img = bool(P.get("portrait_data"))
    img_w = 210 if has_img else 0
    tx = L + (img_w + 36 if has_img else 0)
    tw = W - M - SH - PAD - tx
    y = M + PAD + 36
    deck_count(svg, W - M - SH - PAD, M + PAD + 2, a["index"], P["total"])
    y = heading(svg, tx, y, a["title"], 44, tw - 60, C["ink"])
    y += 14
    for p in a["paras"]:
        y += 36
        y = svg.para(tx, y, to_runs(p), tw, 16.5, 25, fill=C["graphite"], bold_fill=C["ink"], accent_fill=C["ink"])
    text_bottom = y
    if has_img:
        ih = int(img_w * 1132 / 711)
        iy = M + PAD
        svg.add(f'<clipPath id="pc"><rect x="{L}" y="{iy}" width="{img_w}" height="{ih}" rx="8"/></clipPath>'
                f'<image href="{P["portrait_data"]}" x="{L}" y="{iy}" width="{img_w}" height="{ih}" '
                f'preserveAspectRatio="xMidYMid slice" clip-path="url(#pc)"/>'
                f'<rect x="{L}" y="{iy}" width="{img_w}" height="{ih}" rx="8" fill="none" stroke="{C["ink"]}" stroke-width="2"/>')
        text_bottom = max(text_bottom, iy + ih - 20)
    # facts as a two-column definition list, full width
    y = text_bottom + 40
    svg.add(f'<line x1="{L}" x2="{W - M - SH - PAD}" y1="{y}" y2="{y}" stroke="{C["ink"]}" stroke-width="1.5"/>')
    colw = (W - M - SH - PAD - L - 28) / 2
    col_y = [y, y]
    for i, (k, v) in enumerate(a["facts"]):
        c = i % 2 if len(a["facts"]) > 3 else 0
        cx = L + c * (colw + 28)
        cy = col_y[c] + 26
        svg.text(cx, cy, k, 12.5, "AB", C["graphite"])
        end = svg.para(cx, cy + 22, to_runs(v), colw, 15.5, 21, fn="AB", fb="AB", fill=C["ink"],
                       bold_fill=C["ink"], accent_fill=C["ink"])
        col_y[c] = end + 16
        svg.add(f'<line x1="{cx}" x2="{cx + colw}" y1="{col_y[c]}" y2="{col_y[c]}" stroke="{C["rule"]}" stroke-width="1"/>')
    h = int(max(col_y) + PAD - 10 + SH + M)
    plate(svg, h, "paper")
    return svg.render(W, h)


def telemetry_panel(svg: Svg, x: float, y: float, w: float, p: dict, G: dict) -> float:
    """Ink panel with live repo data. Returns bottom y."""
    stats = [G.get("featured", {}).get(r) for r in p["repos"]]
    stats = [s for s in stats if s]
    parts_start = len(svg.parts)
    cy = y + 30
    svg.text(x + 20, cy, "Repo telemetry", 15, "AW", C["on-ink"])
    svg.text(x + w - 20, cy, "live from GitHub" if stats else "", 11.5, "AT", C["on-ink-dim"], anchor="end")
    cy += 16
    svg.add(f'<line x1="{x}" x2="{x + w}" y1="{cy}" y2="{cy}" stroke="{C["ink-rule"]}" stroke-width="1.5"/>')
    public = [s for s in stats if not s.get("private")]
    if not p["repos"] or not public:
        cy += 30
        msg = ("Code is private for now. The working simulation runs on the portfolio."
               if not p["repos"] else "Repository is private. Stats appear once it's public.")
        if not G:
            msg = "Waiting for the first sync. The workflow fills this in within a minute of the push."
        cy = svg.para(x + 20, cy, plain_runs(msg), w - 40, 14, 20, fill=C["on-ink-dim"], bold_fill=C["on-ink"])
        primary = next((l for l in p["links"] if "github.com" not in l["href"]), None)
        if primary:
            cy += 30
            svg.text(x + 20, cy, primary["label"], 14, "AB", C["hivis"])
            cy += 19
            svg.text(x + 20, cy, fit(primary["href"].split("//", 1)[-1], "AT", 12.5, w - 40), 12.5, "AT", C["on-ink-dim"])
        cy += 26
    compact = len(public) > 1
    for k, s in enumerate(public):
        cy += 28
        name = s["full"].split("/", 1)[1]
        svg.text(x + 20, cy, fit(name, "AB", 15, w - 40), 15, "AB", C["hivis"])
        cy += 12
        cells = [(fmt_n(s["commits"]), "commits"), (fmt_n(s["stars"]), "stars"),
                 (ago(s["pushed_at"]).replace(" ago", ""), "since push")]
        cw = (w - 40) / 3
        big = 22 if compact else 28
        for j, (v, lbl) in enumerate(cells):
            svg.text(x + 20 + j * cw, cy + big + 4, v, big, "AK", C["on-ink"], extra=' letter-spacing="-0.5"')
            svg.text(x + 20 + j * cw, cy + big + 22, lbl, 11.5, "AT", C["on-ink-dim"])
        cy += big + 36
        # 12-week commit sparkline
        weekly = s.get("weekly") or []
        if weekly:
            bw_ = (w - 40) / 12
            hmax = max(weekly) or 1
            sh = 26 if compact else 34
            for j, v in enumerate(weekly):
                bh = max(2, sh * v / hmax)
                col = C["hivis"] if j == len(weekly) - 1 else C["on-ink-dim"]
                svg.add(f'<rect x="{x + 20 + j * bw_ + 1:.1f}" y="{cy + sh - bh:.1f}" width="{bw_ - 3:.1f}" height="{bh:.1f}" rx="1" fill="{col}" opacity="{1 if v else .35}"/>')
            cy += sh + 16
            svg.text(x + 20, cy, "commits, last 12 weeks", 11, "AT", C["on-ink-dim"])
            cy += 6
        # language split
        langs = sorted((s.get("languages") or {}).items(), key=lambda kv: -kv[1])[:4]
        if langs and not compact:
            tot = sum(v for _, v in langs) or 1
            cy += 14
            lx = x + 20
            shades = [C["hivis"], C["on-ink"], C["on-ink-dim"], C["ink-rule"]]
            for j, (lang, v) in enumerate(langs):
                lw = (w - 40) * v / tot
                svg.add(f'<rect x="{lx:.1f}" y="{cy}" width="{max(lw - 2, 1):.1f}" height="6" fill="{shades[j]}"/>')
                lx += lw
            cy += 22
            label = " · ".join(f"{l} {100 * v / tot:.0f}%" for l, v in langs)
            svg.text(x + 20, cy, fit(label, "AT", 11.5, w - 40), 11.5, "AT", C["on-ink-dim"])
        latest = s.get("latest")
        if latest:
            cy += 26
            svg.text(x + 20, cy, f"Last commit · {ago(latest['date'])}", 11.5, "AB", C["on-ink-dim"])
            cy += 19
            lines = wrap(plain_runs(latest["message"]), w - 40, 13.5)[:2 if not compact else 1]
            for li, line in enumerate(lines):
                t = line_text(line)
                if li == len(lines) - 1:
                    t = fit(t, "AT", 13.5, w - 40)
                svg.text(x + 20, cy + li * 19, t, 13.5, "AT", C["on-ink"])
            cy += 19 * (len(lines) - 1)
        if compact and k < len(public) - 1:
            cy += 18
            svg.add(f'<line x1="{x + 20}" x2="{x + w - 20}" y1="{cy}" y2="{cy}" stroke="{C["ink-rule"]}" stroke-width="1"/>')
    cy += 24
    svg.parts.insert(parts_start, f'<rect x="{x}" y="{y}" width="{w}" height="{cy - y}" rx="8" fill="{C["ink"]}"/>')
    return cy


def svg_project(P: dict, p: dict, G: dict) -> str:
    svg = Svg(f"{p['name']}: {p['what']}")
    L = M + PAD
    colw = 540
    px, pw = L + colw + 34, W - M - SH - PAD - (L + colw + 34)
    y = M + PAD + 8
    # stage pill + dates
    live = p["live"]
    pill_w = mw(p["stage"], "AB", 13) + 40
    svg.add(f'<rect x="{L}" y="{y - 15}" width="{pill_w:.0f}" height="26" rx="13" fill="{C["paper"]}" stroke="{C["ink"]}" stroke-width="1.5"/>')
    if live:
        svg.add(halo(L + 15, y - 2, C["ok"], 4, 11))
    svg.add(f'<circle cx="{L + 15}" cy="{y - 2}" r="4" fill="{C["ok"] if live else C["hivis"]}"'
            f'{"" if live else " stroke=" + chr(34) + C["ink"] + chr(34) + " stroke-width=" + chr(34) + "1.5" + chr(34)}/>')
    svg.text(L + 26, y + 3, p["stage"], 13, "AB", C["ink"])
    svg.text(L + pill_w + 14, y + 3, p["dates"], 14, "AT", C["graphite"])
    deck_count(svg, W - M - SH - PAD, y + 3, p["index"], P["total"])
    y += 70
    y = heading(svg, L, y, p["name"], 56, colw, C["ink"])
    y += 34
    y = svg.para(L, y, plain_runs(p["what"]), colw, 19, 26, fill=C["graphite"], bold_fill=C["ink"])
    if p["flag"]:
        lines = wrap(plain_runs(p["flag"]), colw - 26, 14, "AB", "AB")
        fh = 14 + 20 * len(lines)
        fw = max(mw(line_text(l), "AB", 14) for l in lines) + 24
        y += 18
        svg.add(f'<rect x="{L}" y="{y}" width="{fw:.0f}" height="{fh}" rx="3" fill="{C["hivis"]}" stroke="{C["ink"]}" stroke-width="1.5"/>')
        for i, l in enumerate(lines):
            svg.text(L + 12, y + 22 + i * 20, line_text(l), 14, "AB", C["ink"])
        y += fh
    y += 10
    for b in p["bullets"]:
        y += 28
        svg.add(f'<rect x="{L}" y="{y - 6}" width="11" height="2" fill="{C["ink"]}"/>')
        y = svg.para(L + 23, y, to_runs(b), colw - 23, 15.5, 22, fill=C["graphite"], bold_fill=C["ink"], accent_fill=C["ink"])
    if p["stack"]:
        y += 40
        # stack as outlined chips
        cx = L
        for tag in [t.strip() for t in p["stack"].split(",") if t.strip()]:
            tw = mw(tag, "AB", 12.5) + 20
            if cx + tw > L + colw:
                cx = L
                y += 34
            svg.add(f'<rect x="{cx:.1f}" y="{y - 17}" width="{tw:.1f}" height="26" rx="4" fill="none" stroke="{C["ink"]}" stroke-width="1.5"/>')
            svg.text(cx + 10, y + 1, tag, 12.5, "AB", C["ink"])
            cx += tw + 8
        y += 10
    left_bottom = y
    right_bottom = telemetry_panel(svg, px, M + PAD + 42, pw, p, G)
    h = int(max(left_bottom, right_bottom) + PAD - 6 + SH + M)
    plate(svg, h, "sheet")
    return svg.render(W, h)


def svg_proof(P: dict) -> str:
    pr = P["proof"]
    svg = Svg(pr["title"])
    L = M + PAD
    R = W - M - SH - PAD
    y = M + PAD + 8
    svg.text(L, y, pr["yr"], 14, "AB", C["ink"])
    deck_count(svg, R, y, pr["index"], P["total"])
    y += 44
    hy = heading(svg, L, y, pr["title"], 40, 560, C["ink"])
    ty = svg.para(L + 600, y + 4, plain_runs(pr["text"]), R - L - 600, 16, 23, fill=C["ink"], bold_fill=C["ink"])
    y = max(hy, ty) + 34
    # score grid
    n = max(1, len(pr["score"]))
    cw = (R - L) / n
    sh_ = 104
    svg.add(f'<rect x="{L}" y="{y}" width="{R - L}" height="{sh_}" rx="6" fill="{C["hivis"]}" stroke="{C["ink"]}" stroke-width="2"/>')
    for i, (big, lbl) in enumerate(pr["score"]):
        cx = L + i * cw
        if i:
            svg.add(f'<line x1="{cx}" x2="{cx}" y1="{y}" y2="{y + sh_}" stroke="{C["ink"]}" stroke-width="2"/>')
        size = 46
        while mw(big, "AK", size) > cw - 40 and size > 24:
            size -= 2
        svg.text(cx + 20, y + 58, big, size, "AK", C["ink"], extra=' letter-spacing="-1"')
        svg.text(cx + 20, y + 84, fit(lbl, "AB", 14, cw - 40), 14, "AB", C["ink"])
    y += sh_ + 22
    # more
    if pr["more"]:
        n = len(pr["more"])
        cw = (R - L) / n
        tops = []
        box_y = y
        for i, (yr, h3, ptxt) in enumerate(pr["more"]):
            cx = L + i * cw + 20
            yy = box_y + 30
            svg.text(cx, yy, yr, 12.5, "AB", C["ink"], extra=' opacity="0.72"')
            yy += 26
            yy = svg.para(cx, yy, plain_runs(h3), cw - 40, 17, 21, fn="AW", fb="AW", fill=C["ink"], bold_fill=C["ink"])
            yy += 24
            yy = svg.para(cx, yy, plain_runs(ptxt), cw - 40, 14, 20, fill=C["ink"], bold_fill=C["ink"])
            tops.append(yy)
        bh = max(tops) + 24 - box_y
        svg.add(f'<rect x="{L}" y="{box_y}" width="{R - L}" height="{bh}" rx="6" fill="none" stroke="{C["ink"]}" stroke-width="2"/>')
        for i in range(1, n):
            svg.add(f'<line x1="{L + i * cw}" x2="{L + i * cw}" y1="{box_y}" y2="{box_y + bh}" stroke="{C["ink"]}" stroke-width="2"/>')
        y = box_y + bh
    h = int(y + PAD - 6 + SH + M)
    plate(svg, h, "hivis")
    return svg.render(W, h)


def svg_telemetry(G: dict) -> str:
    svg = Svg("Live GitHub telemetry")
    L = M + PAD
    R = W - M - SH - PAD
    y = M + PAD + 36
    heading(svg, L, y, "Live telemetry.", 44, 600, C["ink"])
    y += 34
    when = dt.datetime.fromisoformat(G["fetched_at"]).strftime("%d %b %Y, %H:%M IST") if G.get("fetched_at") else "pending"
    svg.text(L, y, f"Pulled from GitHub every {CFG.get('refresh_label', '6 hours')}, counts cover the past year. Last sync {when}.", 16, "AT", C["graphite"])
    y += 30
    cal = G.get("calendar") or {}
    u = G.get("user") or {}
    cells = [
        (fmt_n(cal.get("total")), "contributions"),
        (fmt_n(cal.get("commits")), "commits"),
        (fmt_n(cal.get("prs")), "pull requests"),
        (fmt_n(u.get("public_repos")), "public repos"),
        (fmt_n(G.get("stars")), "stars earned"),
        (f"{cal.get('streak', 0)} d" if cal else "–", f"streak · best {cal.get('longest', 0)} d" if cal else "streak"),
    ]
    cw = (R - L) / len(cells)
    ch = 96
    svg.add(f'<rect x="{L}" y="{y}" width="{R - L}" height="{ch}" rx="6" fill="{C["sheet"]}" stroke="{C["ink"]}" stroke-width="2"/>')
    for i, (v, lbl) in enumerate(cells):
        cx = L + i * cw
        if i:
            svg.add(f'<line x1="{cx}" x2="{cx}" y1="{y}" y2="{y + ch}" stroke="{C["ink"]}" stroke-width="1.5"/>')
        svg.text(cx + 16, y + 52, v, 32, "AK", C["ink"], extra=' letter-spacing="-0.8"')
        svg.text(cx + 16, y + 76, fit(lbl, "AB", 11.5, cw - 24), 11.5, "AB", C["graphite"])
    y += ch + 36

    days = cal.get("days") or []
    if days:
        cell, gap = 12, 3
        weeks: list[list] = []
        for d, c in days:
            wd = (dt.date.fromisoformat(d).weekday() + 1) % 7  # Sunday = 0 like GitHub
            if not weeks or wd == 0:
                weeks.append([None] * 7)
            weeks[-1][wd] = (d, c)
        weeks = weeks[-53:]
        gw = len(weeks) * (cell + gap)
        gx = L + (R - L - gw - 30) / 2 + 30
        nz = sorted(c for _, c in days if c)
        qs = [nz[int(len(nz) * q)] for q in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]
        ramp = [C["paper"], "#B9C2CE", C["graphite"], C["ink-2"], C["ink"]]
        def level(c):
            if not c:
                return 0
            return 1 + sum(c > q for q in qs)
        top_day = max(days, key=lambda d: d[1]) if nz else None
        svg.css += ("@keyframes pop{from{opacity:0}to{opacity:1}}.w{opacity:0;animation:pop .5s ease forwards}")
        last_month = None
        for wi, wk in enumerate(weeks):
            wx = gx + wi * (cell + gap)
            first = next((d for d in wk if d), None)
            if first:
                mth = first[0][:7]
                if mth != last_month and first[0][8:10] <= "07":
                    svg.text(wx, y, dt.date.fromisoformat(first[0]).strftime("%b"), 11, "AB", C["graphite"])
                last_month = mth
            g = [f'<g class="w" style="animation-delay:{wi * 0.02:.2f}s">']
            for di, d in enumerate(wk):
                if not d:
                    continue
                lv = level(d[1])
                cy_ = y + 10 + di * (cell + gap)
                fill = C["hivis"] if top_day and d[0] == top_day[0] else ramp[lv]
                stroke = f' stroke="{C["ink"]}" stroke-width="1.2"' if fill == C["hivis"] else (f' stroke="{C["rule"]}" stroke-width="1"' if lv == 0 else "")
                g.append(f'<rect x="{wx}" y="{cy_}" width="{cell}" height="{cell}" rx="2" fill="{fill}"{stroke}><title>{d[0]}: {d[1]}</title></rect>')
            g.append("</g>")
            svg.add("".join(g))
        for di, lbl in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
            svg.text(gx - 8, y + 10 + di * (cell + gap) + 10, lbl, 10.5, "AT", C["graphite"], anchor="end")
        y += 10 + 7 * (cell + gap) + 22
        # legend
        lx = R - 5 * 15 - 40
        svg.text(lx - 8, y + 10, "Less", 11, "AT", C["graphite"], anchor="end")
        for i, col in enumerate(ramp):
            st = f' stroke="{C["rule"]}"' if i == 0 else ""
            svg.add(f'<rect x="{lx + i * 15}" y="{y}" width="12" height="12" rx="2" fill="{col}"{st}/>')
        svg.text(lx + 5 * 15 + 4, y + 10, "More", 11, "AT", C["graphite"])
        if top_day:
            svg.add(f'<rect x="{L}" y="{y}" width="12" height="12" rx="2" fill="{C["hivis"]}" stroke="{C["ink"]}" stroke-width="1.2"/>')
            svg.text(L + 20, y + 10, f"Best day: {top_day[1]} contributions on {dt.date.fromisoformat(top_day[0]).strftime('%d %b')}", 11, "AB", C["ink"])
        y += 48
    else:
        y += 4

    langs = G.get("languages") or []
    if langs:
        top = langs[:6]
        rest = sum(v for _, v in langs[6:])
        if rest:
            top.append(("Other", rest))
        tot = sum(v for _, v in top) or 1
        svg.text(L, y, "Languages across public repos", 14, "AW", C["ink"])
        y += 14
        shades = [C["hivis"], C["ink"], C["ink-2"], C["graphite"], "#8A93A0", "#B9C2CE", C["rule"]]
        lx = L
        svg.add(f'<rect x="{L}" y="{y}" width="{R - L}" height="14" rx="3" fill="{C["paper"]}"/>')
        for i, (lang, v) in enumerate(top):
            lw = (R - L) * v / tot
            svg.add(f'<rect x="{lx:.1f}" y="{y}" width="{max(lw - 2, 1):.1f}" height="14" fill="{shades[i % len(shades)]}"'
                    f'{" stroke=" + chr(34) + C["ink"] + chr(34) if i == 0 else ""}/>')
            lx += lw
        y += 36
        lx = L
        for i, (lang, v) in enumerate(top):
            label = f"{lang} {100 * v / tot:.1f}%"
            lw = mw(label, "AB", 12.5) + 34
            if lx + lw > R:
                lx = L
                y += 22
            svg.add(f'<rect x="{lx}" y="{y - 10}" width="11" height="11" rx="2" fill="{shades[i % len(shades)]}" stroke="{C["ink"]}" stroke-width="1"/>')
            svg.text(lx + 17, y, label, 12.5, "AB", C["ink"])
            lx += lw
        y += 10
    elif not G:
        svg.text(L, y, "Waiting for the first sync. The workflow fills this in after the first push.", 15, "AT", C["graphite"])
    h = int(y + PAD - 10 + SH + M)
    plate(svg, h, "paper")
    return svg.render(W, h)


def svg_crew(P: dict) -> str:
    c = P["crew"]
    svg = Svg(c["title"])
    L, R = M + PAD, W - M - SH - PAD
    y = M + PAD + 36
    deck_count(svg, R, M + PAD + 2, c["index"], P["total"])
    y = heading(svg, L, y, c["title"], 44, R - L - 80, C["ink"])
    y += 32
    y = svg.para(L, y, plain_runs(c["lede"]), R - L, 16.5, 24, fill=C["graphite"], bold_fill=C["ink"])
    y += 26
    svg.add(f'<line x1="{L}" x2="{R}" y1="{y}" y2="{y}" stroke="{C["ink"]}" stroke-width="1.5"/>')
    for t, h3, role, ptxt in c["items"]:
        yy = y + 34
        svg.text(L, yy, t, 15, "AB", C["ink"])
        tx = L + 180
        yy = svg.para(tx, yy, plain_runs(h3), R - tx, 20, 25, fn="AW", fb="AW", fill=C["ink"], bold_fill=C["ink"])
        yy += 23
        svg.text(tx, yy, role, 14.5, "AT", C["graphite"])
        yy += 25
        yy = svg.para(tx, yy, to_runs(ptxt), R - tx, 15.5, 22, fill=C["graphite"], bold_fill=C["ink"], accent_fill=C["ink"])
        y = yy + 22
        svg.add(f'<line x1="{L}" x2="{R}" y1="{y}" y2="{y}" stroke="{C["rule"]}" stroke-width="1"/>')
    h = int(y + PAD - 12 + SH + M)
    plate(svg, h, "paper")
    return svg.render(W, h)


def svg_playbook(P: dict) -> str:
    pb = P["playbook"]
    svg = Svg(pb["title"])
    L, R = M + PAD, W - M - SH - PAD
    y = M + PAD + 36
    deck_count(svg, R, M + PAD + 2, pb["index"], P["total"], on_ink=True)
    y = heading(svg, L, y, pb["title"], 44, R - L - 80, C["on-ink"])
    y += 32
    y = svg.para(L, y, plain_runs(pb["lede"]), R - L, 16.5, 24, fill=C["on-ink-dim"], bold_fill=C["on-ink"])
    y += 22
    cw = (R - L) / 2
    rows = [pb["rules"][i:i + 2] for i in range(0, len(pb["rules"]), 2)]
    n = 0
    for row in rows:
        svg.add(f'<line x1="{L}" x2="{R}" y1="{y}" y2="{y}" stroke="{C["ink-rule"]}" stroke-width="1.5"/>')
        bottoms = []
        for j, (h3, ptxt) in enumerate(row):
            n += 1
            cx = L + j * cw + (28 if j else 0)
            inner = cw - 28 - (0 if j else 0)
            yy = y + 34
            svg.text(cx, yy, f"{n:02d}", 13, "AB", C["hivis"])
            yy += 28
            yy = svg.para(cx, yy, plain_runs(h3), inner - 10, 21, 25, fn="AW", fb="AW", fill=C["on-ink"], bold_fill=C["on-ink"])
            yy += 27
            yy = svg.para(cx, yy, to_runs(ptxt), inner - 10, 15, 22, fill=C["on-ink-dim"], bold_fill=C["on-ink"], accent_fill=C["hivis"])
            bottoms.append(yy)
        ny = max(bottoms) + 28
        if len(row) > 1:
            svg.add(f'<line x1="{L + cw}" x2="{L + cw}" y1="{y}" y2="{ny}" stroke="{C["ink-rule"]}" stroke-width="1.5"/>')
        y = ny
    h = int(y + PAD - 20 + SH + M)
    plate(svg, h, "ink")
    return svg.render(W, h)


def svg_toolkit(P: dict) -> str:
    tk = P["toolkit"]
    svg = Svg(tk["title"])
    L, R = M + PAD, W - M - SH - PAD
    y = M + PAD + 36
    deck_count(svg, R, M + PAD + 2, tk["index"], P["total"])
    y = heading(svg, L, y, tk["title"], 44, R - L - 80, C["ink"])
    y += 32
    y = svg.para(L, y, plain_runs(tk["lede"]), R - L, 16.5, 24, fill=C["graphite"], bold_fill=C["ink"])
    y += 24
    svg.add(f'<line x1="{L}" x2="{R}" y1="{y}" y2="{y}" stroke="{C["ink"]}" stroke-width="1.5"/>')
    for th, td in tk["rows"]:
        yy = y + 30
        svg.text(L, yy, th, 16, "AW", C["ink"])
        tx = L + 210
        yy = svg.para(tx, yy, plain_runs(td), R - tx, 15.5, 22, fill=C["graphite"], bold_fill=C["ink"])
        y = yy + 18
        svg.add(f'<line x1="{L}" x2="{R}" y1="{y}" y2="{y}" stroke="{C["rule"]}" stroke-width="1"/>')
    h = int(y + PAD - 12 + SH + M)
    plate(svg, h, "sheet")
    return svg.render(W, h)


def svg_section(title: str, lede: str) -> str:
    svg = Svg(title)
    L, R = M + PAD, W - M - SH - PAD
    y = M + 30 + 30
    heading(svg, L, y, title, 34, R - L, C["ink"])
    y += 30
    y = svg.para(L, y, plain_runs(lede), R - L, 15.5, 22, fill=C["graphite"], bold_fill=C["ink"])
    h = int(y + 30 + SH + M)
    plate(svg, h, "paper")
    return svg.render(W, h)


def svg_contact(P: dict, G: dict) -> str:
    ct = P["contact"]
    svg = Svg(ct["title"])
    L, R = M + PAD, W - M - SH - PAD
    y = M + PAD + 40
    deck_count(svg, R, M + PAD + 2, ct["index"], P["total"], on_ink=True)
    y = heading(svg, L, y, ct["title"], 50, R - L - 80, C["on-ink"])
    y += 34
    y = svg.para(L, y, plain_runs(ct["lede"]), 620, 17, 25, fill=C["on-ink-dim"], bold_fill=C["on-ink"])
    y += 34
    # title block, like the bottom-right corner of a drawing sheet
    cells = list(ct["titleblock"])
    synced = dt.datetime.fromisoformat(G["fetched_at"]).strftime("%d %b %Y") if G.get("fetched_at") else NOW.strftime("%d %b %Y")
    cells.append(("Last synced", synced))
    weights = [2] + [1] * (len(cells) - 1)
    unit = (R - L) / sum(weights)
    th = 62
    svg.add(f'<rect x="{L}" y="{y}" width="{R - L}" height="{th}" fill="{C["ink-2"]}" stroke="{C["on-ink-dim"]}" stroke-width="2"/>')
    cx = L
    for i, (k, v) in enumerate(cells):
        cw = unit * weights[i]
        if i:
            svg.add(f'<line x1="{cx}" x2="{cx}" y1="{y}" y2="{y + th}" stroke="{C["on-ink-dim"]}" stroke-width="1.5"/>')
        svg.text(cx + 14, y + 24, k, 11.5, "AT", C["on-ink-dim"])
        col = C["hivis"] if k.lower().startswith("drawn") else C["on-ink"]
        svg.text(cx + 14, y + 46, fit(v, "AB", 14, cw - 24), 14, "AB", col)
        cx += cw
    y += th
    h = int(y + PAD - 6 + SH + M)
    plate(svg, h, "ink")
    return svg.render(W, h)


def svg_button(label: str, solid: bool, external: bool) -> str:
    svg = Svg(label)
    size = 15
    tw = mw(label, "AB", size)
    w = int(tw + 36 + (18 if external else 0))
    h = 44
    fill = C["ink"] if solid else C["sheet"]
    fg = C["paper"] if solid else C["ink"]
    svg.add(f'<rect x="{SH - 3}" y="{SH - 3}" width="{w - SH}" height="{h - SH}" rx="4" fill="{C["hivis"] if solid else C["ink"]}"/>')
    svg.add(f'<rect x="1" y="1" width="{w - SH - 2}" height="{h - SH - 2}" rx="4" fill="{fill}" stroke="{C["ink"]}" stroke-width="1.5"/>')
    svg.text(17, 24.5, label, size, "AB", fg)
    if external:
        ax = 17 + tw + 9
        svg.add(f'<path d="M{ax} {27}l8-8M{ax + 2} {19}h6v6" fill="none" stroke="{fg}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>')
    return svg.render(w, h)


# ─────────────────────────────────────────────────────────── writing ──

WRITTEN: dict[str, str] = {}


def write_svg(name: str, content: str) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.svg"
    path.write_text(content, encoding="utf-8")
    rel = f"./assets/generated/{name}.svg"
    WRITTEN[name] = rel
    return rel


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def button_row(links: list[dict], prefix: str) -> str:
    out = []
    for i, l in enumerate(links):
        external = not l["href"].startswith(("mailto:", "tel:"))
        src = write_svg(f"btn-{prefix}-{slugify(l['label'])}", svg_button(l["label"], l.get("kind") == "solid", external))
        out.append(f'<a href="{esc(l["href"])}"><img src="{src}" alt="{esc(l["label"])}" height="44"/></a>')
    return "\n".join(out)


def img(src: str, alt: str, href: str = "") -> str:
    tag = f'<img src="{src}" alt="{esc(alt)}" width="100%"/>'
    return f'<a href="{esc(href)}">{tag}</a>' if href else tag


def md_escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def build_readme(P: dict, G: dict) -> str:
    site = CFG["portfolio_url"].rstrip("/")
    blocks: dict[str, str] = {}

    blocks["banner"] = img(write_svg("banner", svg_banner(P, G)),
                           f"{' '.join(P['cover']['name'])}: {' '.join(P['cover']['claim'])}", site)

    ct = P.get("contact", {})
    reach = {l["label"].lower(): l for l in ct.get("reach", [])}
    nav = [{"kind": "solid", "label": CFG.get("portfolio_label", "sujalnegi.tech"), "href": site}]
    for key in ("download résumé", "linkedin", "github"):
        if key in reach:
            l = dict(reach[key])
            l["kind"] = "line"
            if key == "download résumé":
                l["label"] = "Résumé"
            nav.append(l)
    email = next((l for l in ct.get("reach", []) if l["href"].startswith("mailto:")), None)
    if email:
        nav.append({"kind": "line", "label": "Email", "href": email["href"]})
    blocks["nav"] = button_row(nav, "nav")

    a = P["about"]
    blocks["about"] = img(write_svg("about", svg_about(P)), a["title"], f"{site}/#{'s-about'}")
    extra = [f"**{k}:** {to_md(v, site)}" for k, v in a["facts"] if "<a" in v]
    blocks["about_links"] = " · ".join(extra)

    proj_md = []
    for p in P["projects"]:
        primary = p["links"][0]["href"] if p["links"] else f"{site}/#{p['anchor']}"
        alt = f"{p['name']}: {p['what']}. {p['stage']}, {p['dates']}."
        part = [img(write_svg(f"project-{p['slug']}", svg_project(P, p, G)), alt, primary)]
        if p["links"]:
            part.append("<br/>")
            part.append(button_row(p["links"], p["slug"]))
        proj_md.append('<p align="center">\n' + "\n".join(part) + "\n</p>")
    blocks["projects"] = "\n\n<br/>\n\n".join(proj_md)

    if P.get("proof"):
        blocks["proof"] = img(write_svg("proof", svg_proof(P)), P["proof"]["title"], f"{site}/#s-traction")
    blocks["telemetry"] = img(write_svg("telemetry", svg_telemetry(G)), "Live GitHub telemetry",
                              f"https://github.com/{USER}?tab=repositories")

    # recently shipped: live table
    blocks["shipped_head"] = img(write_svg("section-shipped", svg_section(
        "Recently shipped.", "The latest commit on each repo I've pushed to, refreshed on every sync.")), "Recently shipped")
    rows = ["| Repo | Latest commit | When |", "|:--|:--|--:|"]
    for r in G.get("recent", []):
        l = r["latest"]
        rows.append(f"| [**{r['name']}**]({r['url']}) | [`{l['sha']}`]({l['url']}) {md_escape_cell(l['message'])} | {ago(l['date'])} |")
    blocks["shipped"] = "\n".join(rows) if len(rows) > 2 else "_Filled in on the first sync._"

    bench = G.get("bench", [])
    if bench:
        brow = ["| Also on the bench | What it is | Stack |", "|:--|:--|:--|"]
        for r in bench:
            name = f"[**{r['name']}**]({r['url']})" + (f" · [live]({r['homepage']})" if r["homepage"] else "")
            brow.append(f"| {name} | {md_escape_cell(r['description']) or '—'} | {r['language'] or '—'} |")
        blocks["bench"] = "\n".join(brow)
    else:
        blocks["bench"] = ""

    if P.get("crew"):
        blocks["crew"] = img(write_svg("crew", svg_crew(P)), P["crew"]["title"], f"{site}/#s-teams")
    if P.get("playbook"):
        blocks["playbook"] = img(write_svg("playbook", svg_playbook(P)), P["playbook"]["title"], f"{site}/#s-playbook")
    if P.get("toolkit"):
        blocks["toolkit"] = img(write_svg("toolkit", svg_toolkit(P)), P["toolkit"]["title"], f"{site}/#s-toolkit")
    if ct:
        blocks["contact"] = img(write_svg("contact", svg_contact(P, G)), ct["title"],
                                email["href"] if email else site)
        shown = [l for l in ct["reach"] if CFG.get("show_phone") or not l["href"].startswith("tel:")]
        blocks["contact_buttons"] = button_row(
            [dict(l, label=("Résumé" if l["label"].lower() == "download résumé" else l["label"])) for l in shown],
            "contact")
    blocks["synced"] = (dt.datetime.fromisoformat(G["fetched_at"]).strftime("%d %b %Y, %H:%M IST")
                        if G.get("fetched_at") else "pending first run")
    blocks["site"] = site
    blocks["user"] = USER

    tpl = (ROOT / "templates" / "README.template.md").read_text(encoding="utf-8")
    out = re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", lambda m: blocks.get(m.group(1), ""), tpl)
    return re.sub(r"\n{4,}", "\n\n\n", out)


def main() -> None:
    P = load_portfolio()
    C.update({k: v for k, v in (P.get("palette") or {}).items() if k in C})
    G = load_github(P)
    # remove stale generated files, then write fresh ones
    if OUT.exists():
        for f in OUT.glob("*.svg"):
            f.unlink()
    readme = build_readme(P, G)
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    log(f"wrote README.md and {len(WRITTEN)} images")


if __name__ == "__main__":
    main()
