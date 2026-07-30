"""任务二：AI 漫剧创作工作流（方向A 真人剧：《超能末世》EP1 英语≤1min / 《大力甜心》EP1 国语1-3min）
链路：剧本导入(版本化) → 结构化 → ◇一致性资产锁定 → 分镜关键帧 → ◇镜头确认 →
生成任务(external 外部工具回传 / comfyui 自动出图 / simulated 标注模拟) → 多模态一致性评价
(关键帧图 & 视频逐帧) → 修改重跑(版本链+失败沉淀) → ◇采用/废弃 → 导出交接。
本版改进：分镜"必须引用锁定资产"改为服务端强约束；回传状态服务端校验；
新增 ComfyUI HTTP API 自动出图模式；新增视频任务的逐帧多模态评价；多用户数据隔离。"""
import json, time, shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from .. import db, llm, comfy
from ..auth import current_user

router = APIRouter(prefix="/api/drama", tags=["drama"], dependencies=[Depends(current_user)])
UPLOAD_DIR = db.DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
IMG_EXTS = ("png", "jpg", "jpeg", "webp")

# 两个真实题目的规格模板（来自任务书，硬规格不可混用）
PRESETS = [
    {"title": "超能末世，大小姐您的外挂已到账 · EP1", "lang": "英语/外国人",
     "spec": {"duration": "≤60s", "ratio": "9:16 竖屏", "format": "MP4", "audience": "海外短剧",
              "style": "真人写实风格；末世/丧尸/异能题材；高冲突快节奏",
              "notes": "前置3-5s高光镜头；1-3s切换；英文台词/旁白/字幕；结尾悬念钩子"}},
    {"title": "大力甜心 · EP1", "lang": "国语/中国人",
     "spec": {"duration": "1-3min", "ratio": "9:16 竖屏", "format": "MP4", "audience": "国内短剧",
              "style": "真人短剧风格；怪力女主×轮椅总裁",
              "notes": "重点验收：站位/表演/机位/物体重量感；男主休闲西装+电动轮椅，女主出场运动装"}},
]

@router.get("/presets")
def presets():
    return {"presets": PRESETS, "comfyui": comfy.available()}

# ---------------- 项目 ----------------

class ProjectReq(BaseModel):
    title: str
    lang: str = ""
    spec: dict = {}

@router.post("/projects")
def create_project(req: ProjectReq, user=Depends(current_user)):
    pid = db.run("INSERT INTO d_projects(owner_id,title,lang,spec_json,status,created_at) VALUES(?,?,?,?,?,?)",
                 (user["id"], req.title, req.lang, json.dumps(req.spec, ensure_ascii=False), "active", time.time()))
    db.log("drama", "create_project", {"project_id": pid, "title": req.title}, user=user["username"])
    return {"project_id": pid}

@router.get("/projects")
def projects(user=Depends(current_user)):
    ps = db.rows("SELECT * FROM d_projects WHERE owner_id=? ORDER BY id DESC", (user["id"],))
    for p in ps:
        p["spec_json"] = json.loads(p["spec_json"] or "{}")
    return ps

def _own_project(pid: int, uid: int):
    p = db.one("SELECT * FROM d_projects WHERE id=? AND owner_id=?", (pid, uid))
    if not p:
        raise HTTPException(404, "项目不存在")
    return p

@router.get("/projects/{pid}")
def project(pid: int, user=Depends(current_user)):
    p = _own_project(pid, user["id"])
    p["spec_json"] = json.loads(p["spec_json"] or "{}")
    return p

# ---------------- 剧本：导入(版本化)与结构化 ----------------

class ScriptImportReq(BaseModel):
    project_id: int
    raw_text: str

@router.post("/import_script")
def import_script(req: ScriptImportReq, user=Depends(current_user)):
    _own_project(req.project_id, user["id"])
    prev = db.one("SELECT MAX(version) v FROM d_scripts WHERE project_id=?", (req.project_id,))
    ver = (prev["v"] or 0) + 1
    sid = db.run("INSERT INTO d_scripts(project_id,version,raw_text,struct_json,status,created_at) VALUES(?,?,?,?,?,?)",
                 (req.project_id, ver, req.raw_text, "", "draft", time.time()))
    db.log("drama", "import_script", {"project_id": req.project_id, "script_id": sid, "version": ver,
                                      "chars": len(req.raw_text)}, user=user["username"])
    return {"script_id": sid, "version": ver}

