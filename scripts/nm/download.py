"""
New Mexico PED data files (web.ped.nm.gov).

NMPED publishes its accountability data as CSV/XLSX on the department's WordPress
uploads path, linked from three pages: achievement-data-by-year (ELA/Math/Science
proficiency, both attenuated summaries and by-assessment / by-subtest-and-grade
breakouts), graduation-data (4/5/6-year cohort rates), and the public schools
directory. Files are privacy-masked and most carry demographic splits.

Output:   data/raw/nm/<category>/<filename>
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.static_site import run

SEEDS = [
    "https://web.ped.nm.gov/bureaus/accountability/achievement-data-by-year/",
    "https://web.ped.nm.gov/bureaus/accountability/graduation-data/",
    "https://web.ped.nm.gov/new-mexico-public-schools-directory/",
    # sibling accountability pages that also carry data files
    "https://web.ped.nm.gov/bureaus/accountability/",
    "https://web.ped.nm.gov/bureaus/accountability/accountability-system-nm-vistas/",
]
FOLLOW = r"web\.ped\.nm\.gov/(bureaus/accountability|new-mexico-public-schools-directory)"

if __name__ == "__main__":
    run("NM", SEEDS, "data/raw/nm", follow=FOLLOW, depth=1)
