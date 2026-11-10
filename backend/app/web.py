"""One process, one port: the web app + the API (Part 28, the Windows package).

    python -m uvicorn app.web:app --host 0.0.0.0 --port 8080

- /_api/...  -> the API (app.main), exactly like the nginx set-up (VITE_API_BASE_URL=/_api), so the
               browser's Host header reaches the API unchanged and links built from APP_BASE_URL
               (http://<host>:<port>/_api) work.
- /assets/... -> the built web app's files (cached), everything else -> index.html (single-page app).
FRONTEND_DIST (default ../frontend/dist next to the backend) says where the built web app is.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.main import app as api

DIST = Path(os.getenv("FRONTEND_DIST") or Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()


@asynccontextmanager
async def lifespan(_app):
    # a mounted app's own start-up (scheduler, background jobs) must still run
    async with api.router.lifespan_context(api):
        yield


async def spa(request):
    path = request.path_params.get("path", "")
    candidate = (DIST / path).resolve()
    if path and candidate.is_file() and DIST in candidate.parents:
        return FileResponse(candidate)
    index = DIST / "index.html"
    if not index.is_file():
        return PlainTextResponse(f"The web app is not built here: {DIST}", status_code=500)
    return FileResponse(index, headers={"Cache-Control": "no-store"})


routes = [Mount("/_api", app=api)]
if (DIST / "assets").is_dir():
    routes.append(Mount("/assets", app=StaticFiles(directory=DIST / "assets"), name="assets"))
routes += [Route("/", spa), Route("/{path:path}", spa)]

app = Starlette(routes=routes, lifespan=lifespan)
