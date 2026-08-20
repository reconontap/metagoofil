# metagoofil — Usage (2026 refresh)

metagoofil finds documents (`pdf,doc,xls,ppt,docx,...`) that a domain publishes, using the
Google dork `filetype:<ext> site:<domain>`, and optionally downloads them.

**What changed:** the original discovery scraped Google HTML through the `googlesearch`
library. Google now serves scraper clients a JS-only shell (or a `429 → /sorry` CAPTCHA),
so that returned **0 results**. Discovery has been replaced with a **headed browser engine**:
it opens Chromium, runs the dork, and **pauses for you to solve the CAPTCHA** if Google shows
one, then scrapes the real results. Everything downstream (threaded downloader, output flags)
is unchanged.

## Install

```bash
cd metagoofil
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip setuptools
pip install -r requirements.txt        # requests + beautifulsoup4 + playwright
playwright install chromium            # one-time: the browser binary
```

> Discovery needs a **display** (headed Chromium) and a **TTY** (to press Enter after solving
> the CAPTCHA). On a headless server it can't get documents — run it on a desktop session.

## How it works now

1. Chromium opens **once** and is reused across all filetypes, so you solve **at most one**
   CAPTCHA for the whole run.
2. For each filetype it navigates `google.com/search?q=filetype:<ext>+site:<domain>`,
   paginating with `&start=`.
3. If a CAPTCHA / "unusual traffic" page appears, it prints:
   `Solve it in the browser window, then press [Enter]…` — solve it, press Enter, it continues.
4. It keeps only direct document links on the target domain (and subdomains), drops Google
   `#:~:text=` scroll-to-text duplicate anchors, dedupes, and hands the URLs to the downloader.

A persistent browser profile is stored at `~/.metagoofil/profile`, so a solved challenge's
cookies carry over and later runs are challenged less often.

## Common usage

**List document URLs (no download):**
```bash
python3 metagoofil.py -d nasa.gov -t pdf -l 20
```

**Download every found file into a folder (`-o` implies download and creates the folder):**
```bash
python3 metagoofil.py -d nasa.gov -t pdf -o nasa_docs
```
`-o nasa_docs` creates `nasa_docs/` if missing and downloads all PDFs found (up to `-l`).

**Cap how many are downloaded per filetype with `-n`:**
```bash
python3 metagoofil.py -d nasa.gov -t pdf -l 50 -n 10 -o nasa_docs   # find 50, download 10
```

**Multiple filetypes (one browser session, solve captcha once):**
```bash
python3 metagoofil.py -d acme.com -t pdf,docx,xlsx -o acme_docs
```

## Extract metadata (unchanged design)

This fork intentionally does **not** parse metadata itself — use `exiftool` on the downloads:
```bash
exiftool -r nasa_docs/*.pdf | egrep -i "Author|Creator|Email|Producer|Template|Company" | sort -u
```

## Flags reference (new / changed)

| Flag | Meaning |
|------|---------|
| `-o DIR` | Folder to download the found files into. **Passing `-o` implies download** and `DIR` is created if it doesn't exist. |
| `-w` | Also triggers download; with no `-o` it saves to `./data`. Redundant if you pass `-o`. |
| `-n N` | Max files to download **per filetype**. Default: **all found** (bounded by `-l`). e.g. `-n 10`. |
| `-l N` | Max results to search **per filetype**. Default: 100. Paginates Google in pages of 10. |
| `--search google` | Discovery engine. Only `google` (headed browser, captcha pause) is supported. Default. |
| `--headless` | Run the browser headless. **You cannot solve a CAPTCHA headless**, so a challenged search returns nothing. Not recommended. |
| `-u "UA…"` | User-Agent for **file downloads only**. The browser engine uses Chromium's real UA (a fake one is a bot signal), so `-u` no longer affects discovery. |
| `-e DELAY` | Legacy, accepted for compatibility. You pace Google by solving the CAPTCHA, so it no longer spaces searches. |

Unchanged: `-d` domain, `-t` filetypes, `-r` downloader threads, `-i` download timeout,
`-f` save links.

> **No results / only a few?** Google serves ~10 results per page; the engine paginates until
> it runs out or hits `-l`. If you passed `-o`/`-w` but files show `Connection timed out`, the
> **box can't reach the target host** (proxy/egress) — discovery via Google still worked.

## Notes / limits

- **Requires a desktop session** (headed Chromium + a terminal to press Enter). Won't retrieve
  documents on a pure headless box.
- If Chromium isn't installed you get a clear hint (`playwright install chromium`).
- Google is non-deterministic: sometimes it serves results with no challenge, sometimes it
  challenges. The persistent profile reduces repeat challenges.

## Tests

```bash
python3 -m pytest tests/      # 17 unit tests: URL extraction + challenge detection
```
The live browser + captcha flow needs a display + TTY, so it's verified manually, not in CI.
```
