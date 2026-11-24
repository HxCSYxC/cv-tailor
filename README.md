# CV Tailor

Save one master CV on your computer. Each time you upload a job description, the app writes a separate CV for that job and keeps it.

Each job CV keeps every section, job and bullet from your master CV, in the same order. Claude rewords your summary and bullets toward the job description. It is told not to add facts, and the app double-checks: any rewritten line that brings in a number or a name not already on your CV is thrown away and your original line is kept. The job page shows every reworded line next to the original, and lists the job's key terms your CV does and does not cover.

## Run it

```bash
cd cv-tailor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

To have Claude reword your CV, start the app with your Anthropic API key (create one at console.anthropic.com):

```bash
ANTHROPIC_API_KEY=your-key python3 app.py
```

Without a key the app still works: job CVs keep your exact wording and you get the coverage report. It uses `claude-opus-5-5`; set `CV_TAILOR_MODEL` to use another model. Each job CV is one API call, billed to your Anthropic account.

Open [http://127.0.0.1:7860](http://127.0.0.1:7860). If that port is busy, the app moves to the next free one and prints the address it used. You can also choose a port: `PORT=8000 python3 app.py`.

1. Upload your CV once (PDF, Word, HTML, or text). It is stored in `data/cv.db`.
2. Upload or paste a job description. A CV for that job is created immediately.
3. Download that version as PDF, HTML, or Markdown.

Upload another job description and you get another CV. The master CV stays as you uploaded it. Replacing the master CV does not delete job CVs already saved; open a job and regenerate if you want the new master applied.

`data/` is not part of this repository. Your CV stays on the machine where you run the app.