class StructureReq(BaseModel):
    script_id: int

@router.post("/structure")
def structure(req: StructureReq, user=Depends(current_user)):
    """LLM 结构化剧本：角色/场景/道具/分场/情绪节点；原稿异名与语病按人物表与剧情逻辑修正并记录在 fixes。"""
    s = db.one("SELECT s.*, p.title, p.lang, p.spec_json, p.owner_id FROM d_scripts s "
               "JOIN d_projects p ON p.id=s.project_id WHERE s.id=?", (req.script_id,))
    if not s or s["owner_id"] != user["id"]:
        raise HTTPException(404, "剧本不存在")
    data = llm.complete_json(
        "你是短剧制片助理，从剧本中提取结构化制作信息。原稿若有角色异名或语病，以人物表与剧情逻辑为准修正，并在 fixes 中记录。",
        f"项目：{s['title']}（{s['lang']}）规格：{s['spec_json']}\n剧本原文：\n{s['raw_text'][:12000]}\n\n"
        f"输出 JSON：{{characters:[{{name, role, look(外形/服装要点), voice(声线建议)}}], "
        f"scenes:[{{name, time, place, mood}}], props:[道具名数组], "
        f"sequences:[{{scene, beat, emotion, lines(关键台词数组)}}], fixes:[对原稿问题的修正记录]}}",
        max_tokens=6000)
    db.run("UPDATE d_scripts SET struct_json=?, status='structured' WHERE id=?",
           (json.dumps(data, ensure_ascii=False), req.script_id))
    db.log("drama", "structure", {"script_id": req.script_id}, user=user["username"])
    return data

class StructSaveReq(BaseModel):
    script_id: int
    struct: dict

@router.post("/structure/save")
def structure_save(req: StructSaveReq, user=Depends(current_user)):
    """人工编辑结构化结果后保存（人工修正节点）。"""
    db.run("UPDATE d_scripts SET struct_json=?, status='structured' WHERE id=?",
           (json.dumps(req.struct, ensure_ascii=False), req.script_id))
    db.log("drama", "structure_edit", {"script_id": req.script_id}, user=user["username"])
    return {"ok": True}

@router.get("/scripts")
def scripts(project_id: int, user=Depends(current_user)):
    _own_project(project_id, user["id"])
    ss = db.rows("SELECT * FROM d_scripts WHERE project_id=? ORDER BY version DESC", (project_id,))
    for x in ss:
        x["struct_json"] = json.loads(x["struct_json"] or "null")
    return ss

# ---------------- 一致性资产 ----------------

class AssetReq(BaseModel):
    project_id: int
    kind: str  # character / scene / prop
    name: str
    notes: str = ""

