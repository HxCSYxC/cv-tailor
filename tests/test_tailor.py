import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

from cvtailor.parse import header_key, parse_cv
from cvtailor.store import Store
from cvtailor.tailor import coverage, extract_terms, tailor

MASTER = """
CHAN EXAMPLE
example@school.edu · Hong Kong · github.com/example
Decision analytics student who reports numbers a client can defend.
EDUCATION
Example University
BEng, Decision Analytics
EXPERIENCE
Wisers Information Limited
Analytics Intern
• Validated 10000 records for luxury fashion brands and built Tableau dashboards.
• Wrote notes for internal meetings.
PROJECTS
RiskFit
Personal project
• Stress-tested five portfolios through 2008, 2020 and 2022, including VaR and expected shortfall.
• Built a one-page portfolio proposal from a risk questionnaire.
AI Trader
Personal project
• Rejected 91 chart rules after trading costs on 1.09 million trades.
SKILLS
Python, Tableau, Excel, SQL
"""

RISK_JOB = """
Risk Analyst
We need someone who can run stress tests, report VaR and expected shortfall, and explain portfolio risk in Python.
"""

BRAND_JOB = """
Marketing Analytics Intern
Build Tableau dashboards for luxury fashion brands and keep campaign reporting accurate.
"""


class ParseTests(unittest.TestCase):
    def test_tracked_caps_header(self):
        self.assertEqual(header_key("E D U C A T I O N"), "education")

    def test_sections_and_bullets(self):
        cv = parse_cv(MASTER)
        self.assertEqual(cv["name"], "CHAN EXAMPLE")
        keys = [section["key"] for section in cv["sections"]]
        self.assertEqual(keys, ["education", "experience", "projects", "skills"])
        experience = cv["sections"][1]
        self.assertEqual(experience["entries"][0]["heading"], "Wisers Information Limited")
        self.assertIn("Tableau", experience["entries"][0]["bullets"][0])


class FakeClient:
    """Stands in for anthropic.Anthropic() so tests never call the API."""

    def __init__(self, rewrite_fn):
        self.rewrite_fn = rewrite_fn
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"]
        lines = json.loads(prompt.split("<lines>\n", 1)[1].rsplit("\n</lines>", 1)[0])
        out = [{"id": line["id"], "text": self.rewrite_fn(line["text"])} for line in lines]
        block = SimpleNamespace(type="text", text=json.dumps({"lines": out}))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def headings(cv):
    return [(s["key"], e["heading"], len(e["bullets"])) for s in cv["sections"] for e in s["entries"]]


class TailorTests(unittest.TestCase):
    def test_structure_is_identical_to_master(self):
        cv = parse_cv(MASTER)
        client = FakeClient(lambda text: text.replace("Built", "Delivered"))
        risk, _ = tailor(cv, "Risk Analyst", RISK_JOB, client=client)
        self.assertEqual(headings(risk), headings(cv))
        self.assertEqual([s["title"] for s in risk["sections"]], [s["title"] for s in cv["sections"]])
        self.assertEqual(risk["sections"][-1]["lines"], cv["sections"][-1]["lines"])

    def test_claude_rewording_is_applied_and_listed(self):
        cv = parse_cv(MASTER)
        client = FakeClient(lambda text: text.replace("Stress-tested", "Ran stress tests on"))
        risk, notes = tailor(cv, "Risk Analyst", RISK_JOB, client=client)
        bullet = risk["sections"][2]["entries"][0]["bullets"][0]
        self.assertTrue(bullet.startswith("Ran stress tests on five portfolios"))
        self.assertEqual(len(risk["changes"]), 1)
        self.assertEqual(risk["changes"][0]["where"], "RiskFit")
        self.assertIn("reworded 1 line", notes[0])
        self.assertIn("Risk Analyst", client.calls[0]["messages"][0]["content"])

    def test_rewrite_that_adds_a_number_or_name_is_rejected(self):
        cv = parse_cv(MASTER)

        def invent(text):
            if "Tableau" in text:
                return text + " Increased revenue 40%."
            if "chart rules" in text:
                return text.replace("Rejected", "Using Kubernetes, rejected")
            return text

        tailored, notes = tailor(cv, "Analyst", BRAND_JOB, client=FakeClient(invent))
        self.assertEqual(tailored["changes"], [])
        self.assertEqual(to_text(tailored), to_text(cv))
        self.assertTrue(any("Kept the original wording of 2" in note for note in notes))

    def test_api_failure_keeps_the_cv(self):
        cv = parse_cv(MASTER)

        class Broken:
            beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(RuntimeError("offline"))))

        tailored, notes = tailor(cv, "Analyst", BRAND_JOB, client=Broken())
        self.assertEqual(to_text(tailored), to_text(cv))
        self.assertTrue(any("offline" in note for note in notes))

    def test_without_a_key_the_wording_is_unchanged(self):
        cv = parse_cv(MASTER)
        tailored, notes = tailor(cv, "Analyst", BRAND_JOB, use_ai=False)
        self.assertEqual(to_text(tailored), to_text(cv))
        self.assertIn("ANTHROPIC_API_KEY", notes[0])

    def test_sentence_end_does_not_break_matching(self):
        keywords, phrases = extract_terms(RISK_JOB)
        self.assertIn("python", keywords)
        self.assertNotIn("python.", keywords)
        self.assertNotIn("risk python", phrases)
        self.assertNotIn("someone", keywords)

    def test_coverage_reports_missing_terms_without_adding_them(self):
        cv = parse_cv(MASTER)
        report = coverage(cv, BRAND_JOB)
        self.assertIn("campaign", report["missing"])
        self.assertIn("tableau dashboards", report["found"])
        self.assertTrue(0 < report["percent"] < 100)


def to_text(cv: dict) -> str:
    chunks = [cv["profile"]]
    for section in cv["sections"]:
        chunks.extend(section.get("lines", []))
        for entry in section.get("entries", []):
            chunks.extend([entry["heading"], entry.get("sub", ""), *entry.get("bullets", [])])
    return "\n".join(chunks)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.pop(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if k in os.environ}

    def tearDown(self):
        os.environ.update(self._env)

    def test_master_is_remembered_and_each_job_gets_its_own_cv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cv.db"
            store = Store(path)
            store.save_master("cv.txt", MASTER.encode())
            again = Store(path)
            master = again.get_master()
            self.assertIsNotNone(master)
            self.assertEqual(master["parsed"]["name"], "CHAN EXAMPLE")
            risk_id = again.add_job("risk.txt", RISK_JOB, "Risk Analyst")
            brand_id = again.add_job("brand.txt", BRAND_JOB, "Marketing Analytics Intern")
            reopened = Store(path)
            jobs = reopened.list_jobs()
            self.assertEqual({job["title"] for job in jobs}, {"Risk Analyst", "Marketing Analytics Intern"})
            risk = reopened.get_job(risk_id)
            brand = reopened.get_job(brand_id)
            self.assertEqual(headings(risk["cv"]), headings(master["parsed"]))
            self.assertEqual(risk["match"]["missing"], ["analyst"])
            self.assertTrue(all(job["match"] for job in jobs))
            filename, pdf = reopened.get_version_file(risk["version_id"], "pdf")
            self.assertTrue(filename.endswith(".pdf"))
            self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
