"""
Orchestrator for the Web Novel Translator.

Loops through raw_chapters/, translates each chapter that doesn't
already have output, updates and persists the glossary after every
chapter, and writes the translated text to output/.

Usage:
    python main.py                     # translate every pending chapter
    python main.py --start 5 --end 10  # translate a specific range
    python main.py --overwrite         # re-translate chapters that already have output
    python main.py --limit 3           # translate at most 3 chapters this run
"""

import argparse
import sys
import time
from pathlib import Path
from typing import List

import config
from glossary_manager import GlossaryManager
import translator


def find_chapter_files(raw_dir: Path, start: int = None, end: int = None) -> List[Path]:
    """Return raw chapter files in numeric order, optionally filtered to
    a [start, end] inclusive range of chapter numbers."""
    files = []
    for f in sorted(raw_dir.glob("*.txt")):
        try:
            num = int(f.stem)
        except ValueError:
            print(f"  [skip] {f.name} doesn't look like a numbered chapter file, ignoring.")
            continue
        if start is not None and num < start:
            continue
        if end is not None and num > end:
            continue
        files.append(f)
    return sorted(files, key=lambda p: int(p.stem))


def output_path_for(chapter_file: Path, output_dir: Path) -> Path:
    return output_dir / f"{chapter_file.stem}{config.OUTPUT_EXTENSION}"


def translate_all(
    raw_dir: Path,
    output_dir: Path,
    glossary: GlossaryManager,
    start: int = None,
    end: int = None,
    overwrite: bool = False,
    limit: int = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    chapter_files = find_chapter_files(raw_dir, start=start, end=end)

    if not chapter_files:
        print(f"No numbered .txt chapter files found in {raw_dir}/. "
              f"Run scraper.py first, or drop files in named like 001.txt, 002.txt, ...")
        return

    pending = []
    for chapter_file in chapter_files:
        out_path = output_path_for(chapter_file, output_dir)
        if out_path.exists() and not overwrite:
            continue
        pending.append(chapter_file)

    if limit is not None:
        pending = pending[:limit]

    if not pending:
        print("Nothing to do -- every chapter already has translated output. "
              "Pass --overwrite to re-translate.")
        return

    print(f"Translating {len(pending)} chapter(s) with model '{config.MODEL_NAME}'...\n")

    for i, chapter_file in enumerate(pending, start=1):
        chapter_num = chapter_file.stem
        print(f"[{i}/{len(pending)}] Chapter {chapter_num} ({chapter_file.name})")

        raw_text = chapter_file.read_text(encoding="utf-8").strip()
        if not raw_text:
            print(f"  [skip] {chapter_file.name} is empty.")
            continue

        glossary_text = glossary.as_prompt_text()

        try:
            translation, glossary_additions = translator.translate_chapter(raw_text, glossary_text)
        except RuntimeError as exc:
            print(f"  [error] Skipping chapter {chapter_num}: {exc}", file=sys.stderr)
            continue

        out_path = output_path_for(chapter_file, output_dir)
        out_path.write_text(translation, encoding="utf-8")
        print(f"  -> wrote {len(translation):,} characters to {out_path}")

        added = glossary.add_entries(glossary_additions)
        if added:
            glossary.save()
            print(f"  -> glossary: {added} new term(s) added (total: {glossary.stats()})")

        for conflict in glossary.pop_conflicts():
            print(
                f"  [glossary conflict] '{conflict['original']}' ({conflict['category']}): "
                f"on file as '{conflict['existing_translation']}', model proposed "
                f"'{conflict['proposed_translation']}'. Kept the on-file version -- "
                f"edit glossary.json by hand if the model's suggestion is actually better."
            )

        # Respect free-tier rate limits between requests.
        if i < len(pending):
            time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    print("\nDone.")


def main():
    parser = argparse.ArgumentParser(description="Translate scraped web novel chapters with Gemini.")
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_CHAPTERS_DIR)
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--glossary", type=Path, default=config.GLOSSARY_PATH)
    parser.add_argument("--start", type=int, default=None, help="First chapter number to include.")
    parser.add_argument("--end", type=int, default=None, help="Last chapter number to include.")
    parser.add_argument("--limit", type=int, default=None, help="Translate at most N chapters this run.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-translate chapters even if output already exists for them.",
    )
    args = parser.parse_args()

    glossary = GlossaryManager(args.glossary)

    translate_all(
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        glossary=glossary,
        start=args.start,
        end=args.end,
        overwrite=args.overwrite,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
