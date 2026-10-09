import json

from app.openapi_export import CONTRACT, render


def test_committed_contract_matches_the_api():
    assert CONTRACT.exists(), "run: python -m app.openapi_export"
    assert json.loads(CONTRACT.read_text(encoding="utf-8")) == json.loads(render()), (
        "The API changed but docs/api/openapi.json didn't. Run: python -m app.openapi_export"
    )
