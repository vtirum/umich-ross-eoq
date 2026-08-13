"""
Idaho SDE public school finance files (sde.idaho.gov).

Static crawl of the finance-transparency section: average daily attendance
(full-term, midterm, best-28), support units, enrollment by building / district /
grade, revenues and expenditures 2004-2024, annual statements of financial
condition, and statewide certificated and non-certificated salary reports. Many of
the salary reports are PDFs, so they will not show demographic columns.

The Idaho Report Card data files are a separate JSON API; see id/reportcard.py.

Output:   data/raw/id/<category>/<filename>
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.static_site import run

SEEDS = [
    "https://www.sde.idaho.gov/finance-transparency/public-school-finance/",
    "https://www.sde.idaho.gov/finance-transparency/",
    "https://www.sde.idaho.gov/about-us/departments/assessment-accountability/",
]
FOLLOW = r"sde\.idaho\.gov/(finance-transparency|about-us/departments/assessment-accountability)"

if __name__ == "__main__":
    run("ID", SEEDS, "data/raw/id", follow=FOLLOW, depth=1)