@router.post("/assets")
def create_asset(req: AssetReq, user=Depends(current_user)):
    _own_project(req.project_id, user["id"])
    aid = db.run("INSERT INTO d_assets(project_id,kind,name,version,prompt,params,image_path,status,notes,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (req.project_id, req.kind, req.name, 1, "", "{}", "", "draft", req.notes, time.time()))
    db.log("drama", "create_asset", {"asset_id": aid, "name": req.name}, user=user["username"])
    return {"asset_id": aid}

class AssetPromptReq(BaseModel):
    asset_id: int
    style: str = "真人写实电影质感"

@router.post("/assets/prompt")
def asset_prompt(req: AssetPromptReq, user=Depends(current_user)):
    """为资产生成出图 Prompt（角色=三视图+表情/服装状态；场景/道具=基准图），引用最新结构化剧本。"""
    a = db.one("SELECT a.*, p.title, p.lang FROM d_assets a JOIN d_projects p ON p.id=a.project_id WHERE a.id=?",
               (req.asset_id,))
    if not a:
        raise HTTPException(404, "资产不存在")
    st = db.one("SELECT struct_json FROM d_scripts WHERE project_id=? AND struct_json!='' ORDER BY version DESC LIMIT 1",
                (a["project_id"],))
    ctx = st["struct_json"][:4000] if st else "（暂无结构化剧本）"
    tpl = ("角色资产：输出 front/side/back 三视图统一 Prompt(同一人物、同一服装、白背景、三视图排版)、"
           "2 个关键表情变体、必要的服装状态变体。") if a["kind"] == "character" else \
          "场景/道具资产：输出 1 条基准图 Prompt + 1 条备用角度 Prompt，强调可复用、风格统一。"
    data = llm.complete_json(
        "你是 AI 影像资产的 Prompt 工程师，输出可直接用于主流图像模型(即梦/GPT Image/ComfyUI SDXL)的英文 Prompt，并附中文说明。",
        f"项目：{a['title']}（{a['lang']}）风格基调：{req.style}\n资产：[{a['kind']}] {a['name']}；备注：{a['notes']}\n"
        f"剧本结构化信息（节选）：{ctx}\n\n{tpl}\n"
        f"输出 JSON：{{prompts:[{{label, prompt(英文), negative}}], consistency_keys(必须锁定的一致性要素数组), usage_note(中文)}}",
        max_tokens=2500)
    db.run("UPDATE d_assets SET prompt=? WHERE id=?", (json.dumps(data, ensure_ascii=False), req.asset_id))
    db.log("drama", "asset_prompt", {"asset_id": req.asset_id}, user=user["username"])
    return data

def _save_upload(file: UploadFile, stem: str, exts) -> str:
    ext = (file.filename or "f.png").rsplit(".", 1)[-1].lower()
    if ext not in exts:
        raise HTTPException(400, f"仅支持 {'/'.join(exts)}")
    p = UPLOAD_DIR / f"{stem}.{ext}"
    with open(p, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return p.name

@router.post("/assets/upload")
async def asset_upload(asset_id: int = Form(...), file: UploadFile = File(...), user=Depends(current_user)):
    """上传外部工具（即梦/GPT Image/ComfyUI 等）产出的资产参考图。"""
    a = db.one("SELECT * FROM d_assets WHERE id=?", (asset_id,))
    if not a:
        raise HTTPException(404, "资产不存在")
    name = _save_upload(file, f"asset_{asset_id}_v{a['version']}", IMG_EXTS)
    db.run("UPDATE d_assets SET image_path=? WHERE id=?", (name, asset_id))
    db.log("drama", "asset_upload", {"asset_id": asset_id, "file": name}, user=user["username"])
    return {"image": f"/api/drama/file/{name}"}

class AssetLockReq(BaseModel):
    asset_id: int
    action: str  # lock / new_version

@router.post("/assets/lock")
def asset_lock(req: AssetLockReq, user=Depends(current_user)):
    """人工确认：锁定资产版本（镜头引用锁定版），或开新版本迭代。锁定前必须有参考图（服务端约束）。"""
    a = db.one("SELECT * FROM d_assets WHERE id=?", (req.asset_id,))
    if not a:
        raise HTTPException(404, "资产不存在")
    if req.action == "lock":
        if not a["image_path"]:
            raise HTTPException(400, "锁定前必须上传参考图：镜头一致性依赖已确认的基准图。")
        db.run("UPDATE d_assets SET status='locked' WHERE id=?", (req.asset_id,))
    else:
        db.run("UPDATE d_assets SET status='draft', version=version+1, image_path='' WHERE id=?", (req.asset_id,))
    db.log("drama", "asset_" + req.action, {"asset_id": req.asset_id}, user=user["username"])
    return {"ok": True}

@router.get("/assets")
def assets(project_id: int, user=Depends(current_user)):
    _own_project(project_id, user["id"])
    arr = db.rows("SELECT * FROM d_assets WHERE project_id=? ORDER BY kind, id", (project_id,))
    for a in arr:
        a["prompt"] = json.loads(a["prompt"] or "null")
    return arr

@router.get("/file/{name}")
def get_file(name: str):
    p = UPLOAD_DIR / Path(name).name  # 防路径穿越
    if not p.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(p)

# ---------------- 分镜与关键帧 ----------------

class StoryboardReq(BaseModel):
    project_id: int
    scene: str = ""
    n_shots: int = 6

@router.post("/storyboard")
def storyboard(req: StoryboardReq, user=Depends(current_user)):
    """LLM 生成分镜草案。改进：无结构化剧本/无锁定资产时服务端直接拒绝（此前仅前端提示）。"""
    p = _own_project(req.project_id, user["id"])
    st = db.one("SELECT struct_json FROM d_scripts WHERE project_id=? AND struct_json!='' ORDER BY version DESC LIMIT 1",
                (req.project_id,))
    if not st:
        raise HTTPException(400, "请先完成剧本结构化。")
    locked = db.rows("SELECT id,kind,name,version FROM d_assets WHERE project_id=? AND status='locked'", (req.project_id,))
    if not locked:
        raise HTTPException(400, "分镜必须引用已锁定的一致性资产：请先在「一致性资产」上传参考图并锁定至少一个资产。")
    data = llm.complete_json(
        "你是竖屏短剧分镜师。遵守：1-3秒一切；优先中景/特写；避免空镜/慢镜头/发呆/背面镜头；连续镜头考虑首尾帧衔接。",
        f"项目规格：{p['spec_json']}\n剧本结构：{st['struct_json'][:6000]}\n"
        f"已锁定一致性资产（每个镜头必须通过 asset_ids 引用，禁止引入未锁定的新角色形象）：{json.dumps(locked, ensure_ascii=False)}\n"
        f"为场景「{req.scene or '按剧情顺序的第一场'}」拆 {req.n_shots} 个连续镜头。\n"
        f"输出 JSON 数组，每镜：{{seq, scene, size(景别), camera(机位/运镜), action, line(台词/旁白), emotion, "
        f"first_frame, last_frame, asset_ids(引用的资产id数组), sfx, risk(衔接/一致性风险，可空)}}",
        max_tokens=4000)
    valid = {a["id"] for a in locked}
    ids = []
    for sh in data:
        aids = [i for i in sh.get("asset_ids", []) if i in valid]  # 只保留真实存在的锁定资产引用
        sid = db.run("INSERT INTO d_shots(project_id,seq,scene,shot_json,asset_ids,status,created_at) VALUES(?,?,?,?,?,?,?)",
                     (req.project_id, sh.get("seq", 0), sh.get("scene", req.scene),
                      json.dumps(sh, ensure_ascii=False), json.dumps(aids), "draft", time.time()))
        ids.append(sid)
    db.log("drama", "storyboard", {"project_id": req.project_id, "shots": ids}, user=user["username"])
    return {"shot_ids": ids}

class ShotSaveReq(BaseModel):
    shot_id: int
    shot: dict
    status: str = ""

@router.post("/shots/save")
def shot_save(req: ShotSaveReq, user=Depends(current_user)):
    if req.status and req.status not in ("draft", "confirmed", "discarded"):
        raise HTTPException(400, "非法镜头状态")
    args = [json.dumps(req.shot, ensure_ascii=False), json.dumps(req.shot.get("asset_ids", []))]
    sql = "UPDATE d_shots SET shot_json=?, asset_ids=?"
    if req.status:
        sql += ", status=?"; args.append(req.status)
    sql += " WHERE id=?"; args.append(req.shot_id)
    db.run(sql, tuple(args))
    db.log("drama", "shot_save", {"shot_id": req.shot_id, "status": req.status}, user=user["username"])
    return {"ok": True}

@router.get("/shots")
def shots(project_id: int, user=Depends(current_user)):
    _own_project(project_id, user["id"])
    arr = db.rows("SELECT * FROM d_shots WHERE project_id=? ORDER BY seq, id", (project_id,))
    for s in arr:
        s["shot_json"] = json.loads(s["shot_json"] or "{}")
        s["asset_ids"] = json.loads(s["asset_ids"] or "[]")
    return arr

# ---------------- 生成任务（external / comfyui / simulated） ----------------

MODES = ("external", "comfyui", "simulated")

class TaskReq(BaseModel):
    shot_id: int
    kind: str = "keyframe"  # keyframe / video
    mode: str = "external"

@router.post("/tasks")
def create_task(req: TaskReq, user=Depends(current_user)):
    """编排生成 Prompt。external=外部工具人工执行回传；comfyui=经 HTTP API 自动出图（需配置）；
    simulated=明确标注的模拟接口，仅验证编排，不计为真实生成。"""
    if req.mode not in MODES:
        raise HTTPException(400, "非法模式")
    if req.mode == "comfyui" and not comfy.available():
        raise HTTPException(400, "ComfyUI 未配置，无法使用 comfyui 模式。")
    sh = db.one("SELECT * FROM d_shots WHERE id=?", (req.shot_id,))
    if not sh:
        raise HTTPException(404, "镜头不存在")
    if sh["status"] != "confirmed":
        raise HTTPException(400, "生成任务只针对人工确认过的镜头。")
    aids = json.loads(sh["asset_ids"] or "[]")
    assets_ = db.rows(f"SELECT id,kind,name,version,status FROM d_assets WHERE id IN ({','.join('?'*len(aids))})", aids) if aids else []
    ref = [{"id": a["id"], "kind": a["kind"], "name": a["name"], "version": a["version"],
            "locked": a["status"] == "locked"} for a in assets_]
    tpl = "关键帧图像 Prompt（英文；按任务书建议可输出单帧或九宫格多帧排版版本，注明引用哪张资产参考图作垫图/ID 保持，画幅 9:16）" if req.kind == "keyframe" else \
          "4-15秒 I2V 视频 Prompt（英文，含首帧引用、镜头运动、动作、口型/台词、音效提示）"
    data = llm.complete_json(
        "你是 AI 视频生成的 Prompt 工程师。生成的 Prompt 必须显式引用一致性资产（以 [ASSET#id vN] 标记参考图），不允许脱离资产自由发挥。",
        f"镜头信息：{sh['shot_json']}\n引用资产：{json.dumps(ref, ensure_ascii=False)}\n"
        f"生成 {tpl}。输出 JSON：{{prompt(英文), negative, params(建议参数：模型/时长/比例9:16等), asset_refs(引用说明), first_last_frame(首尾帧衔接说明)}}",
        max_tokens=2000)
    prev = db.one("SELECT MAX(version) v FROM d_tasks WHERE shot_id=? AND kind=?", (req.shot_id, req.kind))
    tid = db.run("INSERT INTO d_tasks(shot_id,kind,version,parent_id,prompt,params,mode,status,result_path,fail_reason,eval_json,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (req.shot_id, req.kind, (prev["v"] or 0) + 1, None, json.dumps(data, ensure_ascii=False),
                  json.dumps(data.get("params", {}), ensure_ascii=False), req.mode, "pending", "", "", "", time.time()))
    db.log("drama", "create_task", {"task_id": tid, "shot_id": req.shot_id, "mode": req.mode}, user=user["username"])
    return {"task_id": tid, "prompt": data}

def _task(tid: int):
    t = db.one("SELECT * FROM d_tasks WHERE id=?", (tid,))
    if not t:
        raise HTTPException(404, "任务不存在")
    return t

class ComfyReq(BaseModel):
    task_id: int

@router.post("/tasks/dispatch_comfy")
def dispatch_comfy(req: ComfyReq, user=Depends(current_user)):
    """将任务 Prompt 提交到 ComfyUI（真实 HTTP 调用），任务转入 submitted。"""
    t = _task(req.task_id)
    if t["kind"] != "keyframe":
        raise HTTPException(400, "ComfyUI 模式当前用于关键帧图像生成；视频段请使用 external 模式。")
    p = json.loads(t["prompt"] or "{}")
    prompt_id = comfy.submit(p.get("prompt", ""), p.get("negative", ""))
    params = json.loads(t["params"] or "{}")
    params["comfy_prompt_id"] = prompt_id
    db.run("UPDATE d_tasks SET status='submitted', params=? WHERE id=?", (json.dumps(params, ensure_ascii=False), t["id"]))
    db.log("drama", "comfy_submit", {"task_id": t["id"], "prompt_id": prompt_id}, user=user["username"])
    return {"prompt_id": prompt_id}

@router.post("/tasks/poll_comfy")
def poll_comfy(req: ComfyReq, user=Depends(current_user)):
    """轮询 ComfyUI 执行结果；完成则下载输出图并落盘为任务结果。"""
    t = _task(req.task_id)
    params = json.loads(t["params"] or "{}")
    pid = params.get("comfy_prompt_id")
    if not pid:
        raise HTTPException(400, "该任务尚未提交到 ComfyUI。")
    status, name = comfy.poll(pid, UPLOAD_DIR, f"task_{t['id']}_v{t['version']}")
    if status == "generated":
        db.run("UPDATE d_tasks SET status='generated', result_path=? WHERE id=?", (name, t["id"]))
        db.log("drama", "comfy_done", {"task_id": t["id"], "file": name}, user=user["username"])
    elif status == "failed":
        db.run("UPDATE d_tasks SET status='failed', fail_reason='ComfyUI 执行失败（见其后台日志）' WHERE id=?", (t["id"],))
        db.log("drama", "comfy_failed", {"task_id": t["id"]}, user=user["username"])
    return {"status": status, "result": name}

@router.post("/tasks/result")
async def task_result(task_id: int = Form(...), status: str = Form(...), fail_reason: str = Form(""),
                      file: UploadFile = File(None), user=Depends(current_user)):
    """回传外部工具执行结果：成功上传关键帧图/视频；失败记录失败原因（失败沉淀）。状态服务端校验。"""
    if status not in ("generated", "failed"):
        raise HTTPException(400, "status 仅允许 generated / failed")
    t = _task(task_id)
    path_name = ""
    if status == "generated":
        if file is None:
            raise HTTPException(400, "回传 generated 必须携带结果文件。")
        path_name = _save_upload(file, f"task_{task_id}_v{t['version']}", IMG_EXTS + ("mp4",))
    db.run("UPDATE d_tasks SET status=?, result_path=?, fail_reason=? WHERE id=?",
           (status, path_name, fail_reason, task_id))
    db.log("drama", "task_result", {"task_id": task_id, "status": status, "fail_reason": fail_reason}, user=user["username"])
    return {"ok": True}

@router.post("/tasks/frames")
async def task_frames(task_id: int = Form(...), files: list[UploadFile] = File(...), user=Depends(current_user)):
    """（改进新增）视频任务逐帧评价支持：上传 1-4 张视频截帧，供多模态评价使用。"""
    t = _task(task_id)
    if t["kind"] != "video":
        raise HTTPException(400, "仅视频任务需要上传截帧；关键帧任务可直接评价结果图。")
    names = [_save_upload(f, f"task_{task_id}_v{t['version']}_frame{i}", IMG_EXTS) for i, f in enumerate(files[:4], 1)]
    params = json.loads(t["params"] or "{}")
    params["frames"] = names
    db.run("UPDATE d_tasks SET params=? WHERE id=?", (json.dumps(params, ensure_ascii=False), task_id))
    db.log("drama", "task_frames", {"task_id": task_id, "frames": names}, user=user["username"])
    return {"frames": [f"/api/drama/file/{n}" for n in names]}

class TaskEvalReq(BaseModel):
    task_id: int

@router.post("/tasks/evaluate")
def task_evaluate(req: TaskEvalReq, user=Depends(current_user)):
    """多模态一致性评价：结果图（关键帧）或视频截帧（改进新增）与锁定资产参考图一并交给视觉模型。"""
    t = db.one("SELECT t.*, s.shot_json, s.asset_ids FROM d_tasks t JOIN d_shots s ON s.id=t.shot_id WHERE t.id=?",
               (req.task_id,))
    if not t:
        raise HTTPException(404, "任务不存在")
    if t["status"] != "generated":
        raise HTTPException(400, "该任务还没有生成结果，请先回传/拉取结果。")
    params = json.loads(t["params"] or "{}")
    if t["result_path"].lower().endswith(".mp4"):
        frames = params.get("frames") or []
        if not frames:
            raise HTTPException(400, "视频任务请先上传 1-4 张视频截帧（逐帧评价），再执行评价。")
        images = [llm.img_to_b64(str(UPLOAD_DIR / f)) for f in frames]
        subject = f"前 {len(frames)} 张图为该视频段按时间顺序的截帧"
    else:
        images = [llm.img_to_b64(str(UPLOAD_DIR / t["result_path"]))]
        subject = "第1张图是本镜头关键帧生成结果"
    aids = json.loads(t["asset_ids"] or "[]")
    refs = db.rows(f"SELECT id,name,image_path FROM d_assets WHERE id IN ({','.join('?'*len(aids))}) AND image_path!=''",
                   aids) if aids else []
    ref_note = []
    for a in refs[:3]:
        images.append(llm.img_to_b64(str(UPLOAD_DIR / a["image_path"])))
        ref_note.append(f"图{len(images)}=资产参考 [{a['id']}]{a['name']}")
    data = llm.complete_json(
        f"你是 AI 影像质检员。{subject}，其余是锁定的一致性资产参考图。逐维度检查并定位具体问题；"
        f"视频截帧还需检查帧间动作连续性。",
        f"镜头要求：{t['shot_json']}\n参考图对应：{'; '.join(ref_note) or '（无参考图，仅按镜头要求评价）'}\n"
        f"输出 JSON：{{dims:[{{key(identity/costume/scene/style/action/frame_link), name, score(0-10), issue, "
        f"fix(改Prompt/换资产/改参数)}}], verdict(可用/需重跑), overall}}",
        max_tokens=2000, images=images)
    db.run("UPDATE d_tasks SET eval_json=? WHERE id=?", (json.dumps(data, ensure_ascii=False), req.task_id))
    db.log("drama", "task_evaluate", {"task_id": req.task_id, "verdict": data.get("verdict")}, user=user["username"])
    return data

class TaskReviseReq(BaseModel):
    task_id: int
    instruction: str = ""

@router.post("/tasks/revise")
def task_revise(req: TaskReviseReq, user=Depends(current_user)):
    """按评价修改 Prompt/参数后生成新版本任务（保留旧版本与失败原因，形成前后差异）。"""
    t = _task(req.task_id)
    data = llm.complete_json(
        "你是 Prompt 修改助手。基于评价问题与人工指令修改生成 Prompt，保留资产引用标记 [ASSET#id vN]，"
        "输出与原结构相同的 JSON，并追加 change_log 数组。",
        f"原 Prompt：{t['prompt']}\n评价：{t['eval_json'] or '（无，按人工指令修改）'}\n人工指令：{req.instruction or '按评价修改'}",
        max_tokens=2000)
    tid = db.run("INSERT INTO d_tasks(shot_id,kind,version,parent_id,prompt,params,mode,status,result_path,fail_reason,eval_json,created_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (t["shot_id"], t["kind"], t["version"] + 1, t["id"], json.dumps(data, ensure_ascii=False),
                  json.dumps(data.get("params", {}), ensure_ascii=False), t["mode"], "pending", "", "", "", time.time()))
    db.log("drama", "task_revise", {"from": req.task_id, "to": tid}, user=user["username"])
    return {"task_id": tid, "prompt": data}

