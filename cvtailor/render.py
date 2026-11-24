"""Turn a tailored CV into Markdown, printable HTML, and PDF."""

from __future__ import annotations

import html
from io import BytesIO


def to_markdown(cv: dict) -> str:
    lines: list[str] = []
    if cv.get("name"):
        lines.append(f"# {cv['name']}")
    if cv.get("contact"):
        lines.append(cv["contact"])
    if cv.get("profile"):
        lines.append("")
        lines.append(cv["profile"])
    for section in cv.get("sections", []):
        lines.append("")
        lines.append(f"## {section['title']}")
        for line in section.get("lines", []):
            lines.append("")
            lines.append(line)
        for entry in section.get("entries", []):
            lines.append("")
            lines.append(f"### {entry['heading']}")
            if entry.get("sub"):
                lines.append(f"*{entry['sub']}*")
            for bullet in entry.get("bullets", []):
                lines.append(f"- {bullet}")
    lines.append("")
    return "\n".join(lines)


def to_html(cv: dict) -> str:
    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{html.escape(cv.get('name') or 'CV')}</title>",
        "<style>",
        "body{font-family:Georgia,serif;color:#1c2430;max-width:760px;margin:32px auto;padding:0 20px;line-height:1.4}",
        "h1{font-size:22px;letter-spacing:.04em;margin:0} .contact{color:#3c4a5c;margin:4px 0 12px}",
        ".target{font-size:14px;color:#10233f;margin:0 0 8px} .profile{background:#f4f7fb;border-left:3px solid #10233f;padding:8px 12px}",
        "h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;border-bottom:1px solid #10233f;padding-bottom:2px;margin:16px 0 6px}",
        "h3{font-size:15px;margin:10px 0 0} .sub{color:#3c4a5c;font-style:italic;margin:0}",
        "ul{margin:4px 0 0;padding-left:18px} li{margin:2px 0}",
        "@media print{body{margin:0;max-width:none}}",
        "</style></head><body>",
    ]
    if cv.get("name"):
        parts.append(f"<h1>{html.escape(cv['name'])}</h1>")
    if cv.get("contact"):
        parts.append(f"<p class='contact'>{html.escape(cv['contact'])}</p>")
    if cv.get("profile"):
        parts.append(f"<p class='profile'>{html.escape(cv['profile'])}</p>")
    for section in cv.get("sections", []):
        parts.append(f"<h2>{html.escape(section['title'])}</h2>")
        for line in section.get("lines", []):
            parts.append(f"<p>{html.escape(line)}</p>")
        for entry in section.get("entries", []):
            parts.append(f"<h3>{html.escape(entry['heading'])}</h3>")
            if entry.get("sub"):
                parts.append(f"<p class='sub'>{html.escape(entry['sub'])}</p>")
            if entry.get("bullets"):
                parts.append("<ul>")
                for bullet in entry["bullets"]:
                    parts.append(f"<li>{html.escape(bullet)}</li>")
                parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)


def to_pdf(cv: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    name = ParagraphStyle("name", fontName="Times-Bold", fontSize=16, leading=19, textColor="#10233f")
    body = ParagraphStyle("body", fontName="Times-Roman", fontSize=10, leading=13)
    head = ParagraphStyle("head", fontName="Times-Bold", fontSize=11, leading=14, textColor="#10233f", spaceBefore=8)
    sub = ParagraphStyle("sub", fontName="Times-Italic", fontSize=10, leading=12, textColor="#3c4a5c")
    story = []
    if cv.get("name"):
        story.append(Paragraph(_pdf_text(cv["name"]), name))
    if cv.get("contact"):
        story.append(Paragraph(_pdf_text(cv["contact"]), body))
    if cv.get("profile"):
        story.append(Spacer(1, 6))
        story.append(Paragraph(_pdf_text(cv["profile"]), body))
    for section in cv.get("sections", []):
        story.append(Paragraph(_pdf_text(section["title"].upper()), head))
        for line in section.get("lines", []):
            story.append(Paragraph(_pdf_text(line), body))
        for entry in section.get("entries", []):
            story.append(Spacer(1, 3))
            story.append(Paragraph(_pdf_text(entry["heading"]), ParagraphStyle("entry", parent=body, fontName="Times-Bold")))
            if entry.get("sub"):
                story.append(Paragraph(_pdf_text(entry["sub"]), sub))
            for bullet in entry.get("bullets", []):
                story.append(Paragraph(_pdf_text(f"• {bullet}"), body))
    doc.build(story)
    return buffer.getvalue()


def _pdf_text(value: str) -> str:
    cleaned = (
        value.replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    return (
        cleaned.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
