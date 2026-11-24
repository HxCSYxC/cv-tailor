"""Local app: remember one CV, and save a different CV for each job description.

Run from this folder:

    python3 app.py

Then open http://127.0.0.1:7860
"""

from __future__ import annotations

import html
import os
import re
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cvtailor.parse import text_from_upload
from cvtailor.store import Store

ROOT = Path(__file__).resolve().parent
STORE = Store(ROOT / "data" / "cv.db")
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "7860"))
MAX_BODY = 6_000_000


class Handler(BaseHTTPRequestHandler):
    server_version = "CVTailor/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._html(_home())
                return
            job = re.fullmatch(r"/job/(\d+)", path)
            if job:
                record = STORE.get_job(int(job.group(1)))
                if record is None:
                    self._html(_page("Job not found", "<p>That job is not saved.</p>"), status=404)
                    return
                self._html(_job_page(record))
                return
            download = re.fullmatch(r"/version/(\d+)\.(md|html|pdf)", path)
            if download:
                filename, payload = STORE.get_version_file(int(download.group(1)), download.group(2))
                types = {"md": "text/markdown; charset=utf-8", "html": "text/html; charset=utf-8", "pdf": "application/pdf"}
                self._bytes(payload, types[download.group(2)], filename)
                return
            self._html(_page("Not found", "<p>That page does not exist.</p>"), status=404)
        except Exception as exc:  # noqa: BLE001 - show a local error instead of a stack page
            self._html(_page("Something went wrong", f"<p>{html.escape(str(exc))}</p>"), status=500)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            fields = _read_form(self)
            if path == "/master":
                upload = fields.get("cv")
                if not upload or not upload.get("data"):
                    raise ValueError("Choose a CV file first.")
                STORE.save_master(upload["filename"] or "cv.txt", upload["data"])
                self._redirect("/")
                return
            if path == "/jobs":
                text, filename = _job_text(fields)
                title = fields.get("title", {}).get("text", "")
                job_id = STORE.add_job(filename, text, title)
                self._redirect(f"/job/{job_id}")
                return
            regen = re.fullmatch(r"/job/(\d+)/regenerate", path)
            if regen:
                STORE.regenerate(int(regen.group(1)))
                self._redirect(f"/job/{regen.group(1)}")
                return
            delete = re.fullmatch(r"/job/(\d+)/delete", path)
            if delete:
                STORE.delete_job(int(delete.group(1)))
                self._redirect("/")
                return
            self._html(_page("Not found", "<p>That action does not exist.</p>"), status=404)
        except ValueError as exc:
            self._html(_page("Check the upload", f"<p>{html.escape(str(exc))}</p><p><a href='/'>Back</a></p>"), status=400)
        except Exception as exc:  # noqa: BLE001
            self._html(_page("Something went wrong", f"<p>{html.escape(str(exc))}</p>"), status=500)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[cv-tailor] {self.address_string()} {fmt % args}")

    def _html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, payload: bytes, content_type: str, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()


