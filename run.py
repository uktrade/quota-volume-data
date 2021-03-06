from sys import argv
from sys import stdout
from functools import cache
from datetime import datetime

import requests
import xlsxwriter


URL_BASE = "https://www.trade-tariff.service.gov.uk/api/v2/"
QUOTA_SEARCH = f"{URL_BASE}quotas/search"
HEADING_SEARCH = f"{URL_BASE}headings/"

DATE_FORMAT = r'%Y-%m-%d'
DATETIME_FORMAT = fr'{DATE_FORMAT}T%H:%M:%S.%fZ'


def to_date(obj, format=DATETIME_FORMAT):
    if obj:
        return datetime.strptime(obj, format).date()
    else:
        return None


FIELDS = (
    ("Quota #", lambda q: q["quota_order_number_id"]),
    ("Geography", lambda q: ";\n".join(g["description"] for g in q["geographical_areas"])),
    ("Description", lambda q: q["description"]),
    ("Headings", lambda q: ";\n".join("{0[number]} – {0[description]}".format(h) for h in q["headings"])),
    ("Commodity codes", lambda q: ";\n".join(set(q["goods_nomenclature_item_ids"]))),
    ("Quota unit", lambda q: f'{q["measurement_unit"] or ""}{q["measurement_unit_qualifier"] or ""}'),
    ("Monetary unit", lambda q: q["monetary_unit"]),
    ("Validity start", lambda q: to_date(q["validity_start_date"])),
    ("Validity end", lambda q: to_date(q["validity_end_date"])),
    ("Suspension start", lambda q: to_date(q["suspension_period_start_date"], DATE_FORMAT)),
    ("Suspension end", lambda q: to_date(q["suspension_period_end_date"], DATE_FORMAT)),
    ("Blocking start", lambda q: to_date(q["blocking_period_start_date"], DATE_FORMAT)),
    ("Blocking end", lambda q: to_date(q["blocking_period_end_date"], DATE_FORMAT)),
    ("Status", lambda q: q["status"]),
    ("Last allocated", lambda q: to_date(q["last_allocation_date"])),
    ("Initial volume", lambda q: float(q["initial_volume"]) if q["initial_volume"] else None),
    ("Current balance", lambda q: float(q["balance"]) if q["balance"] else None),
    ("Fill rate", lambda q: float(q["fill_rate"]) if "fill_rate" in q else None),
)


FORMATS = {
    "wrapped": {"text_wrap": True},
    "date": {'num_format': 'yyyy-mm-dd'},
    "percentage": {"num_format": "0.00%"},
}


FIELD_FORMATS = {
    "Validity start": "date",
    "Validity end": "date",
    "Last allocated": "date",
    "Suspension start": "date",
    "Suspension end": "date",
    "Blocking start": "date",
    "Blocking end": "date",
    "Fill rate": "percentage",
}


def get_includes(included):
    return {
        (i["type"], i["id"]): {
            **i.get("attributes", {}),
            **i.get("relationships", {})
        }
        for i in included
    }


def relationships(obj, name: str):
    data = obj.get("relationships", {}).get(name, {}).get("data")
    if isinstance(data, list):
        for r in data:
            yield (r["type"], r["id"])
    elif isinstance(data, dict):
        yield (data["type"], data["id"])


@cache
def get_heading(heading: str):
    response = requests.get(HEADING_SEARCH + heading)
    assert response.status_code == 200 

    body = response.json()
    return {
        "number": heading,
        "description": body["data"]["attributes"]["description"],
    }


def augment(quotas, includes={}):
    for quota in quotas:
        quota["attributes"]["measures"] = []
        quota["attributes"]["geographical_areas"] = []
        quota["attributes"]["goods_nomenclature_item_ids"] = []
        quota["attributes"]["headings"] = []

        for measure_id in relationships(quota, "measures"):
            measure = includes.get(measure_id)
            quota["attributes"]["measures"].append(measure)
            quota["attributes"]["goods_nomenclature_item_ids"].append(
                measure["goods_nomenclature_item_id"]
            )

        headings = set(i[0:4] for i in quota["attributes"]["goods_nomenclature_item_ids"])
        for h in sorted(headings):
            quota["attributes"]["headings"].append(get_heading(h))

        order_number_id = next(relationships(quota, "order_number"))
        order_number = includes.get(order_number_id, {})
        quota["attributes"]["geographical_areas"] = [
            includes.get((g["type"], g["id"]))
            for g in order_number.get("geographical_areas", {}).get("data", [])
        ]

        parts = (quota["attributes"]["balance"], quota["attributes"]["initial_volume"])
        if all(parts) and float(parts[1]) != 0.0:
            quota["attributes"]["fill_rate"] = 1.0 - float(parts[0]) / float(parts[1])

        yield quota


def get_quotas():
    response = requests.get(QUOTA_SEARCH, params={"page": 1})
    assert response.status_code == 200

    body = response.json()
    meta = body['meta']

    total_pages = int(meta['pagination']['total_count'])
    per_page = int(meta['pagination']['per_page'])
    pages = (total_pages // per_page) + min(total_pages % per_page, 1)

    yield from augment(body["data"], get_includes(body["included"]))
    for page_number in range(2, pages):
        response = requests.get(QUOTA_SEARCH, params={"page": page_number})
        assert response.status_code == 200

        body = response.json()
        yield from augment(body["data"], get_includes(body["included"]))


if __name__ == "__main__":
    assert len(argv) == 2, "Usage: {0[0]} <output.xlsx>".format(argv)

    with xlsxwriter.Workbook(argv[1]) as workbook:
        formats = {}
        for format in FORMATS:
            formats[format] = workbook.add_format(FORMATS[format])

        worksheet = workbook.add_worksheet(name="Quota Utilisation")
        worksheet.write_row(0, 0, [f[0] for f in FIELDS])
        for column, field in enumerate(FIELDS):
            worksheet.set_column(
                first_col=column,
                last_col=column,
                width=13,
                cell_format=formats[FIELD_FORMATS.get(field[0], "wrapped")]
            )

        for row, quota in enumerate(get_quotas(), start=1):
            stdout.write("{}\r".format(row))
            worksheet.write_row(row, 0, [f[1](quota['attributes']) for f in FIELDS])
