import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import ai_routes, metrics, routes_admin, routes_customer, routes_delivery, routes_handoffs, routes_integration, routes_notifications, routes_onboarding, routes_relay, routes_risk, routes_simple, routes_staff

app = FastAPI(title="AssureOps API", version="0.3.0")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "private, no-store"  # tenant data never enters shared caches
    return response


@app.exception_handler(HTTPException)
async def typed_error(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    return JSONResponse({"detail": detail, "request_id": request.state.request_id}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    message = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"detail": {"code": "invalid_request", "message": message}, "request_id": request.state.request_id}, status_code=422)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(routes_customer.router)
app.include_router(routes_staff.router)
app.include_router(routes_admin.router)
app.include_router(routes_integration.router)
app.include_router(routes_onboarding.router)
app.include_router(ai_routes.router)
app.include_router(routes_delivery.router)
app.include_router(metrics.router)
app.include_router(routes_handoffs.router)
app.include_router(routes_risk.router)
app.include_router(routes_notifications.router)
app.include_router(routes_relay.router)
app.include_router(routes_simple.router)
