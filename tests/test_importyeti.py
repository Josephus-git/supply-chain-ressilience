from pathlib import Path

import pytest

from dyson_supply_chain.config import Settings
from dyson_supply_chain.importyeti.client import ImportYetiClient, ImportYetiError
from dyson_supply_chain.importyeti.extractor import extract
from dyson_supply_chain.importyeti.models import BOLPage, ResponseFormatError
from dyson_supply_chain.importyeti.pagination import iter_pages


def response(rows, total):
    return {"requestCost": 1, "creditsRemaining": 20, "data": {"data": rows, "totalCount": total}}


def test_response_parsing_and_validation():
    page = BOLPage.from_response(response([{"bol_number": "A", "arrival_date": "01/01/2025"}], 1))
    assert page.records[0]["bol_number"] == "A"
    with pytest.raises(ResponseFormatError):
        BOLPage.from_response({"data": []})


def test_pagination_uses_total_count_and_offsets():
    calls = []

    def fetch(params):
        calls.append(params)
        offset = params["offset"]
        return response([{"bol_number": str(offset + 1), "arrival_date": "01/01/2025"}], 2)

    pages = list(iter_pages(fetch, {"company": "Dyson"}, 1))
    assert [offset for offset, _ in pages] == [0, 1]
    assert calls[-1]["offset"] == 1


def test_extraction_writes_raw_normalized_and_manifest(tmp_path: Path):
    responses = iter([
        response([
            {"bol_number": "A", "arrival_date": "01/01/2025"},
            {"bol_number": "A", "arrival_date": "01/01/2025"},
        ], 2)
    ])

    class Client:
        endpoint = "/v1.0/powerquery/us-import/bols"

        def search_bols(self, params):
            return next(responses)

    manifest = extract(
        Client(), {"company": "Dyson"}, tmp_path / "raw.jsonl", tmp_path / "normalized.jsonl",
        tmp_path / "manifest.json", 10,
    )
    assert manifest["status"] == "completed"
    assert manifest["stats"]["retrieved"] == 2
    assert manifest["stats"]["deduplicated"] == 1
    assert len((tmp_path / "raw.jsonl").read_text().splitlines()) == 1
    assert len((tmp_path / "normalized.jsonl").read_text().splitlines()) == 1


def test_client_retries_429(monkeypatch):
    class Response:
        status_code = 429
        text = "throttled"

        def json(self):
            return {"statusCode": 429}

    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Response()
            return type("OK", (), {"status_code": 200, "json": lambda self: response([], 0)})()

    monkeypatch.setattr("dyson_supply_chain.importyeti.client.time.sleep", lambda _: None)
    session = Session()
    settings = Settings("secret", max_retries=1)
    assert ImportYetiClient(settings, session).search_bols({})["data"]["totalCount"] == 0
    assert session.calls == 2


def test_client_fails_on_authentication_error():
    class Response:
        status_code = 401
        text = "Unauthorized"

        def json(self):
            return {"statusCode": 401}

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    with pytest.raises(ImportYetiError, match="401"):
        ImportYetiClient(Settings("secret"), Session()).search_bols({})

