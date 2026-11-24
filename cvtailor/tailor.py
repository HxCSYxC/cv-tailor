"""Build a job-specific CV from the master CV, and report how well it covers the job.

The CV keeps every section, job and bullet. Only wording changes (see rewrite.py),
and nothing that was not on the master CV is added.
"""

from __future__ import annotations

import copy
import re

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "with", "by",
    "from", "at", "as", "is", "are", "be", "this", "that", "these", "those",
    "you", "your", "our", "we", "they", "their", "will", "can", "able", "into",
    "about", "across", "over", "under", "than", "then", "also", "such", "using",
    "use", "used", "work", "working", "role", "roles", "job", "team", "teams",
    "including", "include", "strong", "ability", "skills", "skill", "experience",
    "experienced", "responsible", "requirements", "required", "preferred",
    "plus", "within", "per", "via", "its", "it", "we", "who", "what", "how",
    "year", "years", "new", "other", "well", "high", "good", "need", "needs",
    "someone", "candidate", "candidates", "looking", "seeking", "join", "help",
    "make", "get", "keep", "run", "explain", "ensure", "must", "should", "would",
    "like", "all", "any", "each", "more", "most", "some", "not", "but", "if",
    "so", "do", "does", "has", "have", "had", "was", "were", "been", "being",
    "opportunity", "company", "position", "apply", "applicant", "us", "my", "i",
    "etc", "e.g", "i.e", "based", "related", "relevant", "knowledge",
    "understanding", "familiarity", "proficiency", "proficient", "excellent",
    "great", "day", "days", "time", "full", "part", "level", "minimum",
}

TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*[a-z0-9+#]|[a-z0-9]{2,}")


def tailor(cv: dict, job_title: str, job_text: str, client=None, use_ai: bool | None = None) -> tuple[dict, list[str]]:
    """Return the master CV with the same sections, entries and bullets, reworded for one job.

    Nothing is removed or reordered. With an Anthropic key, Claude rewords the summary and
    bullets; without one the CV is returned unchanged with a report of the job's terms.
    """
    from cvtailor import rewrite

    title = (job_title or "this role").strip()
    notes: list[str] = []
    if use_ai is None:
        use_ai = client is not None or rewrite.available()
    if use_ai:
        body, changes, extra = rewrite.rewrite(cv, title, job_text, client=client)
        notes.extend(extra)
        if changes:
            notes.insert(0, f"Claude reworded {len(changes)} line(s) for {title}. Sections, jobs and bullets are the same as your master CV.")
        elif not extra:
            notes.insert(0, "Claude found no lines that needed rewording for this job.")
    else:
        body, changes = copy.deepcopy(cv), []
        notes.append(
            "Your wording was not changed: no Anthropic API key is set. "
            "Start the app with ANTHROPIC_API_KEY set to have Claude reword your CV for each job."
        )
    tailored = {
        "name": body.get("name", ""),
        "contact": body.get("contact", ""),
        "target": title,
        "profile": body.get("profile", ""),
        "sections": body.get("sections", []),
        "changes": changes,
    }
    report = coverage(cv, job_text)
    if report["found"]:
        notes.append("Terms from the job already on your CV: " + ", ".join(report["found"]) + ".")
    if report["missing"]:
        notes.append(
            "Not found on your CV (add them to the master CV only if they are true): "
            + ", ".join(report["missing"])
            + "."
        )
    return tailored, notes


def stem_token(word: str) -> str:
    if "-" in word:
        return "-".join(stem_token(part) for part in word.split("-"))
    if len(word) > 6 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 5 and word.endswith("ed") and not word.endswith("eed"):
        return word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    """Lowercase word tokens; a trailing full stop is never part of a word."""
    return [stem_token(word) for word in TOKEN.findall(text.lower())]


def normalize(text: str) -> str:
    return " ".join(tokens(text))


def extract_terms(text: str) -> tuple[list[str], list[str]]:
    counts: dict[str, int] = {}
    bigrams: dict[str, int] = {}
    # Phrases are only counted inside one sentence or bullet, never across a boundary.
    for chunk in re.split(r"[.;:!?\n•()\[\]]+(?:\s|$)|[\n•;!?()]", text):
        words = [word for word in tokens(chunk) if not word.isdigit()]
        for word in words:
            if word not in STOPWORDS and len(word) > 1:
                counts[word] = counts.get(word, 0) + 1
        for left, right in zip(words, words[1:]):
            if left in STOPWORDS or right in STOPWORDS or left.isdigit() or right.isdigit():
                continue
            phrase = f"{left} {right}"
            bigrams[phrase] = bigrams.get(phrase, 0) + 1
    keywords = [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))][:40]
    phrases = [phrase for phrase, _ in sorted(bigrams.items(), key=lambda item: (-item[1], item[0]))[:25]]
    return keywords, phrases


def coverage(cv: dict, job_text: str) -> dict:
    """Which of the job's key terms the master CV already shows, and which it does not.

    Missing terms are only reported, never added: the user decides whether they are true.
    """
    keywords, phrases = extract_terms(job_text)
    cv_tokens = set(tokens(_blob(cv)))
    cv_norm = " " + normalize(_blob(cv)) + " "
    found: list[str] = []
    missing: list[str] = []
    covered_words: set[str] = set()
    for phrase in phrases:
        if f" {phrase} " in cv_norm:
            found.append(phrase)
            covered_words.update(phrase.split())
    for word in keywords[:25]:
        if word in covered_words:
            continue
        if _has_word(word, cv_tokens):
            found.append(word)
        else:
            missing.append(word)
    surface: dict[str, str] = {}
    for raw in TOKEN.findall(job_text.lower()):
        surface.setdefault(stem_token(raw), raw)
    found = [" ".join(surface.get(part, part) for part in term.split()) for term in found]
    missing = [surface.get(term, term) for term in missing]
    total = len(found) + len(missing)
    percent = round(100 * len(found) / total) if total else 0
    return {"found": found, "missing": missing, "percent": percent}


def _has_word(word: str, cv_tokens: set[str]) -> bool:
    return word in cv_tokens or any(word in token.split("-") for token in cv_tokens)


def infer_title(filename: str, text: str, given: str) -> str:
    if given and given.strip():
        return given.strip()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= 80 and len(line.split()) <= 14:
            return line
        break
    stem = (filename or "role").rsplit(".", 1)[0]
    return stem.replace("_", " ").replace("-", " ").strip() or "Untitled role"


def _blob(cv: dict) -> str:
    chunks = [cv.get("profile", "")]
    for section in cv.get("sections", []):
        chunks.extend(section.get("lines", []))
        for entry in section.get("entries", []):
            chunks.append(entry.get("heading", ""))
            chunks.append(entry.get("sub", ""))
            chunks.extend(entry.get("bullets", []))
    return "\n".join(chunks)
