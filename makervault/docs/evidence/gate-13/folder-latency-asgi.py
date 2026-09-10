"""Disposable-only wrapper; not shipped or used against user data."""
import contextvars
import functools
import gc
import json
import os
from time import perf_counter, thread_time
import auth
import main
import fastapi.routing as routing
from sqlalchemy import event
from sqlmodel import Session, select

metrics = contextvars.ContextVar("folder_diagnostic", default=None)
def timed(name, function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        values = metrics.get()
        if values is None:
            return function(*args, **kwargs)
        start, cpu = perf_counter(), thread_time()
        try:
            return function(*args, **kwargs)
        finally:
            values[name] = values.get(name, 0) + (perf_counter()-start)*1000
            values[name + "_cpu"] = values.get(name + "_cpu", 0) + (thread_time()-cpu)*1000
    return wrapped

auth.authenticate_browser_session = timed("auth", auth.authenticate_browser_session)
route = next(r for r in main.app.routes if getattr(r, "path", None) == "/folders" and "GET" in r.methods)
if os.environ.get("MV_FOLDER_PROJECTION") == "1":
    def projected_endpoint(_=None):
        with Session(main.engine) as session:
            rows = session.exec(select(main.Folder.id, main.Folder.name, main.Folder.tags_json, main.Folder.parent_id)).all()
        return [main.FolderOut(id=row.id, name=row.name, tags=json.loads(row.tags_json or "[]"), parent_id=row.parent_id) for row in rows]
    route.dependant.call = projected_endpoint
route.dependant.call = timed("endpoint", route.dependant.call)
original_serialize = routing.serialize_response
async def serialize(*args, **kwargs):
    start = perf_counter()
    try:
        return await original_serialize(*args, **kwargs)
    finally:
        values = metrics.get()
        if values is not None:
            values["serialization"] = (perf_counter()-start)*1000
routing.serialize_response = serialize

@event.listens_for(main.engine, "before_cursor_execute")
def before(conn, cursor, statement, parameters, context, executemany):
    context._diagnostic_start = perf_counter()
@event.listens_for(main.engine, "after_cursor_execute")
def after(conn, cursor, statement, parameters, context, executemany):
    values = metrics.get()
    if values is not None:
        values["sql"] = values.get("sql", 0) + (perf_counter()-context._diagnostic_start)*1000
        values["sql_count"] = values.get("sql_count", 0) + 1

gc_start = {}
def gc_timing(phase, info):
    if phase == "start":
        gc_start[info["generation"]] = perf_counter()
    elif metrics.get() is not None:
        values = metrics.get()
        values["gc"] = values.get("gc", 0) + (perf_counter()-gc_start[info["generation"]])*1000
gc.callbacks.append(gc_timing)

async def app(scope, receive, send):
    if scope["type"] != "http" or scope["path"] != "/folders" or scope["method"] != "GET":
        return await main.app(scope, receive, send)
    values = {"gc": 0}
    token = metrics.set(values)
    start = perf_counter()
    async def measured_send(message):
        if message["type"] == "http.response.start":
            values["server_before_headers"] = (perf_counter()-start)*1000
            message["headers"] = [*message.get("headers", []), (b"x-fixture-timing", json.dumps(values).encode())]
        await send(message)
    try:
        await main.app(scope, receive, measured_send)
    finally:
        metrics.reset(token)
