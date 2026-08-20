# ============================================================
# Usage:
#   python3 search.py --word "XXXX" --max-results 1 --max-chars 3000 --timeout 10 --unicode-start 0x0400 --unicode-end 0x04FF
# ============================================================

import argparse
import re
import sys
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

def scrape(url, max_chars=3000, timeout=10, unicode_start=None, unicode_end=None):
    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout).text
    except requests.RequestException as e:
        print(f"    [scrape error] {url}: {e}", file=sys.stderr)
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        if unicode_start is not None and unicode_end is not None:
            text = "".join(
                c for c in text
                if unicode_start <= ord(c) <= unicode_end or c.isspace()
            )
        return text[:max_chars]
    except Exception as e:
        print(f"    [parse error] {url}: {e}", file=sys.stderr)
        return ""

def search_and_print(word, max_results=10, max_chars=3000, timeout=10, unicode_start=None, unicode_end=None):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(
                query=word,
                region="wt-wt",
                safesearch="moderate",
                max_results=max_results
            ))
    except Exception as e:
        print(f"[search error] query={word!r}: {e}", file=sys.stderr)
        return
    if not results:
        print(f"[search] no results for {word!r}", file=sys.stderr)
        return
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        href = r.get("href", "")
        print(f"\n[{i}] {title}")
        print(href)
        if href:
            print(scrape(
                href,
                max_chars,
                timeout,
                unicode_start,
                unicode_end
            ))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--word", required=True)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--max-chars", type=int, default=3000)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--unicode-start", type=lambda x: int(x, 0))
    parser.add_argument("--unicode-end", type=lambda x: int(x, 0))
    args = parser.parse_args()
    if (args.unicode_start is None) != (args.unicode_end is None):
        parser.error("--unicode-start と --unicode-end は両方指定してください")
    search_and_print(
        args.word,
        args.max_results,
        args.max_chars,
        args.timeout,
        args.unicode_start,
        args.unicode_end
    )

if __name__ == "__main__":
    main()
