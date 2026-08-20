#!/usr/bin/env python

# Standard Python libraries.
import argparse
import os
import queue
import random
import sys
import threading
import time
import urllib


# Third party Python libraries.
import requests

# Local module: browser-based Google discovery. The original googlesearch HTML scraping is
# dead -- Google now serves scraper clients a JS-only shell / 429 CAPTCHA, so it returned 0
# results. browser_search drives a headed Chromium and pauses for the user to solve the
# CAPTCHA. See browser_search.py and docs/superpowers/specs/.
import browser_search

# https://stackoverflow.com/questions/27981545/suppress-insecurerequestwarning-unverified-https-request-is-being-made-in-pytho
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


__version__ = "1.4.0"


class DownloadWorker(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)

    def run(self):
        while True:
            # Grab URL off the queue.
            url = mg.queue.get()

            try:
                headers = {}

                # Assign a User-Agent for each file request.
                # No -u
                if mg.user_agent is None:
                    user_agent_choice = random.choice(mg.random_user_agents).strip()
                    headers["User-Agent"] = f"{user_agent_choice}"
                # -u "My custom user agent 2.0"
                else:
                    headers["User-Agent"] = mg.user_agent

                response = requests.get(
                    url,
                    headers=headers,
                    verify=False,
                    timeout=mg.url_timeout,
                    stream=True,
                )

                # Download the file.
                if response.status_code == 200:
                    try:
                        size = int(response.headers["Content-Length"])

                    except KeyError as e:
                        print(
                            f"[-] Exception for url: {url} -- {e} does not exist. Extracting file size from "
                            "response.content length."
                        )
                        size = len(response.content)

                    mg.total_bytes += size

                    # Strip any trailing /'s before extracting file name. Use response.url in case there were HTTP
                    # 301/302 redirects.
                    url_file_name = str(response.url.strip("/").split("/")[-1])

                    # Decode URL file name if it's encoded. No harm calling urllib.parse.unquote() if the URL file
                    # name isn't URL encoded.
                    filename = urllib.parse.unquote(url_file_name, encoding="utf-8")

                    print(f'[+] Downloading "{filename}" [{size} bytes] from: {response.url}')

                    with open(os.path.join(mg.save_directory, filename), "wb") as fh:
                        for chunk in response.iter_content(chunk_size=1024):
                            if chunk:  # Filter out keep-alive new chunks.
                                fh.write(chunk)

                else:
                    print(f"[-] URL {url} returned HTTP code {response.status_code}")

            except requests.exceptions.RequestException as e:
                print(f"[-] Exception for url: {url} -- {e}")

            mg.queue.task_done()


