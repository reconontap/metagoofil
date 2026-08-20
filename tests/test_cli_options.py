"""Tests for the download/save-directory option resolution.

The user's expectation: passing -o <dir> means "download the found files into <dir>"
(creating it if needed). -w still works for backward compatibility. With neither, the
tool only lists results.
"""

from metagoofil import resolve_download_options


def test_o_alone_implies_download():
    # -o outdir (no -w) -> download into outdir
    assert resolve_download_options("outdir", False) == (True, "outdir")


def test_w_without_o_defaults_to_data():
    # -w (no -o) -> download into ./data
    assert resolve_download_options(None, True) == (True, "./data")


def test_o_and_w_together_use_o():
    assert resolve_download_options("outdir", True) == (True, "outdir")


def test_neither_lists_only():
    # no -o, no -w -> list only, no directory
    assert resolve_download_options(None, False) == (False, None)
