"""ComfyUI HTTP API 接入（本次改进新增，对应报告"后续计划②"）。
配置 .env 中 COMFYUI_URL 与 COMFYUI_WORKFLOW（API 格式工作流 JSON 模板，正/负 Prompt 处
写入占位符 __PROMPT__ / __NEGATIVE__）后，漫剧生成任务可选 comfyui 模式自动出图：
submit() 提交工作流 → poll() 轮询 /history 并下载首张输出图。
未配置时明确报错（不降级、不伪装），仍可使用 external / simulated 模式。"""
import os, json, uuid
from pathlib import Path
import httpx
from fastapi import HTTPException

TIMEOUT = 30.0
_ROOT = Path(__file__).resolve().parent.parent  # 项目根目录

def _url() -> str:
    return os.environ.get("COMFYUI_URL", "").rstrip("/")

def _wf() -> Path | None:
    """工作流模板路径：相对路径按项目根目录解析，避免受启动目录影响。"""
    raw = os.environ.get("COMFYUI_WORKFLOW", "").strip().strip('"')
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = _ROOT / p
    return p

def available() -> bool:
    p = _wf()
    return bool(_url() and p and p.exists())

def status() -> dict:
    """诊断信息：便于前端明确提示缺哪一项。"""
    p = _wf()
    return {"url_set": bool(_url()), "workflow_set": p is not None,
            "workflow_found": bool(p and p.exists()), "workflow_path": str(p) if p else ""}

def _require():
    if not available():
        raise HTTPException(400, "ComfyUI 未配置：请在 .env 设置 COMFYUI_URL 与 COMFYUI_WORKFLOW（API 格式工作流模板，含 __PROMPT__ 占位符），"
                                 "或改用 external（外部工具人工执行）/ simulated（标注模拟）模式。")

def submit(prompt: str, negative: str = "") -> str:
    """填充模板并提交，返回 ComfyUI prompt_id。"""
    _require()
    tpl = _wf().read_text(encoding="utf-8")
    graph = json.loads(tpl.replace("__PROMPT__", json.dumps(prompt)[1:-1])
                          .replace("__NEGATIVE__", json.dumps(negative or "lowres, bad anatomy")[1:-1]))
    r = httpx.post(f"{_url()}/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex}, timeout=TIMEOUT)
    r.raise_for_status()
    pid = r.json().get("prompt_id")
    if not pid:
        raise HTTPException(502, f"ComfyUI 未返回 prompt_id：{r.text[:200]}")
    return pid

def poll(prompt_id: str, save_dir: Path, save_stem: str):
    """查询执行历史；完成则下载首张输出图并落盘，返回 (status, filename|None)。"""
    _require()
    r = httpx.get(f"{_url()}/history/{prompt_id}", timeout=TIMEOUT)
    r.raise_for_status()
    hist = r.json().get(prompt_id)
    if not hist:
        return "running", None
    for node in hist.get("outputs", {}).values():
        for img in node.get("images", []):
            q = {"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")}
            resp = httpx.get(f"{_url()}/view", params=q, timeout=TIMEOUT)
            resp.raise_for_status()
            ext = img["filename"].rsplit(".", 1)[-1].lower() or "png"
            name = f"{save_stem}.{ext}"
            (save_dir / name).write_bytes(resp.content)
            return "generated", name
    status = hist.get("status", {})
    if status.get("status_str") == "error":
        return "failed", None
    return "running", None