class Metagoofil:
    """The Metagoofil Class"""

    def __init__(
        self,
        domain,
        delay,
        save_links,
        url_timeout,
        search_max,
        download_file_limit,
        save_directory,
        number_of_threads,
        file_types,
        user_agent,
        download_files,
        search_engine,
        headless,
    ):
        self.domain = domain
        self.delay = delay
        self.save_links = open(save_links, "a") if save_links else None
        self.url_timeout = url_timeout
        self.search_max = search_max
        self.download_file_limit = download_file_limit
        self.save_directory = save_directory

        # Create queue and specify the number of worker threads.
        self.queue = queue.Queue()
        self.number_of_threads = number_of_threads

        self.file_types = file_types

        self.user_agent = user_agent
        # Populate a list of random User-Agents.
        if self.user_agent is None:
            with open("user_agents.txt") as fp:
                self.random_user_agents = fp.readlines()

        self.download_files = download_files
        self.total_bytes = 0

        # Discovery engine. Currently only the headed-browser "google" engine is supported
        # (it pauses for the user to solve Google's CAPTCHA). Chromium is launched lazily on
        # the first search, so constructing this is cheap.
        self.search_engine = search_engine
        self.headless = headless
        self.engine = browser_search.GoogleBrowserSearch(headless=headless)

    def go(self):
        # Kickoff the threadpool.
        for i in range(self.number_of_threads):
            thread = DownloadWorker()
            thread.daemon = True
            thread.start()

        if "ALL" in self.file_types:
            from itertools import product
            from string import ascii_lowercase

            # Generate all three letter combinations.
            self.file_types = ["".join(i) for i in product(ascii_lowercase, repeat=3)]

        try:
            for filetype in self.file_types:
                # Stores URLs with files, clear out for each filetype.
                self.files = []

                # Search for the files to download via the browser engine. The window opens
                # once (on the first filetype) and is reused, so the user solves at most one
                # CAPTCHA for the whole run.
                print(f"[*] Searching Google for .{filetype} files on {self.domain} (browser engine)")
                try:
                    self.files = self.engine.search_filetype(self.domain, filetype, self.search_max)
                except browser_search.BrowserUnavailable as e:
                    print(f"[-] {e}")
                    sys.exit(1)
                except KeyboardInterrupt:
                    print("\n[*] Search interrupted by user.")
                    break

                # Safety net: never exceed the requested amount.
                if len(self.files) > self.search_max:
                    self.files = self.files[: self.search_max]

                # Download files if specified with -w switch.
                if self.download_files:
                    self.download()

                # Otherwise, just display them.
                else:
                    print(f"[*] Results: {len(self.files)} .{filetype} files found")
                    for file_name in self.files:
                        print(file_name)

                # Save links to output to file.
                if self.save_links:
                    for f in self.files:
                        self.save_links.write(f"{f}\n")
        finally:
            # Always tear down Chromium, even on Ctrl-C or an unexpected error.
            self.engine.close()

        if self.save_links:
            self.save_links.close()

        if self.download_files:
            print(
                "[+] Total download: {} bytes / {:.2f} KB / {:.2f} MB".format(
                    self.total_bytes, self.total_bytes / 1024, self.total_bytes / (1024 * 1024)
                )
            )

    def download(self):
        self.counter = 1
        for url in self.files:
            # download_file_limit is None => download every file found (bounded by -l).
            if self.download_file_limit is None or self.counter <= self.download_file_limit:
                self.queue.put(url)
                self.counter += 1

        self.queue.join()


def get_timestamp():
    now = time.localtime()
    timestamp = time.strftime("%Y%m%d_%H%M%S", now)
    return timestamp


def resolve_download_options(save_directory, download_files):
    """Decide whether to download and where, from the raw -o / -w values.

    Rules (see USAGE.md):
      * -o <dir> given  -> download into <dir>  (i.e. -o implies download)
      * -w but no -o    -> download into ./data
      * neither         -> list results only, no directory
    Returns (download_files, save_directory).
    """
    if save_directory is not None:
        download_files = True
    elif download_files:
        save_directory = "./data"
    return download_files, save_directory


def csv_list(string):
    return string.split(",")


# http://stackoverflow.com/questions/3853722/python-argparse-how-to-insert-newline-in-the-help-text
class SmartFormatter(argparse.HelpFormatter):
    def _split_lines(self, text, width):
        if text.startswith("R|"):
            return text[2:].splitlines()
        # This is the RawTextHelpFormatter._split_lines
        return argparse.HelpFormatter._split_lines(self, text, width)


