"""FastAPI application factory for the Paynkolay POS web UI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from paynkolay_pos.api.dependencies import (
    PlaywrightThreeDSAutomator,
    create_three_ds_automator,
    static_dir,
    templates_dir,
)
from paynkolay_pos.api.parallel_run_store import ParallelRunStore
from paynkolay_pos.api.routes import (
    callbacks,
    cards,
    config,
    health,
    installments,
    parallel_runs,
    payments,
    reports,
    results,
    three_ds,
)
from paynkolay_pos.api.session_store import PaymentSessionStore
from paynkolay_pos.api.three_ds_store import ThreeDSFormStore


def create_app() -> FastAPI:
    """Create and configure the FastAPI web application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        automator: PlaywrightThreeDSAutomator = app.state.three_ds_automator
        await automator.aclose()

    app = FastAPI(
        title="Paynkolay Sanal POS Web",
        version="0.1.0",
        description="Browser UI and API surface for Paynkolay Sanal POS testing.",
        lifespan=lifespan,
    )
    app.state.payment_session_store = PaymentSessionStore()
    app.state.three_ds_form_store = ThreeDSFormStore()
    app.state.parallel_run_store = ParallelRunStore()
    app.state.credential_report_run = reports.ReportCommandRunState()
    app.state.three_ds_automator = create_three_ds_automator()
    app.mount("/static", StaticFiles(directory=static_dir()), name="static")

    templates = Jinja2Templates(directory=templates_dir())

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> RedirectResponse:
        return RedirectResponse("/static/favicon.svg")

    @app.get("/", include_in_schema=False)
    async def payment_page(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "payment.html",
            {"title": "Payment"},
        )

    @app.get("/result", include_in_schema=False)
    async def result_page(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "result.html",
            {"title": "Result"},
        )

    @app.get("/reports", include_in_schema=False)
    async def reports_page(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "report.html",
            {"title": "Reports"},
        )

    @app.get("/parallel", include_in_schema=False)
    async def parallel_page(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "parallel.html",
            {"title": "Parallel Tests"},
        )

    @app.get("/settings", include_in_schema=False)
    async def settings_page(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"title": "Settings"},
        )

    app.include_router(health.router)
    app.include_router(config.router)
    app.include_router(cards.router)
    app.include_router(installments.router)
    app.include_router(parallel_runs.router)
    app.include_router(payments.router)
    app.include_router(three_ds.router)
    app.include_router(results.router)
    app.include_router(callbacks.router)
    app.include_router(reports.router)
    return app