class TaskDecideReq(BaseModel):
    task_id: int
    decision: str  # adopted / discarded
    reason: str = ""

@router.post("/tasks/decide")
def task_decide(req: TaskDecideReq, user=Depends(current_user)):
    """人工采用/废弃生成结果，记录理由（人工最终确认节点）。"""
    if req.decision not in ("adopted", "discarded"):
        raise HTTPException(400, "decision 仅允许 adopted / discarded")
    _task(req.task_id)
    db.run("UPDATE d_tasks SET status=? WHERE id=?", (req.decision, req.task_id))
    db.log("drama", "task_decide", {"task_id": req.task_id, "decision": req.decision, "reason": req.reason},
           user=user["username"])
    return {"ok": True}

@router.get("/tasks")
def tasks(shot_id: int, user=Depends(current_user)):
    arr = db.rows("SELECT * FROM d_tasks WHERE shot_id=? ORDER BY kind, version", (shot_id,))
    for t in arr:
        t["prompt"] = json.loads(t["prompt"] or "null")
        t["params"] = json.loads(t["params"] or "{}")
        t["eval_json"] = json.loads(t["eval_json"] or "null")
    return arr

@router.get("/export/{project_id}")
def export(project_id: int, user=Depends(current_user)):
    """导出镜头交付清单（仅已确认镜头与已采用结果），交给后期剪辑环节。"""
    p = _own_project(project_id, user["id"])
    shots_ = db.rows("SELECT * FROM d_shots WHERE project_id=? AND status='confirmed' ORDER BY seq", (project_id,))
    lines = [f"# {p['title']} 镜头交付清单", "", f"导出人：{user['username']} · 仅含人工确认镜头与已采用结果", ""]
    for s in shots_:
        sj = json.loads(s["shot_json"])
        adopted = db.rows("SELECT * FROM d_tasks WHERE shot_id=? AND status='adopted'", (s["id"],))
        lines += [f"## 镜头 {sj.get('seq')} · {sj.get('scene', '')}",
                  f"- 景别/机位：{sj.get('size', '')} / {sj.get('camera', '')}",
                  f"- 动作：{sj.get('action', '')}", f"- 台词：{sj.get('line', '')}",
                  f"- 首帧：{sj.get('first_frame', '')}", f"- 尾帧：{sj.get('last_frame', '')}",
                  f"- 采用结果：{', '.join(t['result_path'] for t in adopted) or '（待生成）'}", ""]
    db.log("drama", "export", {"project_id": project_id, "shots": len(shots_)}, user=user["username"])
    return {"markdown": "\n".join(lines)}

@router.get("/events")
def events(user=Depends(current_user)):
    return db.rows("SELECT * FROM events WHERE module='drama' AND user=? ORDER BY id DESC LIMIT 100", (user["username"],))