def positive_int(value):
    try:
        value_int = int(value)
        assert value_int >= 0
        return value_int
    except (AssertionError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid value '{value}', must be an int >= 0")


def positive_float(value):
    try:
        value_float = float(value)
        assert value_float >= 0
        return value_float
    except (AssertionError, ValueError):
        raise argparse.ArgumentTypeError(f"invalid value '{value}', must be a float >= 0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Metagoofil v{__version__} - Search Google and download specific file types.",
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        "-d",
        dest="domain",
        action="store",
        required=True,
        help="Domain to search.",
    )
    parser.add_argument(
        "-e",
        dest="delay",
        action="store",
        type=positive_float,
        default=30.0,
        help=(
            "Legacy flag, accepted for backward compatibility. Under the browser engine you "
            "pace Google yourself by solving the CAPTCHA, so this delay no longer spaces "
            "searches. Default: 30.0"
        ),
    )
    parser.add_argument(
        "-f",
        nargs="?",
        metavar="SAVE_FILE",
        dest="save_links",
        action="store",
        default=False,
        help="R|Save the html links to a file.\n"
        "no -f = Do not save links\n"
        "-f = Save links to html_links_<TIMESTAMP>.txt\n"
        "-f SAVE_FILE = Save links to SAVE_FILE",
    )
    parser.add_argument(
        "-i",
        dest="url_timeout",
        action="store",
        type=positive_int,
        default=15,
        help="Number of seconds to wait before timeout for unreachable/stale pages. Default: 15",
    )
    parser.add_argument(
        "-l",
        dest="search_max",
        action="store",
        type=positive_int,
        default=100,
        help="Maximum results to search. Default: 100",
    )
    parser.add_argument(
        "-n",
        dest="download_file_limit",
        action="store",
        type=positive_int,
        default=None,
        help="Maximum number of files to download PER filetype. Default: all found (bounded by -l).",
    )
    parser.add_argument(
        "-o",
        dest="save_directory",
        action="store",
        default=None,
        help=(
            "Directory to download the found files into. Passing -o implies download and the "
            'directory is created if it does not exist. Default (with -w, no -o): "./data".'
        ),
    )
    parser.add_argument(
        "-r",
        dest="number_of_threads",
        action="store",
        type=positive_int,
        default=8,
        help="Number of downloader threads. Default: 8",
    )
    parser.add_argument(
        "-t",
        dest="file_types",
        action="store",
        type=csv_list,
        required=True,
        help=(
            "file_types to download (pdf,doc,xls,ppt,odp,ods,docx,xlsx,pptx). To search all 17,576 three-letter "
            'file extensions, type "ALL"'
        ),
    )
    parser.add_argument(
        "-u",
        dest="user_agent",
        nargs="?",
        default=None,
        help="R|User-Agent for file retrieval (downloads) against -d domain.\n"
        "The browser discovery engine uses Chromium's own real User-Agent (a fake one is a\n"
        "bot signal), so -u affects downloads only.\n"
        "no -u = Randomize User-Agent (recommended)\n"
        '-u "My custom user agent 2.0" = Your customized User-Agent',
    )
    parser.add_argument(
        "-w",
        dest="download_files",
        action="store_true",
        default=False,
        help="Download the files (into -o, or ./data) instead of just listing them. Implied by -o.",
    )
    parser.add_argument(
        "--search",
        dest="search_engine",
        action="store",
        default="google",
        choices=["google"],
        help=(
            "Discovery engine. Only 'google' (headed browser, pauses for you to solve the "
            "CAPTCHA) is supported. Default: google"
        ),
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=False,
        help=(
            "Run the browser engine headless. NOTE: you cannot solve a CAPTCHA in headless "
            "mode, so a challenged search returns nothing. Default: headed (recommended)."
        ),
    )
    args = parser.parse_args()

    # -o implies download; -w downloads to ./data. Create the target directory if needed.
    args.download_files, args.save_directory = resolve_download_options(
        args.save_directory, args.download_files
    )
    if args.download_files:
        os.makedirs(args.save_directory, exist_ok=True)
        print(f"[*] Downloaded files will be saved here: {args.save_directory}")
    else:
        print("[*] Listing results only — pass -o <dir> (or -w) to download the files.")

    if args.save_links is False:
        args.save_links = None
    elif args.save_links is None:
        args.save_links = f"html_links_{get_timestamp()}.txt"

    # print(vars(args))
    mg = Metagoofil(**vars(args))
    mg.go()

    print("[+] Done!")
