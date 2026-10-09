"""Writes the API contract the frontend's typed client is generated from.

    python -m app.openapi_export
"""

import json
from pathlib import Path

from app.main import app

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {CONTRACT}")
