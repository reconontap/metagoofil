"""Unit tests for the pure functions of the browser-based Google discovery engine.

The live browser + captcha flow needs a display and a TTY, so it can't run here; these
tests cover the URL-extraction and challenge-detection logic that all results flow through.
"""

from browser_search import extract_document_urls, is_challenge


# --- extract_document_urls -------------------------------------------------

def test_keeps_direct_document_link_on_domain():
    html = '<a href="https://www.nasa.gov/wp-content/uploads/report.pdf">Report</a>'
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://www.nasa.gov/wp-content/uploads/report.pdf"
    ]


def test_keeps_subdomain_link_matching_site_operator():
    # site:nasa.gov returns results on subdomains like ntrs.nasa.gov
    html = '<a href="https://ntrs.nasa.gov/api/citations/1971/downloads/1971.pdf">x</a>'
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://ntrs.nasa.gov/api/citations/1971/downloads/1971.pdf"
    ]


def test_unwraps_google_url_redirect():
    html = (
        '<a href="/url?q=https://www.nasa.gov/docs/plan.pdf&amp;sa=U&amp;ved=abc">'
        "Plan</a>"
    )
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://www.nasa.gov/docs/plan.pdf"
    ]


def test_rejects_off_domain_link():
    # An ad / unrelated result must be dropped even if it is a .pdf
    html = '<a href="https://adobe.com/reader/promo.pdf">Get Reader</a>'
    assert extract_document_urls(html, "nasa.gov", "pdf") == []


def test_rejects_wrong_extension():
    html = '<a href="https://www.nasa.gov/page-about-the-report">About</a>'
    assert extract_document_urls(html, "nasa.gov", "pdf") == []


def test_rejects_substring_domain_impersonation():
    # notnasa.gov must NOT match nasa.gov
    html = '<a href="https://notnasa.gov/x.pdf">x</a>'
    assert extract_document_urls(html, "nasa.gov", "pdf") == []


def test_extension_match_is_case_insensitive():
    html = '<a href="https://www.nasa.gov/a/report.PDF">R</a>'
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://www.nasa.gov/a/report.PDF"
    ]


def test_keeps_query_but_strips_fragment():
    # The query can be required to fetch the file, but a #fragment is never sent to the
    # server, so it must be dropped from the emitted URL.
    html = '<a href="https://www.nasa.gov/a/report.pdf?emrc=a9d51b#page=2">R</a>'
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://www.nasa.gov/a/report.pdf?emrc=a9d51b"
    ]


def test_dedupes_google_text_fragment_variants():
    # Google appends #:~:text=... scroll-to-text anchors; the plain link and the fragment
    # link are the SAME document and must collapse to one.
    html = (
        '<a href="https://smap.jpl.nasa.gov/files/handbook.pdf">plain</a>'
        '<a href="https://smap.jpl.nasa.gov/files/handbook.pdf#:~:text=On%20the%20cover">frag</a>'
    )
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://smap.jpl.nasa.gov/files/handbook.pdf"
    ]


def test_dedupes_preserving_order():
    html = (
        '<a href="https://www.nasa.gov/b.pdf">b</a>'
        '<a href="https://www.nasa.gov/a.pdf">a</a>'
        '<a href="https://www.nasa.gov/b.pdf">b again</a>'
    )
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://www.nasa.gov/b.pdf",
        "https://www.nasa.gov/a.pdf",
    ]


def test_ignores_google_internal_and_ad_links():
    html = (
        '<a href="https://www.google.com/search?q=next">Next</a>'
        '<a href="https://duckduckgo.com/y.js?ad_domain=x.pdf">ad</a>'
        '<a href="https://accounts.google.com/signin">Sign in</a>'
        '<a href="https://www.nasa.gov/real.pdf">real</a>'
    )
    assert extract_document_urls(html, "nasa.gov", "pdf") == [
        "https://www.nasa.gov/real.pdf"
    ]


def test_docx_filetype():
    html = (
        '<a href="https://acme.com/staff.docx">staff</a>'
        '<a href="https://acme.com/staff.pdf">pdf</a>'
    )
    assert extract_document_urls(html, "acme.com", "docx") == [
        "https://acme.com/staff.docx"
    ]


# --- is_challenge ----------------------------------------------------------

def test_challenge_true_on_sorry_url():
    assert is_challenge("https://www.google.com/sorry/index?continue=x", "<html></html>")


def test_challenge_true_on_recaptcha_marker():
    assert is_challenge("https://www.google.com/search?q=x", "<div>please complete the reCAPTCHA</div>")


def test_challenge_true_on_unusual_traffic_marker():
    html = "<p>Our systems have detected unusual traffic from your computer network.</p>"
    assert is_challenge("https://www.google.com/search?q=x", html)


def test_challenge_true_on_captcha_form_marker():
    assert is_challenge("https://www.google.com/search?q=x", '<form id="captcha-form">')


def test_challenge_false_on_clean_results_page():
    html = '<div id="search"><a href="https://www.nasa.gov/a.pdf">a</a></div>'
    assert not is_challenge("https://www.google.com/search?q=filetype:pdf", html)
