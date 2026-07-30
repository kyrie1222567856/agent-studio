"""任务一：AI 游戏营销创作工作流（热点驱动）
链路：热点获取(手动/定时自动) → 去重聚类 → 匹配判断 → ◇人工确认选题(Brief) → 脚本生成 →
多维评价 → 修改再生成(版本链) → ◇人工确认 → 导出（含热点来源与评价记录）。
本版改进：多用户数据隔离；新增/重复计数准确；定时自动抓取配置；导出附完整溯源。"""
import json, time
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from .. import db, llm, sources
from ..auth import current_user

router = APIRouter(prefix="/api/marketing", tags=["marketing"], dependencies=[Depends(current_user)])

DEFAULT_GAMES = {
    "鸣潮 Wuthering Waves": {"news_queries": ["鸣潮", "Wuthering Waves"], "reddit": ["WutheringWaves"]},
    "明日方舟：终末地 Arknights Endfield": {"news_queries": ["明日方舟 终末地", "Arknights Endfield"], "reddit": ["arknights"]},
    "异环 Neverness to Everness": {"news_queries": ["异环 NTE", "Neverness to Everness"], "reddit": ["NTEGame", "gachagaming"]},
}

@router.get("/config")
def config():
    return {"default_games": DEFAULT_GAMES, "llm": llm.status()}

# ---------------- 热点获取（手动 + 定时共用同一真实链路） ----------------

def do_fetch(owner_id: int, game: str, news_queries: list, reddits: list):
    """真实来源拉取：保存来源/原始链接/发布时间/抓取时间；按 (用户,URL) 去重，准确区分新增与重复。"""
    items, errors = [], []
    for q in news_queries:
        try:
            items += sources.google_news_rss(q)
        except Exception as e:
            errors.append(f"GoogleNews({q}): {type(e).__name__}: {e}")
    for sub in reddits:
        try:
            items += sources.reddit_rss(sub)
        except Exception as e:
            errors.append(f"Reddit(r/{sub}): {type(e).__name__}: {e}")
    added = sum(db.insert_ignore(
        "INSERT OR IGNORE INTO hotspots(owner_id,source,title,url,published_at,fetched_at,game,extra) VALUES(?,?,?,?,?,?,?,?)",
        (owner_id, it["source"], it["title"], it["url"], it["published_at"], it["fetched_at"], game, "{}"))
        for it in items if it["url"])
    return {"fetched": len(items), "added": added, "errors": errors}

class FetchReq(BaseModel):
    game: str
    news_queries: list[str] = []
    reddits: list[str] = []

@router.post("/fetch")
def fetch(req: FetchReq, user=Depends(current_user)):
    r = do_fetch(user["id"], req.game, req.news_queries, req.reddits)
    db.log("marketing", "fetch", {"game": req.game, **r}, user=user["username"])
    if not r["fetched"] and r["errors"]:
        raise HTTPException(502, "所有来源抓取失败：" + " | ".join(r["errors"]))
    return r

@router.get("/hotspots")
def hotspots(game: str = "", user=Depends(current_user)):
    w, args = "WHERE owner_id=?", [user["id"]]
    if game:
        w += " AND game=?"; args.append(game)
    return db.rows(f"SELECT * FROM hotspots {w} ORDER BY id DESC LIMIT 200", tuple(args))

# ---------------- 定时自动抓取（改进新增） ----------------

class ScheduleReq(BaseModel):
    game: str
    news_queries: list[str] = []
    reddits: list[str] = []
    interval_min: int = 30
    enabled: bool = True

@router.get("/schedule")
def get_schedule(user=Depends(current_user)):
    return db.setting_get(f"mkt_schedule:{user['id']}", {"enabled": False})

@router.post("/schedule")
def set_schedule(req: ScheduleReq, user=Depends(current_user)):
    cfg = {"game": req.game, "news_queries": req.news_queries, "reddits": req.reddits,
           "interval_min": max(5, req.interval_min), "enabled": req.enabled,
           "next_run": time.time() if req.enabled else 0, "last_run": 0}
    db.setting_set(f"mkt_schedule:{user['id']}", cfg)
    db.log("marketing", "schedule", {"enabled": req.enabled, "interval_min": cfg["interval_min"], "game": req.game},
           user=user["username"])
    return cfg

# ---------------- 去重聚类 / 匹配判断 ----------------

class ClusterReq(BaseModel):
    game: str

