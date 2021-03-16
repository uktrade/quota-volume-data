from sys import argv
from sys import stdout
from datetime import datetime

import requests
import xlsxwriter


URL_BASE = "https://www.trade-tariff.service.gov.uk/api/v2/quotas/search"

DATE_FORMAT = r'%Y-%m-%dT%H:%M:%S.%fZ'

FIELDS = [
    ("Quota #",         lambda q: q["quota_order_number_id"]),
    ("Validity start",  lambda q: datetime.strptime(q["validity_start_date"], DATE_FORMAT).date() if q["validity_start_date"] is not None else None),
    ("Validity end",    lambda q: datetime.strptime(q["validity_end_date"], DATE_FORMAT).date() if q["validity_end_date"] is not None else None),
    ("Current balance", lambda q: float(q["balance"]) if q["balance"] else None),
    ("Initial volume",  lambda q: float(q["initial_volume"]) if q["initial_volume"] else None),
]

def get_quotas():
    response = requests.get(URL_BASE, params={"page": 1})
    assert response.status_code == 200

    body = response.json()
    meta = body['meta']

    total_pages = int(meta['pagination']['total_count'])
    per_page = int(meta['pagination']['per_page'])
    pages = (total_pages // per_page) + min(total_pages % per_page, 1)

    yield from body['data']
    for page_number in range(2, pages):
        response = requests.get(URL_BASE, params={"page": page_number})
        assert response.status_code == 200

        yield from response.json()['data']


if __name__ == "__main__":
    assert len(argv) == 2, "Usage: {0[0]} <output.xlsx>".format(argv)

    with xlsxwriter.Workbook(argv[1], {"default_date_format": "yyyy-mm-dd"}) as workbook:
        worksheet = workbook.add_worksheet(name="Quota Utilisation")
        worksheet.write_row(0, 0, [f[0] for f in FIELDS])
        worksheet.set_column(0, len(FIELDS)-1, width=13)
        for row, quota in enumerate(get_quotas(), start=1):
            stdout.write("{}\r".format(row))
            worksheet.write_row(row, 0, [f[1](quota['attributes']) for f in FIELDS])
