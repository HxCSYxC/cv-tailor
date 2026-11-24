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
    "year", "years", "new", "other", "well", "high", "good",
}


def tailor(cv: dict, job_title: str, job_text: str) -> tuple[dict, list[str]]:
    title = (job_title or "this role").strip()
    keywords, phrases = extract_terms(job_text)
    notes: list[str] = []
    sections: list[dict] = []
    skill_sections: list[dict] = []
    scored_sections: list[tuple[int, dict]] = []
    fallback_sections: list[dict] = []
    best_bullet = ""
    best_score = 0
    matched_terms: list[str] = []

    for section in cv.get("sections", []):
        if section["key"] == "education":
            sections.append(section)
            continue
        if section["key"] == "skills":
            rewritten, moved = _reorder_skills(section, keywords, phrases)
            skill_sections.append(rewritten)
            if moved:
                notes.append("Moved skills that appear in the job description to the front of each skills line.")
            continue
        rewritten, section_score, top_bullet, top_score, detail = _trim_entries(section, keywords, phrases)
        if top_score > best_score and top_bullet:
            best_score = top_score
            best_bullet = top_bullet
        if section_score > 0 and (rewritten["entries"] or rewritten["lines"]):
            scored_sections.append((section_score, rewritten))
            notes.extend(detail)
        elif rewritten["entries"] or rewritten["lines"]:
            fallback_sections.append(rewritten)

    scored_sections.sort(key=lambda item: item[0], reverse=True)
    chosen = [section for _, section in scored_sections] or fallback_sections
    sections.extend(chosen)
    sections.extend(skill_sections)

    evidence = best_bullet or _blob(cv)
    normalized_evidence = normalize(evidence)
    evidence_tokens = set(normalized_evidence.split())
    for phrase in phrases:
        if phrase in normalized_evidence:
            matched_terms.append(_surface(phrase, evidence))
        if len(matched_terms) == 3:
            break
    if len(matched_terms) < 3:
        covered = {piece for term in matched_terms for piece in normalize(term).split()}
        for word in keywords:
            if word in covered:
                continue
            if word in evidence_tokens or any(word in token.split("-") for token in evidence_tokens):
                matched_terms.append(_surface(word, evidence))
            if len(matched_terms) == 3:
                break

    profile = _profile(title, matched_terms, best_bullet, cv.get("profile", ""))
    notes.insert(0, f"Opening line rewritten for {title} using only wording already on the master CV.")
    if matched_terms:
        notes.insert(1, "Terms shared with this job: " + ", ".join(matched_terms) + ".")
    tailored = {
        "name": cv.get("name", ""),
        "contact": cv.get("contact", ""),
        "target": title,
        "profile": profile,
        "sections": sections,
    }
    return tailored, notes


def stem_token(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize(text: str) -> str:
    words = re.findall(r"[a-z0-9][a-z0-9+.#-]{1,}", text.lower())
    return " ".join(stem_token(word) for word in words)


def extract_terms(text: str) -> tuple[list[str], list[str]]:
    words = [stem_token(word) for word in re.findall(r"[a-z0-9][a-z0-9+.#-]{1,}", text.lower())]
    words = [word for word in words if word not in STOPWORDS and not word.isdigit()]
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    keywords = [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))][:40]
    bigrams: dict[str, int] = {}
    for left, right in zip(words, words[1:]):
        if left in STOPWORDS or right in STOPWORDS:
            continue
        phrase = f"{left} {right}"
        bigrams[phrase] = bigrams.get(phrase, 0) + 1
    phrases = [phrase for phrase, _ in sorted(bigrams.items(), key=lambda item: (-item[1], item[0]))[:25]]
    return keywords, phrases


def score_text(text: str, keywords: list[str], phrases: list[str]) -> int:
    lowered = normalize(text)
    total = 0
    for phrase in phrases:
        if phrase in lowered:
            total += 3
    tokens = set(lowered.split())
    for word in keywords:
        if word in tokens or any(word in token.split("-") for token in tokens):
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


def _trim_entries(section: dict, keywords: list[str], phrases: list[str]) -> tuple[dict, int, str, int, list[str]]:
    notes: list[str] = []
    entries = []
    best_bullet = ""
    best_score = 0
    for entry in section.get("entries", []):
        ranked = [(score_text(bullet, keywords, phrases), bullet) for bullet in entry.get("bullets", [])]
        for bullet_score, bullet in ranked:
            if bullet_score > best_score:
                best_score = bullet_score
                best_bullet = bullet
        heading_score = score_text(f"{entry.get('heading', '')} {entry.get('sub', '')}", keywords, phrases)
        matching = [bullet for bullet_score, bullet in sorted(ranked, key=lambda item: item[0], reverse=True) if bullet_score > 0]
        relevant = heading_score >= 2 or any(bullet_score >= 2 for bullet_score, _ in ranked)
        if matching:
            kept = matching[:3]
            if heading_score >= 2:
                for bullet in entry.get("bullets", []):
                    if len(kept) >= 2:
                        break
                    if bullet not in kept:
                        kept.append(bullet)
        elif heading_score >= 2:
            kept = entry.get("bullets", [])[:2]
        else:
            kept = []
        if relevant and entry.get("bullets") and len(kept) != len(entry.get("bullets", [])):
            notes.append(
                f"Under {entry['heading']}, kept {len(kept)} of {len(entry.get('bullets', []))} bullets closest to this job."
            )
        entry_score = heading_score + sum(item[0] for item in ranked)
        if relevant:
            entries.append({**entry, "bullets": kept or entry.get("bullets", []), "_score": entry_score})
        elif entry.get("bullets"):
            entries.append({**entry, "bullets": entry["bullets"][:1], "_score": 0, "_fallback": True})

    real = [entry for entry in entries if not entry.get("_fallback")]
    if real:
        entries = real
    entries.sort(key=lambda entry: entry.get("_score", 0), reverse=True)
    cleaned = [{key: value for key, value in entry.items() if not key.startswith("_")} for entry in entries]
    section_score = max((entry.get("_score", 0) for entry in entries), default=0)
    return (
        {"key": section["key"], "title": section["title"], "entries": cleaned, "lines": section.get("lines", [])},
        section_score,
        best_bullet,
        best_score,
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


def _profile(title: str, terms: list[str], best_bullet: str, original: str) -> str:
    if terms and best_bullet:
        shown = _join(terms[:3])
        clause = best_bullet.rstrip(".")
        return f"For a {title} role, the closest proof is {shown}: {clause}."
    if best_bullet:
        return f"For a {title} role, the closest proof already listed is: {best_bullet.rstrip('.')}."
    if original:
        return original
    return f"Master CV prepared for a {title} role."


def _surface(term: str, text: str) -> str:
    found = re.search(rf"{re.escape(term)}[a-z]*", text, flags=re.IGNORECASE)
    return found.group(0) if found else term


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _blob(cv: dict) -> str:
    chunks = [cv.get("profile", "")]
    for section in cv.get("sections", []):
        chunks.extend(section.get("lines", []))
        for entry in section.get("entries", []):
            chunks.append(entry.get("heading", ""))
            chunks.append(entry.get("sub", ""))
            chunks.extend(entry.get("bullets", []))
    return "\n".join(chunks)
