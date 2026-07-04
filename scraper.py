"""
Chapter scraper.

Pulls the raw chapter text from a given URL and saves it as a numbered
text file (e.g. raw_chapters/001.txt) for the translator to pick up.

Because every web novel aggregator/host lays out its HTML differently,
this uses a best-effort strategy: try a list of common content selectors,
and fall back to "the <div>/<article> containing the most text" if none
of them match. You can also pass an explicit CSS selector with
--selector if you know the site's markup.

Usage:
    python scraper.py <url> [--selector "div.chapter-content"] [--index 3]
    python scraper.py --url-list urls.txt
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

import config

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Common container selectors used by popular web novel hosting sites/
# aggregators, roughly in order of how likely they are to be right.
# Tried in order; the first one that yields substantial text wins.
CANDIDATE_SELECTORS = [
    "div.chapter-content",
    "div#chapter-content",
    "div.chapter-inner",
    "div.entry-content",
    "div.reading-content",
    "div.text-left",
    "div#content",
    "article",
    "div.content",
    "main",
]

# Tags to strip out of the matched container before extracting text --
# these are almost never part of the actual chapter body.
JUNK_SELECTORS = [
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "iframe",
    ".ad",
    ".ads",
    ".advertisement",
    ".share",
    ".social",
    ".comments",
    ".related-posts",
]

MIN_CONTENT_CHARS = 300  # below this, a candidate is probably not the chapter body


def fetch_html(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def _clean_container(tag) -> str:
    for junk in JUNK_SELECTORS:
        for el in tag.select(junk):
            el.decompose()
    # Convert <br> and block-level closes into newlines before pulling text,
    # so paragraphs don't get glued together.
    for br in tag.find_all("br"):
        br.replace_with("\n")
    text = tag.get_text(separator="\n")
    # Collapse excessive blank lines / whitespace while keeping paragraph breaks.
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n\n".join(lines)


def extract_chapter_text(html: str, selector: Optional[str] = None) -> str:
    soup = BeautifulSoup(html, "html.parser")

    if selector:
        candidates = soup.select(selector)
        if not candidates:
            raise ValueError(f"No elements matched the provided selector: {selector!r}")
        return _clean_container(candidates[0])

    # Try known selectors first.
    best_text = ""
    for sel in CANDIDATE_SELECTORS:
        for el in soup.select(sel):
            text = _clean_container(el)
            if len(text) > len(best_text):
                best_text = text
        if len(best_text) >= MIN_CONTENT_CHARS:
            return best_text

    # Fallback: pick whichever div/article/section on the page has the
    # most extracted text -- crude, but works surprisingly often.
    for el in soup.find_all(["div", "article", "section"]):
        text = _clean_container(el)
        if len(text) > len(best_text):
            best_text = text

    if len(best_text) < MIN_CONTENT_CHARS:
        raise ValueError(
            "Could not confidently locate the chapter body on this page. "
            "Pass --selector with a CSS selector for the chapter container."
        )
    return best_text


def next_chapter_index(raw_dir: Path) -> int:
    """Find the next free numeric filename in raw_dir (e.g. if 001.txt and
    002.txt exist, returns 3)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    existing = []
    for f in raw_dir.glob("*.txt"):
        match = re.match(r"^(\d+)$", f.stem)
        if match:
            existing.append(int(match.group(1)))
    return (max(existing) + 1) if existing else 1


def save_chapter(text: str, raw_dir: Path, index: int) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{index:03d}.txt"
    out_path = raw_dir / filename
    out_path.write_text(text, encoding="utf-8")
    return out_path


def scrape_one(url: str, raw_dir: Path, selector: Optional[str], index: Optional[int]) -> Path:
    print(f"Fetching {url} ...")
    html = fetch_html(url)
    text = extract_chapter_text(html, selector=selector)
    chapter_index = index if index is not None else next_chapter_index(raw_dir)
    out_path = save_chapter(text, raw_dir, chapter_index)
    print(f"  -> saved {len(text):,} characters to {out_path}")
    return out_path


def load_url_list(path: Path) -> List[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def main():
    parser = argparse.ArgumentParser(description="Scrape web novel chapter(s) into raw_chapters/.")
    parser.add_argument("url", nargs="?", help="Chapter URL to scrape.")
    parser.add_argument(
        "--url-list",
        type=Path,
        help="Path to a text file with one chapter URL per line (scraped in order).",
    )
    parser.add_argument(
        "--selector",
        help="CSS selector for the chapter content container, if auto-detection fails.",
    )
    parser.add_argument(
        "--index",
        type=int,
        help="Explicit chapter number to save as (e.g. 5 -> 005.txt). "
        "Ignored with --url-list, where numbering auto-increments.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=config.RAW_CHAPTERS_DIR,
        help="Directory to save raw chapter .txt files into.",
    )
    args = parser.parse_args()

    if not args.url and not args.url_list:
        parser.error("Provide a URL, or --url-list pointing to a file of URLs.")

    try:
        if args.url_list:
            urls = load_url_list(args.url_list)
            if not urls:
                print("No URLs found in the list file.", file=sys.stderr)
                sys.exit(1)
            for url in urls:
                scrape_one(url, args.raw_dir, args.selector, index=None)
        else:
            scrape_one(args.url, args.raw_dir, args.selector, args.index)
    except (requests.RequestException, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
