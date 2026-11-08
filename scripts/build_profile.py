#!/usr/bin/env python3
"""Rebuild the live parts of this GitHub profile README.

Reads profile.json, pulls current data from the GitHub API, then rewrites
generated/*.svg and the marked sections of README.md:

    <!-- NAME:START --> ...generated... <!-- NAME:END -->

Everything outside the markers is left alone, so the intro text can be
edited by hand. Standard library only. Needs a token in GITHUB_TOKEN
(GitHub Actions provides one automatically).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "generated"
README = ROOT / "README.md"
CONFIG = ROOT / "profile.json"
API = "https://api.github.com"

# Blurple on a violet-tinted ink surface. Checked with the dataviz validator:
# fills #6366F1 4.06:1, line #818CF8 6.09:1, heatmap ramp monotone with
# its darkest step 2.07:1 against SURFACE.
SURFACE = "#14151F"
BORDER = "#2B2D42"
BASELINE = "#3A3C50"
TRACK = "#22243A"
TEXT = "#F0F0F7"
MUTED = "#C3C4D6"
FAINT = "#8A8CA3"
ACCENT = "#6366F1"       # fills: area, bars, heatmap
ACCENT_LINE = "#818CF8"  # thin strokes and dots
ACCENT_TEXT = "#A5B4FC"  # small accent labels
HEAT = {
    "NONE": "#1F2029",
    "FIRST_QUARTILE": "#3E438D",
    "SECOND_QUARTILE": "#4E53B3",
    "THIRD_QUARTILE": "#6366F1",
    "FOURTH_QUARTILE": "#818CF8",
}
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"

# Not counted as "main languages" in the header line.
MARKUP = {"HTML", "CSS", "SCSS", "Less", "Batchfile", "Makefile", "Dockerfile", "Procfile"}
WEEKDAYS = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"]
SOCIAL_LABELS = {
    "linkedin": "LinkedIn", "twitter": "X", "bluesky": "Bluesky", "mastodon": "Mastodon",
    "youtube": "YouTube", "instagram": "Instagram", "facebook": "Facebook",
    "reddit": "Reddit", "twitch": "Twitch", "npm": "npm", "hometown": "Hometown",
}


# --------------------------------------------------------------------------- API

class Api:
    def __init__(self, token: str):
        self.token = token

    def _request(self, path: str, accept: str = "application/vnd.github+json",
                 payload: dict | None = None) -> str:
        url = path if path.startswith("http") else API + path
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "profile-readme-builder",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")

    def json(self, path: str):
        return json.loads(self._request(path))

    def raw(self, path: str) -> str:
        return self._request(path, accept="application/vnd.github.raw")

    def graphql(self, query: str, variables: dict) -> dict:
        body = json.loads(self._request("/graphql", payload={"query": query, "variables": variables}))
        if body.get("errors"):
            raise RuntimeError(body["errors"])
        return body["data"]


def fetch_repos(api: Api, login: str) -> list[dict]:
    repos, page = [], 1
    while True:
        batch = api.json(f"/users/{login}/repos?type=owner&sort=pushed&per_page=100&page={page}")
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    # /users/{login}/repos only returns public repos; the filter is a second guard.
    return [r for r in repos if not r.get("private")]


def fetch_contributions(api: Api, login: str):
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date weekday contributionCount contributionLevel } }
          }
        }
      }
    }"""
    cal = api.graphql(query, {"login": login})["user"]["contributionsCollection"]["contributionCalendar"]
    return cal["totalContributions"], cal["weeks"]


def fetch_readme(api: Api, full_name: str) -> str:
    try:
        return api.raw(f"/repos/{full_name}/readme")
    except urllib.error.HTTPError:
        return ""


# ------------------------------------------------------------------- text helpers

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def text_width(s: str, size: float) -> float:
    """Rough width of sans-serif text, good enough for wrapping."""
    w = 0.0
    for ch in s:
        if ch in "il.,:;|!'’ ":
            w += 0.28
        elif ch in "frtj()[]-/":
            w += 0.36
        elif ch in "mwMW":
            w += 0.84
        elif ch.isupper():
            w += 0.66
        elif ch.isdigit():
            w += 0.56
        else:
            w += 0.53
    return w * size


