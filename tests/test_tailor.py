import tempfile
import unittest
from pathlib import Path

from cvtailor.parse import header_key, parse_cv
from cvtailor.store import Store
from cvtailor.tailor import tailor

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


class TailorTests(unittest.TestCase):
    def test_two_jobs_keep_different_evidence(self):
        cv = parse_cv(MASTER)
        risk, _ = tailor(cv, "Risk Analyst", RISK_JOB)
        brand, _ = tailor(cv, "Marketing Analytics Intern", BRAND_JOB)
        self.assertIn("Risk Analyst", risk["profile"])
        self.assertIn("VaR", risk["profile"])
        self.assertIn("Tableau", brand["profile"])
        risk_headings = [entry["heading"] for section in risk["sections"] for entry in section["entries"]]
        brand_headings = [entry["heading"] for section in brand["sections"] for entry in section["entries"]]
        self.assertIn("RiskFit", risk_headings)
        self.assertNotIn("Wisers Information Limited", risk_headings)
        self.assertIn("Wisers Information Limited", brand_headings)
        self.assertNotIn("RiskFit", brand_headings)
        self.assertNotIn("invented employer", risk["profile"].lower())

    def test_does_not_add_a_skill_that_was_not_on_the_cv(self):
        cv = parse_cv(MASTER)
        tailored, _ = tailor(cv, "Kubernetes Engineer", "Kubernetes Docker Terraform on-call production systems")
        blob = tailored["profile"] + "\n" + "\n".join(
            line for section in tailored["sections"] for line in section.get("lines", [])
        )
        self.assertNotIn("Kubernetes", blob)


class StoreTests(unittest.TestCase):
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
            self.assertIn("VaR", risk["cv"]["profile"])
            self.assertIn("Tableau", brand["cv"]["profile"])
            filename, pdf = reopened.get_version_file(risk["version_id"], "pdf")
            self.assertTrue(filename.endswith(".pdf"))
            self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
