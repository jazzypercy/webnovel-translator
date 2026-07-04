# Web Novel Translator

A small local toolchain that scrapes raw web novel chapters, translates
them into English with Gemini, and keeps a growing glossary so names,
locations, and skills stay consistent across the whole series.

## How it fits together

```
scraper.py            -> pulls chapter HTML, saves raw_chapters/001.txt, 002.txt, ...
glossary_manager.py    -> loads/saves glossary.json, merges new terms the model finds
translator.py          -> talks to Gemini via google-genai, returns translation + new terms
main.py                -> loops raw_chapters/, calls translator, writes output/, updates glossary
config.py              -> all the knobs: model name, rate limits, tone, paths
```

The glossary is what keeps a character called 李明 from becoming "Li Ming"
in chapter 3 and "Lee Ming" in chapter 12. Every chapter's translation
call gets the current glossary injected into its prompt, and the model is
asked to report any new proper nouns / skills / locations it encounters.
Those get merged into `glossary.json` immediately, so by the next
chapter they're already locked in -- this is the "first pass learning"
the glossary needs, it just happens continuously rather than in a
separate offline step.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste in your free key from https://aistudio.google.com/apikey
```

The app reads `GEMINI_API_KEY` from the environment (`.env` is loaded
automatically). No key is ever hardcoded in the source.

## Usage

**1. Scrape chapters**

```bash
# single chapter -- auto-numbered as the next file in raw_chapters/
python scraper.py "https://example-novel-site.com/series/chapter-1"

# a specific chapter number
python scraper.py "https://example-novel-site.com/series/chapter-7" --index 7

# a whole batch from a text file of URLs (one per line)
python scraper.py --url-list urls.txt
```

Scraping arbitrary novel sites is inherently fragile -- markup varies
wildly. `scraper.py` tries a list of common chapter-content selectors and
falls back to "biggest text block on the page." If it grabs the wrong
thing (nav menus, comments, etc.), inspect the page and pass the right
container explicitly:

```bash
python scraper.py "https://..." --selector "div.chapter-content"
```

**2. Translate**

```bash
# translate every chapter in raw_chapters/ that doesn't have output yet
python main.py

# just the next 3 pending chapters (handy for testing before a big batch)
python main.py --limit 3

# a specific range
python main.py --start 1 --end 10

# force re-translation (e.g. after editing the glossary or tone)
python main.py --overwrite
```

Translated chapters land in `output/001.md`, `output/002.md`, etc.
`glossary.json` is updated and saved after every single chapter, so you
can safely `Ctrl+C` mid-run without losing progress -- rerunning `main.py`
picks up where it left off.

## The glossary

`glossary.json` looks like this:

```json
{
  "characters": {
    "李明": {"translation": "Li Ming", "notes": "protagonist, quiet and calculating"}
  },
  "locations": {},
  "skills_and_items": {},
  "terms": {}
}
```

You can hand-edit it at any time -- add entries before translating
chapter 1 if you already know how you want names rendered, or fix a
translation you don't like and it'll be used from then on. If the model
ever proposes a different translation for a term already on file,
`main.py` will print a `[glossary conflict]` warning instead of silently
overwriting it, so you can resolve it deliberately.

## Publishing this on GitHub

- `.gitignore` already excludes `.env` (your API key) and scraped/translated
  chapter content (`raw_chapters/*.txt`, `output/*.md`) -- keep the *code*
  public, keep any actual novel text local. Scraped raw chapters and their
  translations are someone else's copyrighted work, not yours to publish.
- `LICENSE` is MIT -- open the file and replace `[Your Name]` with your
  name (or GitHub handle) before pushing.

## Notes on the free tier

Gemini's free tier enforces low requests-per-minute limits (single
digits to low teens depending on the model and any recent changes on
Google's end -- check https://ai.google.dev/gemini-api/docs/rate-limits
for current numbers). `main.py` sleeps `config.SECONDS_BETWEEN_REQUESTS`
seconds between chapters (7s by default) and retries with exponential
backoff on `429` errors. If you're translating a long backlog, `--limit`
lets you run it in small batches across multiple sessions/days if you
hit the daily request cap.

## Customizing tone

Edit `TRANSLATION_TONE` in `config.py` to steer the model's prose style
-- e.g. more literary, more casual, or matching a specific genre's
conventions. It's injected directly into the system prompt for every
chapter.
