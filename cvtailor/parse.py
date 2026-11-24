"""Read an uploaded CV into a structure the tailor can reorder."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

SECTION_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("profile", ("career objective", "professional summary", "summary", "profile")),
    ("education", ("education",)),
    ("experience", ("work experience", "professional experience", "employment", "internships", "experience")),
    ("projects", ("personal projects", "selected projects", "projects")),
    ("leadership", ("leadership & activities", "leadership and activities", "extracurricular", "activities", "leadership")),
    ("skills", ("skills & interests", "skills and interests", "technical skills", "skills")),
)


def text_from_upload(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _pdf_text(data)
    if name.endswith(".docx"):
        return _docx_text(data)
    if name.endswith(".html") or name.endswith(".htm"):
        return html_to_text(data.decode("utf-8", errors="replace"))
    return data.decode("utf-8", errors="replace")


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines: list[str] = []
    for paragraph in root.iter(ns + "p"):
        parts: list[str] = []
        for node in paragraph.iter(ns + "t"):
            if node.text:
                parts.append(node.text)
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|head).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|h1|h2|h3|tr|section)>", "\n", raw)
    raw = re.sub(r"(?i)<li[^>]*>", "\n• ", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = (
        raw.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&#8211;", "–")
        .replace("&ndash;", "–")
        .replace("&mdash;", "—")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_cv(text: str) -> dict:
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    name = ""
    contact = ""
    start = 0
    if lines and header_key(lines[0]) is None:
        name = lines[0]
        start = 1
        contact_lines = []
        while start < len(lines) and header_key(lines[start]) is None and _looks_like_contact(lines[start]):
            contact_lines.append(lines[start].lstrip("· ").strip())
            start += 1
        contact = " · ".join(contact_lines)

    sections: list[dict] = []
    current: dict | None = None
    intro: list[str] = []
    for line in lines[start:]:
        key = header_key(line)
        if key:
            current = {"key": key, "title": _display_header(line), "entries": [], "lines": []}
            sections.append(current)
            continue
        if current is None:
            intro.append(line)
            continue
        _add_line(current, line)

    profile = " ".join(intro).strip()
    kept: list[dict] = []
    for section in sections:
        if section["key"] == "profile":
            profile = " ".join(section["lines"]).strip() or profile
            continue
        kept.append(section)
    return {"name": name, "contact": contact, "profile": profile, "sections": kept}


def header_key(line: str) -> str | None:
    collapsed = _collapse_tracked_caps(line).lower()
    collapsed = re.sub(r"[^a-z&+ ]", "", collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()
    if len(collapsed) > 40:
        return None
    for key, aliases in SECTION_ALIASES:
        for alias in aliases:
            if collapsed == alias:
                return key
    return None


def _add_line(section: dict, line: str) -> None:
    if _is_bullet(line):
        bullet = _strip_bullet(line)
        if section["entries"]:
            section["entries"][-1]["bullets"].append(bullet)
        else:
            section["lines"].append(bullet)
        return
    if section["entries"]:
        last = section["entries"][-1]
        if last["bullets"] and line[:1].islower():
            last["bullets"][-1] = f"{last['bullets'][-1]} {line}"
            return
        if not last["bullets"]:
            last["sub"] = f"{last['sub']} · {line}".strip(" ·") if last["sub"] else line
            return
    if section["key"] in {"experience", "projects", "leadership"}:
        section["entries"].append({"heading": line, "sub": "", "bullets": []})
        return
    section["lines"].append(line)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _collapse_tracked_caps(line: str) -> str:
    parts = line.split()
    if len(parts) >= 4 and all(len(part) <= 3 for part in parts) and line.upper() == line:
        return "".join(parts)
    return line


def _display_header(line: str) -> str:
    collapsed = _collapse_tracked_caps(line)
    if collapsed != line:
        return collapsed.title().replace("&", "&")
    return line


def _looks_like_contact(line: str) -> bool:
    lowered = line.lower()
    return "@" in line or "linkedin.com" in lowered or "github.com" in lowered or "|" in line or "·" in line


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^([•\-\*\u2013\u2014]|\d+\.)\s+", line))


def _strip_bullet(line: str) -> str:
    return re.sub(r"^([•\-\*\u2013\u2014]|\d+\.)\s+", "", line).strip()