@router.post("/cluster")
def cluster(req: ClusterReq, user=Depends(current_user)):
    """LLM 去重聚类：合并同一事件的不同表达，过滤过期/无关，形成候选话题池。"""
    hs = db.rows("SELECT id,source,title,published_at FROM hotspots WHERE owner_id=? AND game=? ORDER BY id DESC LIMIT 120",
                 (user["id"], req.game))
    if not hs:
        raise HTTPException(400, "当前游戏还没有热点数据，请先执行「拉取热点」或开启自动更新。")
    listing = "\n".join(f"[{h['id']}] ({h['source']}, {h['published_at']}) {h['title']}" for h in hs)
    data = llm.complete_json(
        "你是游戏营销内容策划的热点分析助手。依据条目发布时间判断时效。",
        f"以下是围绕游戏《{req.game}》抓取的真实热点条目（编号/来源/发布时间/标题）。\n"
        f"请：1) 合并指向同一事件的条目；2) 过滤与该游戏无关或明显过期(>14天)的条目；3) 输出 3-8 个候选话题。\n"
        f"输出 JSON 数组，每项：title, summary(2句), hotspot_ids(合并条目编号数组), freshness(时效判断), why_grouped(合并依据)。\n\n{listing}",
        max_tokens=3000)
    created = [db.run("INSERT INTO topics(owner_id,title,summary,hotspot_ids,game,status,match_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (user["id"], t.get("title", ""),
                       json.dumps({k: t.get(k, "") for k in ("summary", "freshness", "why_grouped")}, ensure_ascii=False),
                       json.dumps(t.get("hotspot_ids", [])), req.game, "candidate", "", time.time()))
               for t in data]
    db.log("marketing", "cluster", {"game": req.game, "topics": created}, user=user["username"])
    return {"topics": created}

@router.get("/topics")
def topics(game: str = "", user=Depends(current_user)):
    w, args = "WHERE owner_id=?", [user["id"]]
    if game:
        w += " AND game=?"; args.append(game)
    ts = db.rows(f"SELECT * FROM topics {w} ORDER BY id DESC LIMIT 60", tuple(args))
    for t in ts:
        t["summary"] = json.loads(t["summary"]) if t["summary"] else {}
        t["hotspot_ids"] = json.loads(t["hotspot_ids"]) if t["hotspot_ids"] else []
        t["match_json"] = json.loads(t["match_json"]) if t["match_json"] else None
    return ts

def _own_topic(tid: int, uid: int):
    t = db.one("SELECT * FROM topics WHERE id=? AND owner_id=?", (tid, uid))
    if not t:
        raise HTTPException(404, "话题不存在")
    return t

def _topic_hotspots(t):
    hids = json.loads(t["hotspot_ids"] or "[]")
    return db.rows(f"SELECT source,title,url,published_at FROM hotspots WHERE id IN ({','.join('?'*len(hids))})", hids) if hids else []

class MatchReq(BaseModel):
    topic_id: int
    platform: str = "YouTube"
    audience: str = "海外二次元/开放世界玩家，18-30岁"
    goal: str = "新内容曝光与讨论度"

@router.post("/match")
def match(req: MatchReq, user=Depends(current_user)):
    """匹配判断：解释为什么适合/不适合当前游戏、平台、受众与营销目标——给依据与风险，不只给分数。"""
    t = _own_topic(req.topic_id, user["id"])
    ev = "\n".join(f"- ({h['source']}, {h['published_at']}) {h['title']} {h['url']}" for h in _topic_hotspots(t))
    data = llm.complete_json(
        "你是资深游戏内容营销策略师，输出结构化匹配分析。判断要给依据，不要只给分数。",
        f"话题：{t['title']}\n话题概述：{t['summary']}\n关联真实热点条目：\n{ev}\n\n"
        f"任务上下文：游戏《{t['game']}》；发布平台 {req.platform}；目标受众 {req.audience}；营销目标 {req.goal}。\n"
        f"输出 JSON：{{score(0-100), verdict(适合/一般/不适合), reasons(依据数组，每条引用具体热点或游戏/平台事实), "
        f"risks(内容风险数组), angles(2-3个创作角度[{{name,desc}}]), platform_fit(对{req.platform}的适配说明)}}",
        max_tokens=2500)
    db.run("UPDATE topics SET match_json=? WHERE id=?",
           (json.dumps({**data, "platform": req.platform, "audience": req.audience, "goal": req.goal}, ensure_ascii=False), t["id"]))
    db.log("marketing", "match", {"topic_id": t["id"]}, user=user["username"])
    return data

# ---------------- 人工确认选题 → Brief ----------------

class ConfirmTopicReq(BaseModel):
    topic_id: int
    decision: str  # confirmed / rejected
    angle: str = ""
    constraints: str = ""