def _read_form(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length > MAX_BODY:
        raise ValueError("That file is larger than 6 MB.")
    body = handler.rfile.read(length)
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        parsed = parse_qs(body.decode("utf-8", errors="replace"))
        return {key: {"text": values[0], "data": b"", "filename": ""} for key, values in parsed.items()}
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    fields: dict = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename() or ""
        data = part.get_payload(decode=True) or b""
        fields[name] = {"filename": filename, "data": data, "text": data.decode("utf-8", errors="replace")}
    return fields


def _job_text(fields: dict) -> tuple[str, str]:
    upload = fields.get("jd")
    pasted = (fields.get("pasted") or {}).get("text", "")
    if upload and upload.get("data"):
        return text_from_upload(upload["filename"], upload["data"]).strip(), upload["filename"] or "job-description.txt"
    if pasted and pasted.strip():
        return pasted.strip(), "pasted-description.txt"
    raise ValueError("Upload a job description or paste one.")


def _home() -> str:
    master = STORE.get_master()
    jobs = STORE.list_jobs()
    if master is None:
        master_block = "<p class='muted'>No CV saved yet. Upload one and it stays on this computer.</p>"
    else:
        name = html.escape(master["parsed"].get("name") or master["filename"])
        master_block = (
            f"<p><strong>{name}</strong></p>"
            f"<p class='muted'>Saved from {html.escape(master['filename'])} at {html.escape(master['updated_at'])}. "
            "Uploading again replaces the master CV. Job CVs already saved stay as they are until you regenerate them.</p>"
        )
    cards = []
    for job in jobs:
        cards.append(
            "<article class='card'>"
            f"<h3><a href='/job/{job['id']}'>{html.escape(job['title'])}</a>{_badge(job['match'])}</h3>"
            f"<p class='muted'>Saved {html.escape(job['version_at'])}</p>"
            f"<p><a href='/version/{job['version_id']}.pdf'>PDF</a> · "
            f"<a href='/version/{job['version_id']}.html'>HTML</a> · "
            f"<a href='/version/{job['version_id']}.md'>Markdown</a></p>"
            "</article>"
        )
    job_list = "".join(cards) or "<p class='muted'>No job CV yet. Upload a job description and one is written immediately.</p>"
    disabled = "" if master else "disabled"
    body = f"""
    <div class='grid'>
      <section>
        <h2>Master CV</h2>
        {master_block}
        <form action='/master' method='post' enctype='multipart/form-data'>
          <label>CV file (PDF, Word, HTML, or text)</label>
          <input type='file' name='cv' accept='.pdf,.docx,.html,.htm,.txt,.md' required>
          <button type='submit'>Save CV</button>
        </form>
      </section>
      <section>
        <h2>New job</h2>
        <form action='/jobs' method='post' enctype='multipart/form-data'>
          <label>Role title <span class='muted'>(optional, otherwise taken from the description)</span></label>
          <input type='text' name='title' placeholder='Risk analyst, summer 2027'>
          <label>Job description file</label>
          <input type='file' name='jd' accept='.pdf,.docx,.html,.htm,.txt,.md'>
          <label>Or paste the description</label>
          <textarea name='pasted' rows='8' placeholder='Paste the job posting here'></textarea>
          <button type='submit' {disabled}>Create a CV for this job</button>
        </form>
      </section>
    </div>
    <h2>Saved job CVs</h2>
    {job_list}
    """
    return _page("CV Tailor", body)


def _badge(percent: int | None) -> str:
    if percent is None:
        return ""
    tone = "good" if percent >= 70 else "ok" if percent >= 45 else "low"
    return f" <span class='badge {tone}' title='Share of the job description key terms already on your master CV'>{percent}% match</span>"


def _match_block(match: dict | None) -> str:
    if not match:
        return ""
    found = "".join(f"<li>{html.escape(term)}</li>" for term in match["found"]) or "<li class='muted'>None yet</li>"
    missing = "".join(f"<li>{html.escape(term)}</li>" for term in match["missing"]) or "<li class='muted'>Nothing missing</li>"
    return f"""
    <h3>How well your master CV covers this job{_badge(match['percent'])}</h3>
    <div class='grid'>
      <section><h4>Already on your CV</h4><ul class='terms'>{found}</ul></section>
      <section><h4>Not on your CV</h4><ul class='terms missing'>{missing}</ul>
        <p class='muted'>The app never adds these. If one is true for you, add it to your master CV, save it, then regenerate.</p></section>
    </div>
    """


def _job_page(job: dict) -> str:
    shown = [
        note for note in job["notes"]
        if not (job.get("match") and note.startswith(("Terms from the job already", "Not found on your CV")))
    ]
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in shown) or "<li class='muted'>Nothing reordered or trimmed.</li>"
    stale = ""
    if job["stale"]:
        stale = "<p class='warn'>The master CV changed after this version. Regenerate to apply it.</p>"
    body = f"""
    <p><a href='/'>All CVs</a></p>
    <h2>{html.escape(job['title'])}</h2>
    {stale}
    <p>
      <a href='/version/{job['version_id']}.pdf'>Download PDF</a> ·
      <a href='/version/{job['version_id']}.html'>Download HTML</a> ·
      <a href='/version/{job['version_id']}.md'>Download Markdown</a>
    </p>
    {_match_block(job.get('match'))}
    <h3>What changed</h3>
    <ul>{notes}</ul>
    <form action='/job/{job['id']}/regenerate' method='post' class='inline'>
      <button type='submit'>Regenerate from the current master CV</button>
    </form>
    <form action='/job/{job['id']}/delete' method='post' class='inline' onsubmit="return confirm('Delete this job CV and all its versions?')">
      <button type='submit' class='quiet'>Delete this job CV</button>
    </form>
    <h3>CV</h3>
    <iframe class='sheet' srcdoc='{html.escape(job["html"])}'></iframe>
    <h3>Job description used</h3>
    <pre>{html.escape(job['description'])}</pre>
    """
    return _page(job["title"], body)


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body {{ font-family: "Avenir Next", "Helvetica Neue", sans-serif; margin: 0; background: #f6f7f9; color: #1c2430; }}
  main {{ max-width: 980px; margin: 0 auto; padding: 28px 20px 60px; }}
  h1 {{ margin: 0 0 4px; font-size: 28px; }}
  h2 {{ font-size: 18px; margin: 22px 0 8px; }}
  a {{ color: #1a3f72; }}
  .lede {{ color: #3c4a5c; max-width: 680px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  section, .card {{ background: white; border: 1px solid #e2e6ee; border-radius: 10px; padding: 14px 16px; }}
  label {{ display: block; margin: 10px 0 4px; font-size: 14px; }}
  input[type=text], textarea, input[type=file] {{ width: 100%; box-sizing: border-box; }}
  textarea, input[type=text] {{ border: 1px solid #c9d1de; border-radius: 6px; padding: 8px; font: inherit; }}
  button {{ margin-top: 12px; background: #10233f; color: white; border: 0; border-radius: 6px; padding: 8px 12px; font: inherit; cursor: pointer; }}
  button.quiet {{ background: white; color: #6b3a3a; border: 1px solid #e2c8c8; }}
  button:disabled {{ opacity: .45; cursor: not-allowed; }}
  .muted {{ color: #5c6b7e; font-size: 14px; }}
  .warn {{ background: #fff6e8; border-left: 3px solid #a15c00; padding: 8px 10px; }}
  .badge {{ font-size: 12px; font-weight: 600; border-radius: 999px; padding: 2px 8px; margin-left: 8px; vertical-align: middle; }}
  .badge.good {{ background: #e3f3e8; color: #1d5e33; }}
  .badge.ok {{ background: #fff3dc; color: #7a4a00; }}
  .badge.low {{ background: #fbe5e5; color: #8a2b2b; }}
  h4 {{ margin: 0 0 6px; font-size: 14px; }}
  ul.terms {{ list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px; }}
  ul.terms li {{ background: #eef3fa; border-radius: 6px; padding: 2px 8px; font-size: 14px; }}
  ul.terms.missing li {{ background: #f7eeee; }}
  .sheet {{ width: 100%; height: 720px; border: 1px solid #e2e6ee; background: white; }}
  pre {{ white-space: pre-wrap; background: white; border: 1px solid #e2e6ee; padding: 12px; }}
  form.inline {{ display: inline-block; margin-right: 8px; }}
  @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style></head>
<body><main>
  <h1>CV Tailor</h1>
  <p class="lede">One master CV stays saved on this computer. Each job description produces its own CV. The app keeps every job you have held, puts the bullets that match the job first, and shows which of the job's terms your CV does not cover yet. It does not invent experience.</p>
  {body}
</main></body></html>"""


def main() -> None:
    server = None
    for port in range(PORT, PORT + 20):
        try:
            server = ThreadingHTTPServer((HOST, port), Handler)
            break
        except OSError:
            print(f"Port {port} is already in use, trying {port + 1}.", flush=True)
    if server is None:
        raise SystemExit(f"No free port between {PORT} and {PORT + 19}. Set another with PORT=8000 python3 app.py")
    print(f"CV Tailor is running at http://{HOST}:{server.server_address[1]}", flush=True)
    print("The master CV and every job CV are stored in data/cv.db on this computer.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
