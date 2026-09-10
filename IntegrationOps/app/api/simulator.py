import asyncio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/simulator")


@router.get("/status")
async def simulated_status(request: Request):
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status_code=404, detail="Demo mode is disabled")

    mode = request.app.state.simulator_mode
    if mode == "healthy":
        return {"status": "healthy", "provider": "demo-upstream"}
    if mode == "slow":
        await asyncio.sleep(request.app.state.simulator_delay_seconds)
        return {"status": "healthy", "provider": "demo-upstream"}
    if mode == "unauthorized":
        return JSONResponse(status_code=401, content={"error": "token expired"})
    if mode == "rate_limit":
        return JSONResponse(status_code=429, headers={"Retry-After": "60"}, content={"error": "rate limited"})
    if mode == "server_error":
        return JSONResponse(status_code=503, content={"error": "upstream unavailable"})
    if mode == "malformed":
        return {"state": "healthy"}
    return {"status": "healthy"}
