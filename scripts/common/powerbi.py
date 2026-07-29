"""
common/powerbi.py — extract data from public Power BI "view" embeds

Some agencies publish data only inside an embedded Power BI report (Arizona's ADE
Workforce dashboards, Indiana's EdData Form 9 finance). Those reports render by
POSTing to <region>.analysis.windows.net/public/reports/querydata and receiving a
compressed "DSR" payload. We load the embed in a browser, nudge it so every visual
issues its query, capture each querydata response, and decode the DSR into rows.

DSR shapes handled:
  - inline C-arrays with R (repeat-previous) and O/Ø (null) bitmasks
  - ValueDicts dictionary-encoded values
  - named-key rows (G0/M0 as object keys)
  - nested X/SH matrices (trend charts: one row per primary axis value, with an X
    array of per-series measures and series labels in SH)

Column names come from the response's descriptor.Select. Shared by
scripts/az/workforce_dashboards.py and scripts/in/eddata_dashboards.py.
"""

import re
import time

from common.file_utils import safe_filename

# ------------------------- DSR decoding -------------------------

def _clean_field(name):
    """'Count(TIA 2023.PublicEducatorID)' -> 'Count_PublicEducatorID';
       'TIA 2023.GradeBucket' -> 'GradeBucket'."""
    name = re.sub(r"TIA \d+\.", "", name)
    name = re.sub(r"[()]", "", name)
    name = name.replace(" ", "_").replace(".", "_")
    return name.strip("_")


def _column_labels(select, schema):
    """Map row-schema entries (G0,G1,M0,M1...) to human names from descriptor.Select.

    Select entries carry Kind: 1 = grouping/column, 2 = measure. Groupings map to
    G0,G1... in order; measures map to M0,M1... in order.
    """
    groupings = [s.get("Name", "") for s in select if s.get("Kind") == 1]
    measures = [s.get("Name", "") for s in select if s.get("Kind") == 2]
    labels = []
    for col in schema:
        n = col.get("N", "")
        if n.startswith("G"):
            i = int(n[1:])
            labels.append(_clean_field(groupings[i]) if i < len(groupings) else n)
        elif n.startswith("M"):
            i = int(n[1:])
            labels.append(_clean_field(measures[i]) if i < len(measures) else n)
        else:
            labels.append(n)
    return labels


def _lookup(value, col_schema, value_dicts):
    """Resolve a dictionary-encoded value if the column references a ValueDict."""
    dn = col_schema.get("DN")
    if dn and dn in value_dicts and isinstance(value, int):
        vd = value_dicts[dn]
        if 0 <= value < len(vd):
            return vd[value]
    return value


def _decode_dm(dm_rows, value_dicts):
    """Decode a DM<n> array of rows into (schema, list-of-rows).

    Handles: an S schema on the first row; C-array rows with R (repeat) and Ø
    (null) bitmasks; and named-key rows (G0/M0 as object keys).
    """
    schema = None
    ncols = 0
    prev = []
    out = []
    for row in dm_rows:
        if "S" in row:
            schema = row["S"]
            ncols = len(schema)
        if schema is None:
            continue
        R = row.get("R", 0)   # repeat-previous bitmask
        O = row.get("Ø", 0)   # null bitmask
        C = row.get("C")
        cur = [None] * ncols
        if C is not None:
            ci = 0
            for idx in range(ncols):
                bit = 1 << idx
                if R & bit:
                    cur[idx] = prev[idx] if idx < len(prev) else None
                elif O & bit:
                    cur[idx] = None
                else:
                    cur[idx] = _lookup(C[ci], schema[idx], value_dicts) if ci < len(C) else None
                    ci += 1
        else:
            # named-key row
            for idx, col in enumerate(schema):
                n = col.get("N", "")
                bit = 1 << idx
                if n in row:
                    cur[idx] = _lookup(row[n], col, value_dicts)
                elif R & bit:
                    cur[idx] = prev[idx] if idx < len(prev) else None
                elif O & bit:
                    cur[idx] = None
                else:
                    cur[idx] = prev[idx] if idx < len(prev) else None
        out.append(cur)
        prev = cur
    return schema, out


def _looks_like_year(values):
    yrs = [v for v in values if isinstance(v, (int, float)) and 1990 <= v <= 2100]
    return bool(values) and len(yrs) == len(values)


def _split_trend_labels(groupings, primary_vals):
    """For a Year x category trend, decide which grouping name is the primary
    (row) axis and which is the series. The Select order is unreliable, so use a
    year heuristic on the actual primary values.
    """
    year_names = [g for g in groupings if "year" in g.lower()]
    other_names = [g for g in groupings if "year" not in g.lower()]
    if _looks_like_year(primary_vals):
        primary = year_names[0] if year_names else "Year"
        series = other_names[0] if other_names else "Series"
    else:
        primary = groupings[0] if groupings else "Category"
        series = groupings[1] if len(groupings) > 1 else "Series"
    return primary, series


def _decode_series_headers(sh, value_dicts):
    """SH -> flat list of series member values (single-level series)."""
    members = []
    if not sh:
        return members
    for block in sh:
        for dm_key, dm_rows in block.items():
            if not dm_key.startswith("DM"):
                continue
            _schema, rows = _decode_dm(dm_rows, value_dicts)
            members.extend(r[0] if r else None for r in rows)
    return members


