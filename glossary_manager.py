"""
Glossary management for the Web Novel Translator.

The glossary is a local JSON file that tracks how proper nouns, skills,
and locations should be rendered in English. It's injected into every
translation prompt so the model stays consistent chapter-to-chapter, and
the model is asked to propose new entries as it encounters them -- this
is the "first pass" learning the project spec calls for. New entries get
merged in after every chapter, so by the time you re-translate or reach
later chapters, names are already locked in.

Structure of glossary.json:

{
    "characters": {
        "<original term>": {"translation": "...", "notes": "..."}
    },
    "locations": {...},
    "skills_and_items": {...},
    "terms": {...}          # catch-all: titles, factions, recurring idioms, etc.
}
"""

import json
from pathlib import Path
from typing import Any, Dict, List

CATEGORIES = ["characters", "locations", "skills_and_items", "terms"]

_CATEGORY_LABELS = {
    "characters": "Characters",
    "locations": "Locations",
    "skills_and_items": "Skills & Items",
    "terms": "Other Terms",
}


class GlossaryManager:
    """Loads, queries, updates, and persists the shared glossary."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: Dict[str, Dict[str, Dict[str, str]]] = self._load()
        # Populated whenever add_entries() sees a term already on file
        # with a different proposed translation -- surfaced to the user
        # so they can manually resolve it instead of silently drifting.
        self.conflicts: List[Dict[str, str]] = []

    # -- persistence --------------------------------------------------

    def _load(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = {}
        # Make sure every expected category exists even for a fresh file.
        for category in CATEGORIES:
            raw.setdefault(category, {})
        return raw

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2, sort_keys=True)

    # -- reading --------------------------------------------------------

    def is_empty(self) -> bool:
        return all(len(self.data[c]) == 0 for c in CATEGORIES)

    def as_prompt_text(self) -> str:
        """Render the glossary as plain text suitable for injection into
        the translator's system prompt."""
        if self.is_empty():
            return ""

        sections = []
        for category in CATEGORIES:
            entries = self.data.get(category, {})
            if not entries:
                continue
            lines = [f"## {_CATEGORY_LABELS[category]}"]
            for original, info in sorted(entries.items()):
                translation = info.get("translation", "")
                notes = info.get("notes", "")
                line = f"- {original} -> {translation}"
                if notes:
                    line += f"  ({notes})"
                lines.append(line)
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    # -- writing ----------------------------------------------------------

    def add_entries(self, glossary_additions: Dict[str, List[Dict[str, str]]]) -> int:
        """Merge glossary entries proposed by the LLM for one chapter.

        Existing entries are never silently overwritten -- if the model
        proposes a different translation for a term already on file, it's
        recorded in self.conflicts instead so a human can decide, and the
        original on-file translation is kept (this is what future prompts
        will keep using, which is what preserves consistency).

        Returns the number of genuinely new entries added.
        """
        added_count = 0
        if not glossary_additions:
            return added_count

        for category in CATEGORIES:
            proposed_list = glossary_additions.get(category) or []
            for entry in proposed_list:
                original = (entry.get("original") or "").strip()
                translation = (entry.get("translation") or "").strip()
                notes = (entry.get("notes") or "").strip()
                if not original or not translation:
                    continue  # malformed entry from the model; skip it

                existing = self.data[category].get(original)
                if existing is None:
                    self.data[category][original] = {
                        "translation": translation,
                        "notes": notes,
                    }
                    added_count += 1
                elif existing.get("translation") != translation:
                    self.conflicts.append(
                        {
                            "category": category,
                            "original": original,
                            "existing_translation": existing.get("translation", ""),
                            "proposed_translation": translation,
                        }
                    )
                # else: identical to what's already on file -- nothing to do.

        return added_count

    def pop_conflicts(self) -> List[Dict[str, str]]:
        """Return and clear any conflicts recorded since the last call."""
        conflicts, self.conflicts = self.conflicts, []
        return conflicts

    def stats(self) -> Dict[str, int]:
        return {category: len(self.data[category]) for category in CATEGORIES}
