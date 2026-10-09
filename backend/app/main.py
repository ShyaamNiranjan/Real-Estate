from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import text

from app.db import public_session

app = FastAPI(title="Scrollwalk API", version="0.1.0", openapi_url="/api/v1/openapi.json")


class Health(BaseModel):
    status: str
    database: bool


@app.get("/api/v1/health", response_model=Health, tags=["system"])
def health() -> Health:
    try:
        with public_session() as session:
            session.execute(text("SELECT 1"))
        return Health(status="ok", database=True)
    except Exception:
        return Health(status="degraded", database=False)