def _decode_matrix(dm_rows, series_members, value_dicts):
    """Decode a primary-axis DM whose rows carry a nested X value grid.

    Each row: primary grouping value(s) + X=[{M..}, ...] one entry per series
    member. Emits [primary..., series_member, measure...] rows.
    """
    schema = None
    ncols = 0
    prev = []
    out = []
    prim_labels_schema = None
    x_schema = None
    for row in dm_rows:
        if "S" in row:
            schema = row["S"]
            ncols = len(schema)
            prim_labels_schema = schema
        if schema is None:
            continue
        # primary (row-header) values, honoring named keys + R/Ø
        R, O = row.get("R", 0), row.get("Ø", 0)
        prim = [None] * ncols
        for idx, col in enumerate(schema):
            n = col.get("N", "")
            bit = 1 << idx
            if n in row:
                prim[idx] = _lookup(row[n], col, value_dicts)
            elif R & bit:
                prim[idx] = prev[idx] if idx < len(prev) else None
            elif O & bit:
                prim[idx] = None
            else:
                prim[idx] = prev[idx] if idx < len(prev) else None
        prev = prim
        xs = row.get("X", [])
        for j, xrow in enumerate(xs):
            if "S" in xrow:
                x_schema = xrow["S"]
            xvals = []
            if x_schema:
                for xi, xcol in enumerate(x_schema):
                    xn = xcol.get("N", "")
                    xvals.append(_lookup(xrow[xn], xcol, value_dicts) if xn in xrow else None)
            member = series_members[j] if j < len(series_members) else j
            out.append(list(prim) + [member] + xvals)
    return prim_labels_schema, x_schema, out


def decode_querydata(payload):
    """Yield (columns, rows) for each dataset in a Power BI querydata response."""
    results = []
    try:
        data = payload["results"][0]["result"]["data"]
    except (KeyError, IndexError, TypeError):
        return results
    select = data.get("descriptor", {}).get("Select", [])
    groupings = [_clean_field(s.get("Name", "")) for s in select if s.get("Kind") == 1]
    measures = [_clean_field(s.get("Name", "")) for s in select if s.get("Kind") == 2]
    dsr = data.get("dsr", {})
    value_dicts = dsr.get("ValueDicts", {})
    for ds in dsr.get("DS", []):
        series_members = _decode_series_headers(ds.get("SH"), value_dicts)
        for key, val in ds.items():
            if not key.startswith("PH"):
                continue
            for block in val:
                for dm_key, dm_rows in block.items():
                    if not dm_key.startswith("DM") or not isinstance(dm_rows, list):
                        continue
                    is_matrix = any(isinstance(r, dict) and "X" in r for r in dm_rows)
                    if is_matrix and series_members:
                        prim_s, x_s, rows = _decode_matrix(dm_rows, series_members, value_dicts)
                        if not rows:
                            continue
                        # Single primary axis + one series is the shape of every
                        # trend here (Year x category). Name axes via year heuristic.
                        primary_label, series_label = _split_trend_labels(
                            groupings, [r[0] for r in rows])
                        cols = [primary_label, series_label] + measures
                        results.append((cols, rows))
                    else:
                        schema, rows = _decode_dm(dm_rows, value_dicts)
                        if schema and rows:
                            results.append((_column_labels(select, schema), rows))
    return results


# ------------------------- capture -------------------------

def _nudge(page, seconds):
    """Move/scroll over the report so its visuals issue their queries."""
    end = time.time() + seconds
    while time.time() < end:
        try:
            page.mouse.move(500, 400)
            page.mouse.wheel(0, 80)
            page.mouse.wheel(0, -80)
        except Exception:
            pass
        time.sleep(1)


def _next_page(page):
    for sel in ("button[aria-label='Next Page']", "[title='Next Page']", "i.glyphicon-chevron-right"):
        try:
            page.click(sel, timeout=2500)
            return True
        except Exception:
            continue
    return False


def _slug(columns, taken):
    base = "__".join(columns) or "visual"
    base = safe_filename(base)[:80]
    slug = base
    i = 2
    while slug in taken:
        slug = f"{base}_{i}"
        i += 1
    taken.add(slug)
    return slug


def _capture_report(page, report):
    """Load a report, walk its pages, return {page_index: [querydata payloads]}."""
    by_page = {}
    current = {"bodies": []}

    def on_resp(resp):
        if "querydata" in resp.url.lower():
            try:
                current["bodies"].append(resp.json())
            except Exception:
                pass

    page.on("response", on_resp)
    page.goto(report["embed"], wait_until="load", timeout=60000)
    _nudge(page, 22)
    by_page[1] = list(current["bodies"])

    for pidx in range(2, report["pages"] + 1):
        current["bodies"].clear()
        if not _next_page(page):
            print(f"  (could not navigate to page {pidx})")
            break
        time.sleep(4)
        _nudge(page, 14)
        by_page[pidx] = list(current["bodies"])

    page.remove_listener("response", on_resp)
    return by_page