@router.post("/confirm_topic")
def confirm_topic(req: ConfirmTopicReq, user=Depends(current_user)):
    """人工确认选题（菱形节点）：由用户拍板，形成创作 Brief。"""
    t = _own_topic(req.topic_id, user["id"])
    db.run("UPDATE topics SET status=? WHERE id=?", (req.decision, t["id"]))
    brief_id = None
    if req.decision == "confirmed":
        m = json.loads(t["match_json"] or "{}")
        brief_id = db.run("INSERT INTO briefs(owner_id,topic_id,game,platform,audience,goal,constraints,created_at) VALUES(?,?,?,?,?,?,?,?)",
                          (user["id"], t["id"], t["game"], m.get("platform", "YouTube"), m.get("audience", ""), m.get("goal", ""),
                           json.dumps({"angle": req.angle, "constraints": req.constraints}, ensure_ascii=False), time.time()))
    db.log("marketing", "confirm_topic", {"topic_id": t["id"], "decision": req.decision, "angle": req.angle}, user=user["username"])
    return {"brief_id": brief_id}

@router.get("/briefs")
def briefs(user=Depends(current_user)):
    bs = db.rows("SELECT b.*, t.title AS topic_title FROM briefs b LEFT JOIN topics t ON t.id=b.topic_id "
                 "WHERE b.owner_id=? ORDER BY b.id DESC", (user["id"],))
    for b in bs:
        b["constraints"] = json.loads(b["constraints"] or "{}")
    return bs

def _own_brief(bid: int, uid: int):
    b = db.one("SELECT b.*, t.title AS topic_title, t.match_json, t.hotspot_ids FROM briefs b "
               "JOIN topics t ON t.id=b.topic_id WHERE b.id=? AND b.owner_id=?", (bid, uid))
    if not b:
        raise HTTPException(404, "Brief 不存在")
    return b

# ---------------- 脚本：生成 / 评价 / 修改(版本链) / 确认 / 导出 ----------------

class GenScriptReq(BaseModel):
    brief_id: int
    duration_sec: int = 45

@router.post("/generate_script")
def generate_script(req: GenScriptReq, user=Depends(current_user)):
    b = _own_brief(req.brief_id, user["id"])
    cons = json.loads(b["constraints"] or "{}")
    ev = "\n".join(f"- ({h['source']}, {h['published_at']}) {h['title']}" for h in _topic_hotspots(b))
    data = llm.complete_json(
        "你是面向 YouTube 的游戏短视频编导。脚本必须基于给定的真实热点事实，不得编造未证实内容；不确定的信息标注[需核实]。",
        f"游戏：《{b['game']}》 平台：{b['platform']} 受众：{b['audience']} 目标：{b['goal']}\n"
        f"已确认话题：{b['topic_title']}\n创作角度：{cons.get('angle', '由你依据匹配分析选择最优角度')}\n限制条件：{cons.get('constraints', '无')}\n"
        f"事实依据（真实热点条目）：\n{ev}\n\n"
        f"生成 {req.duration_sec} 秒左右的 YouTube 竖屏(9:16)短视频脚本。输出 JSON：\n"
        f"{{title, hook(前3秒开场), segments:[{{sec, vo(旁白/台词), screen_text, shot(镜头提示)}}], "
        f"cta, tags(数组), facts_used(引用了哪些热点事实), notes(拍摄/素材提示)}}",
        max_tokens=3500)
    sid = db.run("INSERT INTO scripts(brief_id,version,parent_id,content_json,eval_json,status,created_at) VALUES(?,?,?,?,?,?,?)",
                 (b["id"], 1, None, json.dumps(data, ensure_ascii=False), "", "draft", time.time()))
    db.log("marketing", "generate_script", {"brief_id": b["id"], "script_id": sid}, user=user["username"])
    return {"script_id": sid, "content": data}

@router.get("/scripts")
def scripts(brief_id: int, user=Depends(current_user)):
    _own_brief(brief_id, user["id"])
    ss = db.rows("SELECT * FROM scripts WHERE brief_id=? ORDER BY version", (brief_id,))
    for s in ss:
        s["content_json"] = json.loads(s["content_json"] or "{}")
        s["eval_json"] = json.loads(s["eval_json"] or "null")
    return ss

def _own_script(sid: int, uid: int):
    s = db.one("SELECT s.*, b.game, b.platform, b.audience, b.goal, b.topic_id FROM scripts s "
               "JOIN briefs b ON b.id=s.brief_id WHERE s.id=? AND b.owner_id=?", (sid, uid))
    if not s:
        raise HTTPException(404, "脚本不存在")
    return s

EVAL_DIMS = "hotspot_match(热点匹配度), factual(事实依据), hook(开场吸引力), platform_fit(平台适配-YouTube竖屏), risk(内容风险)"

class EvalReq(BaseModel):
    script_id: int

