"""FastAPI application: read-only endpoints for the web app.

Run it with `map-routing api` (development) or `map-routing ui` (later, with the
web app). It binds to 127.0.0.1 only; there is no authentication.

`create_app` only assembles the app: the store (on `app.state`, see
`dependencies.py`), error handlers and one router per resource. A new view adds a
router module and one `include_router` line here.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from map_routing import __version__
from map_routing.api import areas, scenarios
from map_routing.api.data import BrokenData, DataStore, NotFound
from map_routing.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="map-routing",
        version=__version__,
        summary="Read-only API for the map-routing web app.",
    )
    app.state.store = DataStore(settings or load_settings())

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(BrokenData)
    async def broken_data(_: Request, exc: BrokenData) -> JSONResponse:
        # A server-side data problem (500), but with a message that says what to fix.
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(areas.router)
    app.include_router(scenarios.router)
    return app


def app_factory():
    """Entry point for uvicorn (`--factory`), using settings from the environment."""
    return create_app(load_settings())
