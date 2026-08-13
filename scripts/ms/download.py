"""
Mississippi MDE public reporting files (mdek12.org/publicreporting).

Organised by school year (2018-19 to 2025-26) and by topic (Assessment,
Accountability, Reports, Diplomas & Transcripts, Staff); the files themselves are
WordPress uploads. A good share are PDFs rather than spreadsheets.

Files served from mdek12.org/sites/default/files 403 without a same-site Referer,
which common/static_site.py retries automatically.

Not crawled: msrc.mdek12.org and newreports.mdek12.org are separate apps rather
than file listings.

Output:   data/raw/ms/<category>/<filename>
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.static_site import run

YEARS = ["2025-26", "2024-25", "2023-24", "2022-23", "2021-22", "2020-21",
         "2019-20", "2018-19"]
SEEDS = (
    ["https://mdek12.org/publicreporting/",
     "https://mdek12.org/publicreporting/Assessment/",
     "https://mdek12.org/publicreporting/Accountability",
     "https://mdek12.org/publicreporting/Reports",
     "https://mdek12.org/publicreporting/Diplomas-and-Transcripts",
     "https://mdek12.org/publicreporting/public-reporting-staff/"]
    + [f"https://mdek12.org/publicreporting/{y}/" for y in YEARS]
)
FOLLOW = r"mdek12\.org/publicreporting"

if __name__ == "__main__":
    run("MS", SEEDS, "data/raw/ms", follow=FOLLOW, depth=1)