@router.post("/evaluate")
def evaluate(req: EvalReq, user=Depends(current_user)):
    s = _own_script(req.script_id, user["id"])
    data = llm.complete_json(
        "你是严格的短视频脚本审校，逐维度打分并给出可执行修改建议。",
        f"任务上下文：游戏《{s['game']}》 平台 {s['platform']} 受众 {s['audience']} 目标 {s['goal']}\n"
        f"脚本 JSON：\n{s['content_json']}\n\n"
        f"按以下维度评价：{EVAL_DIMS}。输出 JSON：{{dims:[{{key,name,score(0-10),issue(问题定位到具体段落),suggestion}}], overall(总评2句), lowest(最低分维度key)}}",
        max_tokens=2500)
    db.run("UPDATE scripts SET eval_json=?, status='evaluated' WHERE id=?", (json.dumps(data, ensure_ascii=False), s["id"]))
    db.log("marketing", "evaluate", {"script_id": s["id"]}, user=user["username"])
    return data

class ReviseReq(BaseModel):
    script_id: int
    instruction: str = ""

@router.post("/revise")
def revise(req: ReviseReq, user=Depends(current_user)):
    """按评价自动重写低分部分（或按人工指令修改），生成新版本，保留前后版本供对比。"""
    s = _own_script(req.script_id, user["id"])
    if not s["eval_json"]:
        raise HTTPException(400, "请先执行评价，再基于评价修改。")
    data = llm.complete_json(
        "你是短视频脚本修改助手。只修改需要修改的部分，保持其余内容与原 JSON 结构不变。",
        f"原脚本：\n{s['content_json']}\n\n评价结果：\n{s['eval_json']}\n\n"
        f"人工补充要求：{req.instruction or '无，按评价中低分维度的建议修改'}\n"
        f"输出修改后的完整脚本 JSON（结构同原脚本），顶层追加 change_log(数组：每处修改与原因)。",
        max_tokens=3500)
    sid = db.run("INSERT INTO scripts(brief_id,version,parent_id,content_json,eval_json,status,created_at) VALUES(?,?,?,?,?,?,?)",
                 (s["brief_id"], (s["version"] or 1) + 1, s["id"], json.dumps(data, ensure_ascii=False), "", "draft", time.time()))
    db.log("marketing", "revise", {"from": s["id"], "to": sid, "instruction": req.instruction}, user=user["username"])
    return {"script_id": sid, "content": data}

class ConfirmScriptReq(BaseModel):
    script_id: int

@router.post("/confirm_script")
def confirm_script(req: ConfirmScriptReq, user=Depends(current_user)):
    s = _own_script(req.script_id, user["id"])
    db.run("UPDATE scripts SET status='confirmed' WHERE id=?", (s["id"],))
    db.log("marketing", "confirm_script", {"script_id": s["id"]}, user=user["username"])
    return {"ok": True}

@router.get("/export/{script_id}")
def export(script_id: int, user=Depends(current_user)):
    """导出 Markdown（改进：附热点来源溯源 + 最近评价记录 + 版本/确认状态，交付即可核验）。"""
    s = _own_script(script_id, user["id"])
    t = db.one("SELECT * FROM topics WHERE id=?", (s["topic_id"],)) or {}
    c = json.loads(s["content_json"])
    ev = json.loads(s["eval_json"] or "null")
    lines = [f"# {c.get('title', '')}", "",
             f"- 游戏：{s['game']}  平台：{s['platform']}  受众：{s['audience']}",
             f"- 脚本版本：v{s['version']}  状态：{s['status']}  确认人：{user['username']}", "",
             f"**开场钩子（0-3s）**：{c.get('hook', '')}", "", "## 分段脚本", ""]
    for i, seg in enumerate(c.get("segments", []), 1):
        lines += [f"### 段落 {i}（{seg.get('sec', '?')}s）",
                  f"- 旁白：{seg.get('vo', '')}", f"- 屏幕文字：{seg.get('screen_text', '')}", f"- 镜头：{seg.get('shot', '')}", ""]
    lines += [f"**CTA**：{c.get('cta', '')}", "", f"**标签**：{', '.join(c.get('tags', []))}", "",
              f"**事实依据**：{c.get('facts_used', '')}", "", f"**备注**：{c.get('notes', '')}", ""]
    if ev:
        lines += ["## 评价记录（最近一次）", ""] + \
                 [f"- {d.get('name')}：{d.get('score')}/10 —— {d.get('suggestion', '')}" for d in ev.get("dims", [])] + \
                 ["", f"总评：{ev.get('overall', '')}", ""]
    lines += [f"## 热点溯源（话题：{t.get('title', '—')}）", ""] + \
             [f"- ({h['source']}, 发布 {h['published_at']}) {h['title']}  {h['url']}" for h in _topic_hotspots(t)] if t else []
    db.log("marketing", "export", {"script_id": s["id"]}, user=user["username"])
    return {"filename": f"script_v{s['version']}.md", "markdown": "\n".join(lines)}

@router.get("/events")
def events(user=Depends(current_user)):
    return db.rows("SELECT * FROM events WHERE module='marketing' AND user=? ORDER BY id DESC LIMIT 100", (user["username"],))
