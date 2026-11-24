"""Build a job-specific CV by selecting and reordering the master CV.

Nothing is added. A bullet, skill, or school that was not on the master CV
cannot appear on the tailored one.
"""

from __future__ import annotations

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


def tailor(cv: dict, job_title: str, job_text: str) -> tuple[dict, list[str]]:
    title = (job_title or "this role").strip()
    keywords, phrases = extract_terms(job_text)
    notes: list[str] = []
    education: list[dict] = []
    experience: list[dict] = []
    skill_sections: list[dict] = []
    scored_sections: list[tuple[int, dict]] = []
    fallback_sections: list[dict] = []

    for section in cv.get("sections", []):
        if section["key"] == "education":
            education.append(section)
            continue
        if section["key"] == "skills":
            rewritten, moved = _reorder_skills(section, keywords, phrases)
            skill_sections.append(rewritten)
            if moved:
                notes.append("Moved skills that appear in the job description to the front of each skills line.")
            continue
        if section["key"] == "experience":
            # Employment history is never dropped or reordered: a missing job reads as a gap.
            rewritten, detail = _trim_experience(section, keywords, phrases)
            experience.append(rewritten)
            notes.extend(detail)
            continue
        rewritten, section_score, detail = _trim_entries(section, keywords, phrases)
        if section_score > 0 and (rewritten["entries"] or rewritten["lines"]):
            scored_sections.append((section_score, rewritten))
            notes.extend(detail)
        elif rewritten["entries"] or rewritten["lines"]:
            fallback_sections.append(rewritten)

    scored_sections.sort(key=lambda item: item[0], reverse=True)
    others = [section for _, section in scored_sections] or fallback_sections
    sections = education + experience + others + skill_sections

    tailored = {
        "name": cv.get("name", ""),
        "contact": cv.get("contact", ""),
        "target": title,
        "profile": cv.get("profile", ""),
        "sections": sections,
    }
    report = coverage(cv, job_text)
    if report["found"]:
        notes.insert(0, "Terms from the job already on your CV: " + ", ".join(report["found"]) + ".")
    if report["missing"]:
        notes.insert(
            1 if report["found"] else 0,
            "Not found on your CV (add them to the master CV only if they are true): "
            + ", ".join(report["missing"])
            + ".",
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


def score_text(text: str, keywords: list[str], phrases: list[str]) -> int:
    lowered = normalize(text)
    padded = f" {lowered} "
    total = 0
    for phrase in phrases:
        if f" {phrase} " in padded:
            total += 3
    for word in keywords:
        if _has_word(word, set(lowered.split())):
            total += 1
    return total


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


def _rank_bullets(bullets: list[str], keywords: list[str], phrases: list[str]) -> list[tuple[int, str]]:
    return [(score_text(bullet, keywords, phrases), bullet) for bullet in bullets]


def _pick_bullets(bullets: list[str], ranked: list[tuple[int, str]], limit: int) -> list[str]:
    """Strongest matching bullets first; untouched order when nothing matches."""
    matching = [bullet for score, bullet in sorted(ranked, key=lambda item: item[0], reverse=True) if score > 0]
    kept = matching[:limit]
    for bullet in bullets:
        if len(kept) >= min(2, len(bullets)):
            break
        if bullet not in kept:
            kept.append(bullet)
    return kept


def _trim_experience(section: dict, keywords: list[str], phrases: list[str]) -> tuple[dict, list[str]]:
    notes: list[str] = []
    entries = []
    for entry in section.get("entries", []):
        bullets = entry.get("bullets", [])
        ranked = _rank_bullets(bullets, keywords, phrases)
        kept = _pick_bullets(bullets, ranked, 4)
        if len(kept) != len(bullets):
            notes.append(f"Under {entry['heading']}, kept {len(kept)} of {len(bullets)} bullets closest to this job.")
        entries.append({**entry, "bullets": kept})
    return {"key": section["key"], "title": section["title"], "entries": entries, "lines": section.get("lines", [])}, notes


def _trim_entries(section: dict, keywords: list[str], phrases: list[str]) -> tuple[dict, int, list[str]]:
    notes: list[str] = []
    entries = []
    for entry in section.get("entries", []):
        bullets = entry.get("bullets", [])
        ranked = _rank_bullets(bullets, keywords, phrases)
        heading_score = score_text(f"{entry.get('heading', '')} {entry.get('sub', '')}", keywords, phrases)
        relevant = heading_score >= 2 or any(score >= 2 for score, _ in ranked)
        entry_score = heading_score + sum(score for score, _ in ranked)
        if relevant:
            kept = _pick_bullets(bullets, ranked, 3)
            if bullets and len(kept) != len(bullets):
                notes.append(f"Under {entry['heading']}, kept {len(kept)} of {len(bullets)} bullets closest to this job.")
            entries.append({**entry, "bullets": kept, "_score": entry_score})
        elif bullets:
            entries.append({**entry, "bullets": bullets[:1], "_score": 0, "_fallback": True})

    real = [entry for entry in entries if not entry.get("_fallback")]
    if real:
        dropped = [entry["heading"] for entry in entries if entry.get("_fallback")]
        if dropped:
            notes.append(f"Left out {', '.join(dropped)} from {section['title'].title()}: nothing in it matched this job.")
        entries = real
    entries.sort(key=lambda entry: entry.get("_score", 0), reverse=True)
    cleaned = [{key: value for key, value in entry.items() if not key.startswith("_")} for entry in entries]
    section_score = max((entry.get("_score", 0) for entry in entries), default=0)
    return (
        {"key": section["key"], "title": section["title"], "entries": cleaned, "lines": section.get("lines", [])},
        section_score,
        notes,
    )


def _reorder_skills(section: dict, keywords: list[str], phrases: list[str]) -> tuple[dict, bool]:
    moved = False
    lines = []
    for line in section.get("lines", []):
        parts = _split_outside_parens(line)
        if len(parts) < 2:
            lines.append(line)
            continue
        ranked = sorted(parts, key=lambda part: score_text(part, keywords, phrases), reverse=True)
        if ranked != parts:
            moved = True
        lines.append(", ".join(ranked))
    return {"key": "skills", "title": section["title"], "entries": [], "lines": lines}, moved


def _split_outside_parens(line: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for char in line:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == "," and depth == 0:
            piece = "".join(buf).strip(" -")
            if piece:
                parts.append(piece)
            buf = []
            continue
        buf.append(char)
    piece = "".join(buf).strip(" -")
    if piece:
        parts.append(piece)
    return parts


def _blob(cv: dict) -> str:
    chunks = [cv.get("profile", "")]
    for section in cv.get("sections", []):
        chunks.extend(section.get("lines", []))
        for entry in section.get("entries", []):
            chunks.append(entry.get("heading", ""))
            chunks.append(entry.get("sub", ""))
            chunks.extend(entry.get("bullets", []))
    return "\n".join(chunks)
