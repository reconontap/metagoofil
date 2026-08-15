"""Browser-based Google discovery for metagoofil.

Google now serves scraper clients a JS-only shell (or a 429 -> /sorry CAPTCHA), so the
original `googlesearch` HTML scraping returns nothing. This module drives a real, headed
Chromium via Playwright: it runs metagoofil's `filetype:<ext> site:<domain>` dork, PAUSES
for the user to solve any CAPTCHA that Google shows, then scrapes the rendered result page
for direct document URLs. The browser is opened once and reused across all filetypes, so a
run needs at most one manual solve.

The URL-extraction and challenge-detection logic lives in the two module-level pure
functions below and is unit-tested; the browser driving itself needs a display + TTY and is
verified manually (see USAGE.md).
"""

import os
from time import sleep
from urllib.parse import urlparse, urlunparse, parse_qs, quote_plus

from bs4 import BeautifulSoup


CHALLENGE_MARKERS = (
    "unusual traffic",
    "recaptcha",
    "our systems have detected",
    'id="captcha-form"',
)


def is_challenge(url, html):
    """True if the page is a Google bot-challenge (CAPTCHA / "unusual traffic") page."""
    u = (url or "").lower()
    h = (html or "").lower()
    if "/sorry/" in u:
        return True
    return any(marker in h for marker in CHALLENGE_MARKERS)


def _unwrap_redirect(href):
    """Return the real target of a Google `/url?q=<real>` redirect, else href unchanged."""
    parsed = urlparse(href)
    if parsed.path == "/url" or parsed.path.endswith("/url"):
        params = parse_qs(parsed.query)
        for key in ("q", "url"):
            if params.get(key):
                return params[key][0]
    return href


def _domain_matches(netloc, domain):
    """True if host is `domain` or a subdomain of it (matching the `site:` operator)."""
    host = netloc.lower().split(":")[0]
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def extract_document_urls(html, domain, ext):
    """Extract direct document URLs from a rendered Google results page.

    Keeps only links whose host is `domain` (or a subdomain) AND whose path ends in
    `.<ext>`, unwrapping `/url?q=` redirects. Order-preserving dedup.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    ext = ext.lower().lstrip(".")
    suffix = "." + ext
    out = []
    seen = set()
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        url = _unwrap_redirect(href)
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if not _domain_matches(parsed.netloc, domain):
            continue
        if not parsed.path.lower().endswith(suffix):
            continue
        # Drop the #fragment: it's never sent to the server, so `report.pdf` and
        # `report.pdf#:~:text=...` (Google's scroll-to-text anchor) are the same document.
        # Keep the query -- it may be required to fetch the file.
        normalized = urlunparse(parsed._replace(fragment=""))
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


class BrowserUnavailable(Exception):
    """Raised when Chromium cannot be launched (e.g. Playwright's browser isn't installed)."""


# Common Chromium binary locations on Kali / Debian, tried before Playwright's bundled one.
_SYSTEM_CHROMIUM = ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome")


class GoogleBrowserSearch:
    """Drive a headed Chromium to run metagoofil's Google dorks, pausing for CAPTCHAs.

    Open the browser once (persistent profile so a solved challenge's cookies survive across
    runs), then call `search_filetype()` per filetype. Call `close()` when done.
    """

    SEARCH_URL = "https://www.google.com/search?q={query}&num=100&start={start}"

    def __init__(self, headless=False, profile_dir=None, page_timeout=30, jitter=1.0, max_pages=10):
        self.headless = headless
        self.profile_dir = profile_dir or os.path.expanduser("~/.metagoofil/profile")
        self.page_timeout = page_timeout
        self.jitter = jitter
        self.max_pages = max_pages
        self._pw = None
        self._ctx = None
        self._page = None

    def search_filetype(self, domain, ext, max_results):
        """Return up to `max_results` direct document URLs for `filetype:<ext> site:<domain>`."""
        query = "filetype:{ext} site:{domain}".format(ext=ext, domain=domain)
        results = []
        seen = set()
        for page_index in range(self.max_pages):
            if len(results) >= max_results:
                break
            url = self.SEARCH_URL.format(query=quote_plus(query), start=page_index * 100)
            try:
                current_url, html = self._fetch(url)
            except BrowserUnavailable:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print("[-] Browser fetch failed ({}): {}".format(ext, e))
                break

            if is_challenge(current_url, html):
                self._prompt_solve()
                try:
                    current_url, html = self._fetch(url)
                except Exception as e:
                    print("[-] Browser fetch failed after challenge ({}): {}".format(ext, e))
                    break

            new = 0
            for doc_url in extract_document_urls(html, domain, ext):
                if doc_url not in seen:
                    seen.add(doc_url)
                    results.append(doc_url)
                    new += 1
            if new == 0:
                break
            sleep(self.jitter)

        return results[:max_results]

    def _prompt_solve(self):
        print(
            "[!] Google is showing a CAPTCHA / 'unusual traffic' page.\n"
            "    Solve it in the browser window, then press [Enter] here to continue..."
        )
        try:
            input()
        except EOFError:
            # No TTY (e.g. piped/non-interactive) -- nothing to wait on; carry on so the
            # caller still gets whatever the page yields instead of hanging.
            pass

    def _fetch(self, url):
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=int(self.page_timeout * 1000))
        page.wait_for_timeout(1200)
        return page.url, page.content()

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from e

        self._pw = sync_playwright().start()
        os.makedirs(self.profile_dir, exist_ok=True)
        # No user_agent override: a stale/hardcoded UA both triggers Chrome's own
        # "known security issue" banner and is itself a bot signal (DialBack lesson). Let
        # Chromium report its real, current UA.
        launch_kwargs = dict(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--disable-infobars"],
        )
        for path in _SYSTEM_CHROMIUM:
            if os.path.exists(path):
                launch_kwargs["executable_path"] = path
                break
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(self.profile_dir, **launch_kwargs)
        except Exception as e:
            raise BrowserUnavailable(
                "Could not launch Chromium: {}. Install it with: playwright install chromium".format(e)
            ) from e
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self._page

    def close(self):
        for closer in (
            lambda: self._ctx.close() if self._ctx else None,
            lambda: self._pw.stop() if self._pw else None,
        ):
            try:
                closer()
            except Exception:
                pass
        self._ctx = self._pw = self._page = None

