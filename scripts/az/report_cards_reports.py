import csv
import json
import time
import random
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://azreportcards.azed.gov/api"
OUT_DIR = Path("data/raw/az_reportcards")
OUT_DIR.mkdir(parents=True, exist_ok=True)

STATE_ENTITY_ID = 79275

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://azreportcards.azed.gov/",
}

REPORT_ENDPOINTS = [
    {
        "name": "Student Enrollment",
        "path": "DataApi/Student Enrollment",
        "params": {"reportSection": "Student Enrollment"},
    },
    {
        "name": "Teacher Qualification",
        "path": "DataApi/Teacher Qualification",
        "params": {"reportSection": "Teacher Qualification"},
    },
    {
        "name": "Assessment Proficiency Level",
        "path": "DataApi/Assessment Proficiency Level",
        "params": {"reportSection": "Assessment Proficiency Level"},
    },
    {
        "name": "ALT Assessment Participation Rates",
        "path": "DataApi/ALT Assessment Participation Rates",
        "params": {"reportSection": "ALT Assessment Participation Rates"},
    },
    {
        "name": "Assessment Participation Rates",
        "path": "DataApi/Assessment Participation Rates",
        "params": {"reportSection": "Assessment Participation Rates"},
    },
    {
        "name": "Federal Proficiency Goals",
        "path": "DataApi/Federal Proficiency Goals",
        "params": {"reportSection": "Federal Proficiency Goals"},
    },
    {
        "name": "Assessment DetailsFAY",
        "path": "DataApi/Assessment DetailsFAY",
        "params": {"reportSection": "Assessment DetailsFAY"},
    },
    {
        "name": "EL Proficiency",
        "path": "DataApi/EL Proficiency",
        "params": {"reportSection": "EL Proficiency"},
    },
    {
        "name": "Preschool Progress Monitoring",
        "path": "DataApi/Preschool Progress Monitoring",
        "params": {"reportSection": "Preschool Progress Monitoring"},
    },
    {
        "name": "Graduation Rate",
        "path": "DataApi/Graduation Rate",
        "params": {"reportSection": "Graduation Rate"},
    },
    {
        "name": "Graduation Rate Report Type 2",
        "path": "DataApi/Graduation Rate",
        "params": {"reportSection": "Graduation Rate", "reportTypeId": 2},
    },
    {
        "name": "End Of Year Promotion",
        "path": "DataApi/End Of Year Promotion",
        "params": {"reportSection": "End Of Year Promotion", "reportTypeId": 1},
    },
    {
        "name": "LRE for Preschool SPED Students",
        "path": "DataApi/LRE for Preschool SPED Students",
        "params": {"reportSection": "LRE for Preschool SPED Students"},
    },
    {
        "name": "GetRAELCount",
        "path": "DataApi/GetRAELCount",
        "params": {},
    },
    {
        "name": "GetTeachersTrendData",
        "path": "DataApi/GetTeachersTrendData",
        "params": {},
    },
    {
        "name": "GetELProficiencyTrendData",
        "path": "DataApi/GetELProficiencyTrendData",
        "params": {},
    },
    {
        "name": "GetGradRateTrendData",
        "path": "DataApi/GetGradRateTrendData",
        "params": {},
    },
    {
        "name": "GetDropoutRateTrendData",
        "path": "DataApi/GetDropoutRateTrendData",
        "params": {},
    },
    {
        "name": "GetEnrollmentTrendData",
        "path": "DataApi/GetEnrollmentTrendData",
        "params": {},
    },
    {
        "name": "GetAssessmentTrendData",
        "path": "DataApi/GetAssessmentTrendData",
        "params": {},
    },
    {
        "name": "Federal Graduation Rate Goals",
        "path": "DataApi/Federal Graduation Rate Goals",
        "params": {},
    },
    {
        "name": "GetELProficiencyActuals",
        "path": "DataApi/GetELProficiencyActuals",
        "params": {},
    },
    {
        "name": "GetChronicAbsenteeismTrendData",
        "path": "DataApi/GetChronicAbsenteeismTrendData",
        "params": {},
    },
]


def safe_name(text):
    return (
        text.replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
        .replace("%20", "_")
        .replace("?", "_")
        .replace("&", "_")
    )


def api_url(path):
    encoded_path = quote(path, safe="/")
    return f"{BASE}/{encoded_path}"