def ellipsize(s: str, size: float, max_w: float) -> str:
    while s and text_width(s + "…", size) > max_w:
        s = s[:-1]
    return s.rstrip(" ,;:-") + "…"


def fit(s: str, size: float, max_w: float) -> str:
    return s if text_width(s, size) <= max_w else ellipsize(s, size, max_w)


def wrap(s: str, size: float, max_w: float, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        if text_width(trial, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = ellipsize(lines[-1], size, max_w)
    return [fit(line, size, max_w) for line in lines]


def weak(desc: str | None) -> bool:
    return not desc or len(desc.split()) < 4


def strip_md(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"<[^>]+>", "", line)
    line = re.sub(r"[*_`]", "", line)
    return " ".join(line.split())


def readme_summary(text: str) -> str:
    """First real sentence of a README, skipping headings, badges and lists."""
    for block in re.split(r"\n\s*\n", text):
        line = block.strip()
        if not line or line.startswith(("#", "!", "<", "|", "```", "-", "*", ">", "[", "=")):
            continue
        line = strip_md(line)
        if len(line.split()) >= 6:
            m = re.match(r"(.+?[.!?])(\s|$)", line)
            return m.group(1) if m else line
    return ""


def readme_title(text: str, repo_name: str) -> str | None:
    """Use the README's H1 spelling (e.g. 'ValueTrack') when it matches the repo name."""
    m = re.search(r"^#\s+(.+)$", text, re.M)
    if not m:
        return None
    head = re.split(r"\s+[—–:|-]\s+", strip_md(m.group(1)))[0].strip()

    def norm(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())

    return head if head and norm(head) == norm(repo_name) else None


def month_year(iso: str) -> str:
    return dt.datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %Y")


def is_ml(repo: dict, keywords: list[str]) -> bool:
    kws = {k.lower() for k in keywords}
    if {t.lower() for t in repo.get("topics") or []} & kws:
        return True
    if repo.get("language") == "Jupyter Notebook":
        return True
    text = f"{repo.get('name', '')} {repo.get('description') or ''}".lower()
    text = text.replace("-", " ").replace("_", " ")
    return any(re.search(rf"\b{re.escape(k.replace('-', ' '))}\b", text) for k in kws)


# ------------------------------------------------------------------------- SVGs

def svg_open(w: int, h: int, label: str, style: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}">'
        f"<style>.s{{font-family:{SANS}}}.m{{font-family:{MONO}}}{style}</style>"
    )


def header_svg(cfg: dict, weeks: list | None, total: int | None, main_langs: list[str]) -> str:
    W, H = 1000, 250
    style = (
        ".ring{transform-box:fill-box;transform-origin:center;animation:ring 2.6s ease-out infinite}"
        "@keyframes ring{from{transform:scale(1);opacity:.55}to{transform:scale(3.2);opacity:0}}"
        "@media (prefers-reduced-motion:reduce){.ring{animation:none;opacity:0}}"
    )
    out = [svg_open(W, H, f"{cfg['name']}. {cfg['headline']} {cfg['subline']}", style)]
    out.append(
        '<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{ACCENT}" stop-opacity=".32"/>'
        f'<stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></linearGradient></defs>'
    )
    out.append(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="16" fill="{SURFACE}" stroke="{BORDER}" stroke-width="1.5"/>')
    out.append(f'<text class="s" x="48" y="104" font-size="46" font-weight="700" fill="{TEXT}">{esc(cfg["name"])}</text>')
    out.append(f'<text class="s" x="48" y="146" font-size="19" fill="{MUTED}">{esc(cfg["headline"])}</text>')
    out.append(f'<text class="s" x="48" y="174" font-size="15" fill="{FAINT}">{esc(cfg["subline"])}</text>')
    meta = "  ·  ".join([cfg.get("location", "")] + main_langs[:2]).upper()
    out.append(f'<text class="m" x="48" y="212" font-size="11" letter-spacing="1.4" fill="{FAINT}" xml:space="preserve">{esc(meta)}</text>')

    days = [d for w in (weeks or []) for d in w["contributionDays"]]
    if len(days) > 1:
        x0, x1, top, base = 620, 952, 76, 186
        cum, running = [], 0
        for d in days:
            running += d["contributionCount"]
            cum.append(running)
        peak = max(cum[-1], 1)
        n = len(cum)
        pts = [(x0 + (x1 - x0) * i / (n - 1), base - (base - top) * c / peak) for i, c in enumerate(cum)]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        for gy in (top, (top + base) / 2):
            out.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" stroke="{BORDER}" stroke-dasharray="2 5"/>')
        out.append(f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{base}" stroke="{BASELINE}" stroke-width="1.5"/>')
        out.append(f'<polygon points="{x0},{base} {line} {x1},{base}" fill="url(#area)"/>')
        out.append(f'<polyline points="{line}" fill="none" stroke="{ACCENT_LINE}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        ex, ey = pts[-1]
        out.append(f'<circle class="ring" cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="none" stroke="{ACCENT_LINE}" stroke-width="1.5"/>')
        out.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="{ACCENT_LINE}"/>')
        out.append(f'<text class="m" x="{x0}" y="56" font-size="11" letter-spacing="1.4" fill="{FAINT}">CONTRIBUTIONS · 12 MONTHS</text>')
        out.append(f'<text class="s" x="{x1}" y="58" font-size="24" font-weight="700" fill="{TEXT}" text-anchor="end">{total}</text>')
        out.append(f'<text class="m" x="{x0}" y="208" font-size="10.5" letter-spacing="1" fill="{FAINT}">{month_year(days[0]["date"]).upper()}</text>')
        out.append(f'<text class="m" x="{x1}" y="208" font-size="10.5" letter-spacing="1" fill="{FAINT}" text-anchor="end">{month_year(days[-1]["date"]).upper()}</text>')
    out.append("</svg>")
    return "".join(out)


def card_svg(index: int, card: dict) -> str:
    W, H = 420, 200
    title = fit(card["title"], 19, W - 56)
    lines = wrap(card["desc"], 13.5, W - 56, 3)
    out = [svg_open(W, H, f"{card['title']}: {card['desc']}")]
    out.append(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="14" fill="{SURFACE}" stroke="{BORDER}" stroke-width="1.5"/>')
    out.append(f'<text class="m" x="28" y="40" font-size="11" letter-spacing="1.5" fill="{FAINT}">{index:02d}</text>')
    if card.get("tag"):
        out.append(f'<text class="m" x="{W - 28}" y="40" font-size="10" letter-spacing="1.5" fill="{ACCENT_TEXT}" text-anchor="end">{esc(card["tag"])}</text>')
    out.append(f'<text class="s" x="28" y="72" font-size="19" font-weight="600" fill="{TEXT}">{esc(title)}</text>')
    for i, line in enumerate(lines):
        out.append(f'<text class="s" x="28" y="{100 + i * 20}" font-size="13.5" fill="{MUTED}">{esc(line)}</text>')
    meta = card.get("meta", "")
    if card.get("lang"):
        out.append(f'<circle cx="33" cy="167" r="4.5" fill="{ACCENT_LINE}"/>')
        sep = f'<tspan fill="{FAINT}"> · {esc(meta)}</tspan>' if meta else ""
        out.append(f'<text class="s" x="46" y="171.5" font-size="12.5" fill="{MUTED}">{esc(card["lang"])}{sep}</text>')
    elif meta:
        out.append(f'<text class="s" x="28" y="171.5" font-size="12.5" fill="{FAINT}">{esc(meta)}</text>')
    out.append("</svg>")
    return "".join(out)


def langs_svg(shares: list[tuple[str, float]]) -> str:
    """One bar per language in a single hue; the text label carries identity."""
    W, row, top = 1000, 30, 62
    H = top + row * (len(shares) - 1) + 30
    label_x, track_x, track_w, pct_x = 32, 180, 690, 968
    label = ", ".join(f"{n} {p:.1f}%" for n, p in shares)
    out = [svg_open(W, H, f"Languages across public repositories: {label}")]
    out.append(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="14" fill="{SURFACE}" stroke="{BORDER}" stroke-width="1.5"/>')
    out.append(f'<text class="m" x="{label_x}" y="34" font-size="11" letter-spacing="1.4" fill="{FAINT}">LANGUAGES · PUBLIC REPOSITORIES</text>')
    for i, (name, pct) in enumerate(shares):
        y = top + i * row
        w = max(track_w * pct / 100, 8)
        out.append(f'<text class="s" x="{label_x}" y="{y + 4.5}" font-size="13.5" fill="{MUTED}">{esc(name)}</text>')
        out.append(f'<rect x="{track_x}" y="{y - 4}" width="{track_w}" height="8" rx="4" fill="{TRACK}"/>')
        out.append(f'<rect x="{track_x}" y="{y - 4}" width="{w:.1f}" height="8" rx="4" fill="{ACCENT}"/>')
        out.append(f'<text class="s" x="{pct_x}" y="{y + 4.5}" font-size="13.5" fill="{TEXT}" text-anchor="end">{pct:.1f}%</text>')
    out.append("</svg>")
    return "".join(out)


def activity_svg(weeks: list, total: int) -> str:
    W, H = 1000, 196
    step, cell, left, top = 15, 12, 56, 44
    weeks = weeks[-53:]
    days = [d for w in weeks for d in w["contributionDays"]]
    longest = run = 0
    per_weekday = [0] * 7
    for d in days:
        per_weekday[d["weekday"]] += d["contributionCount"]
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)
    busiest = WEEKDAYS[per_weekday.index(max(per_weekday))] if total else "—"

    out = [svg_open(W, H, f"{total} contributions in the last 12 months. Longest streak {longest} days. Busiest on {busiest}.")]
    out.append(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="14" fill="{SURFACE}" stroke="{BORDER}" stroke-width="1.5"/>')
    last_label_x = -100
    prev_month = None
    for wi, week in enumerate(weeks):
        x = left + wi * step
        first = week["contributionDays"][0]["date"]
        month = first[5:7]
        if month != prev_month:
            if x - last_label_x >= 36 and wi < len(weeks) - 2:
                name = dt.datetime.strptime(first[:10], "%Y-%m-%d").strftime("%b")
                out.append(f'<text class="m" x="{x}" y="34" font-size="10" fill="{FAINT}">{name}</text>')
                last_label_x = x
            prev_month = month
        for d in week["contributionDays"]:
            y = top + d["weekday"] * step
            out.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" fill="{HEAT.get(d["contributionLevel"], HEAT["NONE"])}"/>')
    for wd, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(f'<text class="m" x="{left - 10}" y="{top + wd * step + 10}" font-size="9.5" fill="{FAINT}" text-anchor="end">{name}</text>')
    sx = 880
    stats = [(str(total), "contributions"), (f"{longest} day{'s' if longest != 1 else ''}", "longest streak"), (busiest, "busiest day")]
    for i, (value, label) in enumerate(stats):
        y = 66 + i * 46
        out.append(f'<text class="s" x="{sx}" y="{y}" font-size="20" font-weight="700" fill="{TEXT}">{esc(value)}</text>')
        out.append(f'<text class="s" x="{sx}" y="{y + 16}" font-size="12" fill="{FAINT}">{label}</text>')
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------- markdown

def img_tag(src: str, alt: str, width: str) -> str:
    return f'<img src="{src}" width="{width}" alt="{esc(alt)}" />'


def replace_block(text: str, key: str, body: str) -> str:
    pattern = re.compile(rf"(<!-- {key}:START -->)(.*?)(<!-- {key}:END -->)", re.S)
    if not pattern.search(text):
        print(f"warning: README has no {key} markers", file=sys.stderr)
        return text
    inner = f"\n\n{body.strip()}\n\n" if body.strip() else "\n"
    return pattern.sub(lambda m: m.group(1) + inner + m.group(3), text)


def current_block(text: str, key: str) -> str:
    m = re.search(rf"<!-- {key}:START -->(.*?)<!-- {key}:END -->", text, re.S)
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------------------- main

def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("error: set GITHUB_TOKEN (or GH_TOKEN)", file=sys.stderr)
        return 1
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    login = os.environ.get("PROFILE_USER") or ROOT.name
    api = Api(token)
    tz = dt.timezone(dt.timedelta(minutes=int(cfg.get("utc_offset_minutes", 0))))
    exclude = {name.lower() for name in cfg.get("exclude", [])} | {login.lower()}
    keywords = cfg.get("ml_keywords", [])

    user = api.json(f"/users/{login}")
    repos = [r for r in fetch_repos(api, login) if r["name"].lower() not in exclude]
    own = [r for r in repos if not r.get("fork") and not r.get("archived")]
    forks = [r for r in repos if r.get("fork")]
    try:
        socials = api.json(f"/users/{login}/social_accounts")
    except urllib.error.HTTPError:
        socials = []
    try:
        total, weeks = fetch_contributions(api, login)
    except Exception as exc:  # keep the old activity graphic if this fails
        print(f"warning: contributions unavailable ({exc})", file=sys.stderr)
        total, weeks = None, None

    # Languages across public, original repositories
    lang_bytes: dict[str, int] = {}
    for r in own:
        for name, size in api.json(f"/repos/{r['full_name']}/languages").items():
            lang_bytes[name] = lang_bytes.get(name, 0) + size
    all_bytes = sum(lang_bytes.values())
    shares: list[tuple[str, float]] = []
    if all_bytes:
        other = 0.0
        for name, size in sorted(lang_bytes.items(), key=lambda kv: -kv[1]):
            pct = 100 * size / all_bytes
            if pct < 1.5 or len(shares) >= 6:
                other += pct
            else:
                shares.append((name, pct))
        if other >= 1:
            shares.append(("Other", other))
    main_langs = [n for n, _ in shares if n not in MARKUP and n != "Other"]

    # Project cards: featured first, then public repos by most recent push
    cards: list[dict] = []
    public_by_name = {r["name"].lower(): r for r in own}
    used = set()

    def repo_card(r: dict, title: str | None = None, fallback: str | None = None) -> dict:
        readme = fetch_readme(api, r["full_name"])
        desc = r.get("description")
        if weak(desc):
            desc = readme_summary(readme) or fallback or desc or "No description yet."
        meta = []
        if r.get("stargazers_count"):
            meta.append(f"★ {r['stargazers_count']}")
        meta.append(f"updated {month_year(r['pushed_at'])}")
        return {
            "title": title or readme_title(readme, r["name"]) or r["name"],
            "desc": desc,
            "lang": r.get("language"),
            "meta": " · ".join(meta),
            "url": r["html_url"],
        }

    for f in cfg.get("featured", []):
        live = public_by_name.get(f["repo"].lower())
        if live:
            cards.append(repo_card(live, f.get("title"), f.get("description")))
            used.add(f["repo"].lower())
        else:
            cards.append({
                "title": f.get("title", f["repo"]),
                "desc": f.get("description", ""),
                "lang": f.get("language"),
                "meta": f.get("private_note", ""),
                "tag": "PRIVATE",
                "url": None,
            })
    for r in sorted(own, key=lambda r: r.get("pushed_at") or "", reverse=True):
        if r["name"].lower() not in used:
            cards.append(repo_card(r))
    cards = cards[: int(cfg.get("max_projects", 6))]

    # Build every output in memory first
    files: dict[str, str] = {}
    blocks: dict[str, str] = {}

    def add(name: str, svg: str) -> str:
        files[name] = svg + "\n"
        digest = hashlib.sha1(svg.encode("utf-8")).hexdigest()[:8]
        return f"generated/{name}?v={digest}"

    readme_text = README.read_text(encoding="utf-8")

    if weeks is None and (GEN_DIR / "header.svg").exists():
        files["header.svg"] = (GEN_DIR / "header.svg").read_text(encoding="utf-8")
        blocks["HEADER"] = current_block(readme_text, "HEADER")
    else:
        src = add("header.svg", header_svg(cfg, weeks, total, main_langs))
        blocks["HEADER"] = img_tag(src, f"{cfg['name']}. {cfg['headline']} {cfg['subline']}", "100%")

    rows = []
    for i in range(0, len(cards), 2):
        cells = []
        for j, card in enumerate(cards[i:i + 2], start=i + 1):
            src = add(f"card-{j:02d}.svg", card_svg(j, card))
            details = ", ".join(x for x in (card.get("lang"), card.get("meta")) if x)
            alt = f"{card['title']}: {card['desc']}" + (f" ({details})" if details else "")
            tag = img_tag(src, alt, "49%")
            cells.append(f'<a href="{card["url"]}">{tag}</a>' if card.get("url") else tag)
        rows.append('<p align="center">\n  ' + "\n  ".join(cells) + "\n</p>")
    blocks["WORK"] = "\n\n".join(rows)

    ml_lines = [f"- [{r['name']}]({r['html_url']}): {r.get('description') or 'machine learning project'}"
                for r in own if is_ml(r, keywords)]
    study = []
    for r in forks:
        if is_ml(r, keywords):
            parent = api.json(f"/repos/{r['full_name']}").get("parent") or r
            study.append(f"- [{parent['full_name']}]({parent['html_url']}): {parent.get('description') or ''}".rstrip(": "))
    ml_parts = []
    if ml_lines:
        ml_parts.append("**ML projects**\n\n" + "\n".join(ml_lines))
    if study:
        ml_parts.append("**Studying from**\n\n" + "\n".join(study))
    blocks["ML"] = "\n\n".join(ml_parts)

    if shares:
        src = add("languages.svg", langs_svg(shares))
        blocks["LANGS"] = img_tag(src, "Languages across public repositories: " + ", ".join(f"{n} {p:.1f}%" for n, p in shares), "100%")
    else:
        blocks["LANGS"] = ""

    if weeks:
        src = add("activity.svg", activity_svg(weeks, total))
        blocks["ACTIVITY"] = img_tag(src, f"{total} contributions in the last 12 months", "100%")
    elif (GEN_DIR / "activity.svg").exists():
        files["activity.svg"] = (GEN_DIR / "activity.svg").read_text(encoding="utf-8")
        blocks["ACTIVITY"] = current_block(readme_text, "ACTIVITY")

    links = []
    blog = (user.get("blog") or "").strip()
    if blog:
        links.append(("Website", blog if re.match(r"https?://", blog) else "https://" + blog))
    for s in socials:
        label = SOCIAL_LABELS.get(s.get("provider", ""), "") or re.sub(r"^https?://(www\.)?", "", s["url"]).split("/")[0]
        links.append((label, s["url"]))
    if user.get("twitter_username") and not any(label == "X" for label, _ in links):
        links.append(("X", f"https://x.com/{user['twitter_username']}"))
    if user.get("email"):
        links.append(("Email", f"mailto:{user['email']}"))
    first_name = cfg["name"].split()[0]
    links.append(("Say hello in an issue", f"https://github.com/{login}/{login}/issues/new?title=Hello%20{first_name}"))
    blocks["CONTACT"] = " · ".join(f"[{label}]({url})" for label, url in links)

    new_text = readme_text
    for key, body in blocks.items():
        new_text = replace_block(new_text, key, body)

    # Only touch the repo (and the "updated" date) when something really changed
    old_files = {p.name: p.read_text(encoding="utf-8") for p in GEN_DIR.glob("*.svg")} if GEN_DIR.exists() else {}

    def without_updated(t: str) -> str:
        return re.sub(r"<!-- UPDATED:START -->.*?<!-- UPDATED:END -->", "", t, flags=re.S)

    if old_files == files and without_updated(new_text) == without_updated(readme_text):
        print("No changes.")
        return 0

    now = dt.datetime.now(tz)
    today = f"{now.day} {now:%b %Y}"
    new_text = replace_block(new_text, "UPDATED", f"<sub>Updated automatically from live GitHub data on {today}.</sub>")

    GEN_DIR.mkdir(exist_ok=True)
    for name in set(old_files) - set(files):
        (GEN_DIR / name).unlink()
    for name, svg in files.items():
        (GEN_DIR / name).write_text(svg, encoding="utf-8", newline="\n")
    README.write_text(new_text, encoding="utf-8", newline="\n")
    print(f"Updated {len(files)} graphics and README for {len(cards)} projects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
