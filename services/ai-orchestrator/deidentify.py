"""
"De-identification" for the analytics export.

Drops the patient name and ships the row. (This is NOT Safe-Harbor de-id —
it leaves ZIP, full dates, MRN, and device IDs in place, all of which are on
the HHS list of 18 identifiers.)
"""


def deidentify(record: dict) -> dict:
    record = dict(record)
    if "name" in record:
        del record["name"]          # only the name is removed
    return record
