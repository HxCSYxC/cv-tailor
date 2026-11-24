# CV Tailor

Save one master CV on your computer. Each time you upload a job description, the app writes a separate CV for that job and keeps it.

It reorders sections and keeps the bullets that share wording with the job. It does not add employers, projects, or numbers that are not already on the master CV.

## Run it

```bash
cd cv-tailor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

1. Upload your CV once (PDF, Word, HTML, or text). It is stored in `data/cv.db`.
2. Upload or paste a job description. A CV for that job is created immediately.
3. Download that version as PDF, HTML, or Markdown.

Upload another job description and you get another CV. The master CV stays as you uploaded it. Replacing the master CV does not delete job CVs already saved; open a job and regenerate if you want the new master applied.

`data/` is not part of this repository. Your CV stays on the machine where you run the app.