def get_json(session, path, params=None):
    url = api_url(path)
    for attempt in range(1, 4): 
        try:
            response = session.get(url, params=params or {}, headers=HEADERS, timeout=(10, 60))
            
            if response.status_code == 204:
                return None, response.url, response.status_code

            if response.status_code in [400, 403, 404, 500]:
                return None, response.url, response.status_code

            response.raise_for_status()

            try:
                return response.json(), response.url, response.status_code
            except Exception:
                return response.text, response.url, response.status_code

        except requests.RequestException as e:
            print(f"Attempt {attempt} failed for {url}: {e}")
            if attempt == 3:
                return None, url, "connection_error"
            
            time.sleep(3 * attempt + random.random())


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_fiscal_years(session):
    data, url, status = get_json(session, "DataApi/GetFiscalYears")
    return [row["fiscalYear"] for row in data]


def get_entities(session, fiscal_year):
    data, url, status = get_json(
        session,
        "Entity/GetEntityList",
        {"fiscalYear": fiscal_year},
    )

    save_json(
        OUT_DIR / str(fiscal_year) / "entities" / "entity_list.json",
        data,
    )

    return data or []


def classify_entity(entity):
    entity_type = str(entity.get("entityType", "")).lower()
    school_types = str(entity.get("schoolTypes", "")).lower()

    if entity_type == "school":
        return "school"

    if entity_type == "lea":
        return "district"

    if "district" in school_types:
        return "district"

    return "unknown"


def download_report(session, fiscal_year, entity, report):
    entity_id = entity["educationOrganizationId"]
    entity_kind = classify_entity(entity)

    params = dict(report["params"])
    params["fiscalYear"] = fiscal_year
    params["educationOrganizationId"] = entity_id

    data, final_url, status = get_json(session, report["path"], params)

    report_name = safe_name(report["name"])
    entity_name = safe_name(entity.get("nameOfInstitution", "unknown"))[:80]

    out_path = (
        OUT_DIR
        / str(fiscal_year)
        / entity_kind
        / str(entity_id)
        / f"{report_name}.json"
    )

    if data is not None:
        save_json(out_path, data)

    return {
        "fiscal_year": fiscal_year,
        "entity_id": entity_id,
        "entity_name": entity.get("nameOfInstitution"),
        "entity_kind": entity_kind,
        "report": report["name"],
        "url": final_url,
        "status_code": status,
        "saved_path": str(out_path) if data is not None else "",
    }


def download_state_report(session, fiscal_year, report):
    fake_entity = {
        "educationOrganizationId": STATE_ENTITY_ID,
        "nameOfInstitution": "Arizona State Level",
        "entityType": "State",
        "schoolTypes": "State",
    }

    row = download_report(session, fiscal_year, fake_entity, report)

    # Move state-level files into a cleaner folder
    old_path = Path(row["saved_path"]) if row["saved_path"] else None
    if old_path and old_path.exists():
        new_path = (
            OUT_DIR
            / str(fiscal_year)
            / "state"
            / f"{safe_name(report['name'])}.json"
        )
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.replace(new_path)
        row["saved_path"] = str(new_path)
        row["entity_kind"] = "state"

    return row


def main():
    manifest = []

    with requests.Session() as session:
        fiscal_years = get_fiscal_years(session)

        # fiscal years = [2025]

        print("Fiscal years:", fiscal_years)

        for fiscal_year in fiscal_years:
            print(f"\n=== Fiscal Year {fiscal_year} ===")

            # Save state report section metadata
            sections, section_url, section_status = get_json(
                session,
                "DataApi/GetSateReportSections",
                {
                    "reportSection": "GetSateReportSections",
                    "fiscalYear": fiscal_year,
                },
            )

            if sections is not None:
                save_json(
                    OUT_DIR / str(fiscal_year) / "state" / "state_report_sections.json",
                    sections,
                )

            # State-level report data
            for report in REPORT_ENDPOINTS:
                print(f"State {fiscal_year}: {report['name']}")
                row = download_state_report(session, fiscal_year, report)
                manifest.append(row)
                time.sleep(0.2)

            # School and district entity list
            entities = get_entities(session, fiscal_year)
            print(f"Found {len(entities)} entities")

            # For testing, uncomment this:
            # entities = entities[:10]

            for idx, entity in enumerate(entities, start=1):
                entity_id = entity.get("educationOrganizationId")
                entity_name = entity.get("nameOfInstitution")
                entity_kind = classify_entity(entity)

                if not entity_id:
                    continue

                print(f"[{idx}/{len(entities)}] {entity_kind}: {entity_name} ({entity_id})")

                for report in REPORT_ENDPOINTS:
                    row = download_report(session, fiscal_year, entity, report)
                    manifest.append(row)
                    time.sleep(0.1)

    manifest_path = OUT_DIR / "manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "fiscal_year",
            "entity_id",
            "entity_name",
            "entity_kind",
            "report",
            "url",
            "status_code",
            "saved_path",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest)

    print(f"\nDone. Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()