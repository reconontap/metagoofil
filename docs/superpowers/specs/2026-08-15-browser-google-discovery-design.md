# metagoofil — browser-based Google discovery (captcha pause)

**Date:** 2026-08-15
**Tool:** `opsdisk/metagoofil` v1.4.0 (Kali-packaged fork)
**Status:** approved design, direct-TDD implementation

## Problem / root cause

metagoofil discovers documents by scraping Google HTML through Mario Vilas'
`googlesearch` library (`metagoofil.py` → `googlesearch.search("filetype:{ext} site:{domain}")`).
Google now serves scraper clients a **JS-only shell** (or a 429 → `/sorry` CAPTCHA),
so the library's parser (`soup.find(id='search').findAll('a')`) finds nothing.

Reproduced 2026-08-15: `metagoofil.py -d nasa.gov -t pdf` → `Results: 0 .pdf files found`.
Direct probe of `google.com/search?q=filetype:pdf+site:nasa.gov`: HTTP 200, 92 KB,
**1 href total, 0 result links** — confirmed bot-shell.

Latent bug: the error path `except Exception as e: ... if e.code == 429` throws
`AttributeError` for exceptions without `.code`.

## Decision

Per user (2026-08-15): **replace discovery with a headed-browser Google engine that
pauses for the user to solve the CAPTCHA**, then scrapes the real (JS-rendered) results.
No DuckDuckGo/Brave engines, no proxy rotation, direct document URLs only. This mirrors
the browser engine already shipped for the `crosslinked` tool, applying the `DialBack`
user-agent lesson.

Trade-off accepted: discovery now requires a **display + TTY** every run (headed Chromium,
manual solve). Headless/automated runs will not retrieve documents.

## Architecture

New module **`browser_search.py`** (repo root, matching opsdisk's flat layout).

### Pure functions (unit-tested, no network/browser)

- `is_challenge(url, html) -> bool` — True if `/sorry/` in url or any of
  `unusual traffic`, `recaptcha`, `our systems have detected`, `id="captcha-form"` in html.
- `extract_document_urls(html, domain, ext) -> list[str]` — parse rendered DOM, collect
  `<a href>`, unwrap `/url?q=<real>` (and `google.com/url?...`) redirects, keep hrefs whose
  netloc == domain or endswith `.domain` (subdomains, matching `site:`) **and** whose path
  (before `?`/`#`) ends in `.{ext}` (case-insensitive). Dedup preserving order.

### `GoogleBrowserSearch` class

- `__init__(headless=False, profile_dir=~/.metagoofil/profile, page_timeout, jitter, max_pages)`.
- Lazy `launch_persistent_context` of Chromium on first use; **no user_agent override**
  (stale UA = "Chrome vulnerability" banner + bot signal, per DialBack); prefer a system
  `chromium` binary if present; `--disable-blink-features=AutomationControlled`.
  Raise `BrowserUnavailable` with an install hint if Chromium can't launch.
- `search_filetype(domain, ext, max_results) -> list[str]`:
  navigate `google.com/search?q=filetype:{ext}+site:{domain}&num=100&start={n}`,
  paginate by `&start=`; on `is_challenge` → prompt + `input()` wait + re-fetch;
  accumulate `extract_document_urls`; stop at `max_results`, at a page with 0 new links,
  or `max_pages`.
- Browser is opened **once** and reused across all filetypes (solve captcha at most once).
- `close()` tears down context + playwright.

## Integration (`metagoofil.py`)

- Remove `import googlesearch` and the `googlesearch.search(...)` block (incl. the buggy
  429 handler).
- In `Metagoofil.__init__`, build one `GoogleBrowserSearch` (respect `--headless`).
- `go()`'s filetype loop calls `self.engine.search_filetype(domain, filetype, search_max)`;
  `close()` the engine after the loop (try/finally).
- New CLI flags: `--search` (default `google`, forward-compatible) and `--headless`.
- Downstream untouched: `-w` download, `-n` limit, `-r` threads, `-o`, `-f`, `-u`, `-i`, `-e`.

## Dependencies

`requirements.txt`: drop `google==3.0.0`; add `playwright`. Keep `requests` (downloader),
`beautifulsoup4` (extraction). README/USAGE: `playwright install chromium`.

## Testing

- `tests/test_browser_search.py`: `extract_document_urls` (domain match incl. subdomains,
  extension filter, `/url?q=` unwrap, dedup, reject off-domain + wrong-extension + ad/`y.js`)
  and `is_challenge` (positive markers + clean page) against saved HTML fixtures.
- Live browser + captcha path can't be automated (needs display + TTY) — verified manually,
  documented as a known limit (same as crosslinked/DialBack).

## Out of scope

Metadata extraction (opsdisk defers to `exiftool` — unchanged), DuckDuckGo/Brave engines,
proxy rotation, HTML-result crawling.
