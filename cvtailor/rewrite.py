"""Reword the master CV for one job with Claude, without adding facts.

Every section, entry, and bullet stays where it was. Only the wording of the
summary and of each bullet changes. Each rewritten line is checked: if it
brings in a number or a capitalised name that is not already on the master
CV, the original line is kept instead.
"""

from __future__ import annotations

import copy
import json
import os
import re

MODEL = os.environ.get("CV_TAILOR_MODEL", "claude-opus-5-5")

SYSTEM = """You tailor a candidate's CV to one job description by rewording it.

Rules, all of them strict:
- Rewrite each line you are given and return every id exactly once.
- Keep every fact true to the original line. Do not add employers, tools, skills,
  certifications, numbers, dates, results, or responsibilities that the original line
  does not state. Do not make claims stronger than the original.
- You may: use the job description's vocabulary for things the line already says,
  lead with what matters most for this job, tighten wording, and fix grammar.
- Keep each line about the same length as the original, never more than half again as long.
- Keep the candidate's language (British or American spelling) and the CV's tense.
- If a line has nothing relevant to the job, return it unchanged.
- The summary may be refocused on the job, using only facts found elsewhere on the CV."""


def available() -> bool:
    """True when an Anthropic credential is configured for this process."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def rewrite(cv: dict, job_title: str, job_text: str, client=None) -> tuple[dict, list[dict], list[str]]:
    """Return (reworded cv, changes, notes). On any failure the CV comes back unchanged."""
    items = _items(cv)
    if not items:
        return copy.deepcopy(cv), [], []
    try:
        proposed = _ask_claude(cv, items, job_title, job_text, client)
    except Exception as exc:  # noqa: BLE001 - never lose the CV because the API failed
        return copy.deepcopy(cv), [], [f"Claude could not reword this CV ({exc.__class__.__name__}: {exc}). Your original wording was kept."]

    allowed = _fact_tokens(_all_text(cv))
    result = copy.deepcopy(cv)
    changes: list[dict] = []
    rejected = 0
    for item_id, (where, original) in items.items():
        new = (proposed.get(item_id) or "").strip()
        if not new or new == original:
            continue
        if not _keeps_facts(new, original, allowed):
            rejected += 1
            continue
        _set(result, item_id, new)
        changes.append({"where": where, "before": original, "after": new})
    notes = []
    if rejected:
        notes.append(
            f"Kept the original wording of {rejected} line(s) because Claude's version added a number or name not on your CV."
        )
    return result, changes, notes


def _ask_claude(cv: dict, items: dict, job_title: str, job_text: str, client) -> dict[str, str]:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    lines = [{"id": item_id, "where": where, "text": text} for item_id, (where, text) in items.items()]
    prompt = (
        f"<job_title>{job_title}</job_title>\n"
        f"<job_description>\n{job_text}\n</job_description>\n\n"
        f"<full_cv_for_context>\n{_all_text(cv)}\n</full_cv_for_context>\n\n"
        "Reword each of these lines for the job above. Return JSON only.\n"
        f"<lines>\n{json.dumps(lines, ensure_ascii=False, indent=1)}\n</lines>"
    )
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={
            "effort": "medium",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "lines": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                                "required": ["id", "text"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["lines"],
                    "additionalProperties": False,
                },
            },
        },
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("the request was declined")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("the answer was cut off")
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    return {line["id"]: line["text"] for line in data.get("lines", []) if isinstance(line, dict)}


def _items(cv: dict) -> dict[str, tuple[str, str]]:
    items: dict[str, tuple[str, str]] = {}
    if cv.get("profile"):
        items["summary"] = ("Summary", cv["profile"])
    for s, section in enumerate(cv.get("sections", [])):
        if section.get("key") in {"education", "skills"}:
            continue
        for e, entry in enumerate(section.get("entries", [])):
            for b, bullet in enumerate(entry.get("bullets", [])):
                items[f"s{s}e{e}b{b}"] = (entry.get("heading", section.get("title", "")), bullet)
    return items


def _set(cv: dict, item_id: str, text: str) -> None:
    if item_id == "summary":
        cv["profile"] = text
        return
    s, e, b = (int(part) for part in re.findall(r"\d+", item_id))
    cv["sections"][s]["entries"][e]["bullets"][b] = text


def _all_text(cv: dict) -> str:
    chunks = [cv.get("profile", "")]
    for section in cv.get("sections", []):
        chunks.append(section.get("title", ""))
        chunks.extend(section.get("lines", []))
        for entry in section.get("entries", []):
            chunks.extend([entry.get("heading", ""), entry.get("sub", ""), *entry.get("bullets", [])])
    return "\n".join(chunk for chunk in chunks if chunk)


NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
NAME = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][A-Za-z0-9+#&.-]*[A-Za-z0-9+#]|\b[A-Z]{2,}\b")


def _fact_tokens(text: str) -> set[str]:
    return {token.lower() for token in NUMBER.findall(text) + NAME.findall(text)}


def _keeps_facts(new: str, original: str, allowed: set[str]) -> bool:
    """Reject a rewrite that adds a number or a capitalised name not on the CV, or that balloons."""
    if len(new) > max(1.6 * len(original), len(original) + 60):
        return False
    original_numbers = set(NUMBER.findall(original))
    if any(number not in original_numbers for number in NUMBER.findall(new)):
        return False
    return all(name.lower() in allowed for name in NAME.findall(new))
