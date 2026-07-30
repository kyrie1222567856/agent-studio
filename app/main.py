"""Agent Studio 主入口。启动：uvicorn app.main:app --host 0.0.0.0 --port 8000
本版改进：多用户登录（/api/auth）、热点定时自动抓取后台调度器（lifespan 启动）。"""
import os, asyncio, contextlib
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx

# 载入 .env（不依赖第三方库；需在业务模块导入前执行）
env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from . import db, llm, auth, scheduler  # noqa: E402
from .routers import marketing, drama, research  # noqa: E402


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()  # 建库/迁移
    task = asyncio.create_task(scheduler.loop())  # 热点自动抓取调度器
    yield
    task.cancel()

app = FastAPI(title="Agent Studio — 垂类 Agent 三合一工作台", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(marketing.router)
app.include_router(drama.router)
app.include_router(research.router)


@app.exception_handler(llm.LLMBadOutput)
async def llm_bad_output(request: Request, exc: llm.LLMBadOutput):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def any_error(request: Request, exc: Exception):
    # 兜底：把真实原因返回给前端 toast，避免只显示 internal error 无从排查
    return JSONResponse(status_code=500, content={"detail": f"服务内部错误：{type(exc).__name__}: {exc}"})


@app.exception_handler(llm.LLMNotConfigured)
async def llm_not_configured(request: Request, exc: llm.LLMNotConfigured):
    return JSONResponse(status_code=424, content={"detail": str(exc)})


@app.exception_handler(httpx.HTTPError)
async def httpx_error(request: Request, exc: httpx.HTTPError):
    return JSONResponse(status_code=502, content={
        "detail": f"外部服务调用失败：{type(exc).__name__}: {exc}。可稍后重试；若为 LLM 调用请检查密钥与网络。"})


@app.get("/api/health")
def health():
    db.conn()
    from . import comfy
    return {"ok": True, "llm": llm.status(), "comfyui": comfy.available(), "comfy_diag": comfy.status()}


STATIC = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
