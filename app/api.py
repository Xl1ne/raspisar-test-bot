from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response

from app import storage
from app.publication import render_calendar


@asynccontextmanager
async def lifespan(_app):
    storage.ensure_schema()
    yield


app = FastAPI(title="Расписарь", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/calendar/{code}.ics")
def calendar(code: str) -> Response:
    conn = storage.connect()
    try:
        body = render_calendar(conn, code)
    except LookupError:
        raise HTTPException(status_code=404, detail="Календарь не найден") from None
    finally:
        conn.close()
    return Response(content=body, media_type="text/calendar; charset=utf-8")
