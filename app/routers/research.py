"""任务三（六选一方向）：AI 科研协作平台 —— 文献证据工作台
选题来自本人真实科研场景（NTU CCDS 研究生课程项目的文献调研）。
链路：任务发起 → 真实检索(arXiv + Semantic Scholar) → AI 初筛(带理由) → ◇人工收录 →
证据卡抽取(quote 逐字强校验 + 段落级定位) → ◇逐条核验(记录核验人/时间) →
引用式综述 → ◇批准 → 版本化交接包导出。
本版改进：论文可粘贴全文，证据 quote 可命中摘要或全文并定位到第 N 段（报告"后续计划③"）；
核验记录核验人与时间；多用户数据隔离。
红线：不生成不存在的论文；quote 无法命中原文即拒绝入库（防伪造引用）。"""
import json, time, re
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from .. import db, llm, sources
from ..auth import current_user

router = APIRouter(prefix="/api/research", tags=["research"], dependencies=[Depends(current_user)])

# ---------------- 任务 ----------------

class TaskReq(BaseModel):
    question: str
    scope: dict = {}

@router.post("/tasks")
def create_task(req: TaskReq, user=Depends(current_user)):
    tid = db.run("INSERT INTO r_tasks(owner_id,question,scope_json,stage,created_at) VALUES(?,?,?,?,?)",
                 (user["id"], req.question, json.dumps(req.scope, ensure_ascii=False), "retrieve", time.time()))
    db.log("research", "create_task", {"task_id": tid, "question": req.question}, user=user["username"])
    return {"task_id": tid}

@router.get("/tasks")
def tasks(user=Depends(current_user)):
    ts = db.rows("SELECT * FROM r_tasks WHERE owner_id=? ORDER BY id DESC", (user["id"],))
    for t in ts:
        t["scope_json"] = json.loads(t["scope_json"] or "{}")
        t["counts"] = {
            "papers": db.one("SELECT COUNT(*) c FROM r_papers WHERE task_id=?", (t["id"],))["c"],
            "included": db.one("SELECT COUNT(*) c FROM r_papers WHERE task_id=? AND status='included'", (t["id"],))["c"],
            "evidence": db.one("SELECT COUNT(*) c FROM r_evidence WHERE task_id=?", (t["id"],))["c"],
        }
    return ts

def _own_task(tid: int, uid: int):
    t = db.one("SELECT * FROM r_tasks WHERE id=? AND owner_id=?", (tid, uid))
    if not t:
        raise HTTPException(404, "任务不存在")
    return t

@router.get("/tasks/{tid}")
def task(tid: int, user=Depends(current_user)):
    t = _own_task(tid, user["id"])
    t["scope_json"] = json.loads(t["scope_json"] or "{}")
    return t

# ---------------- 真实检索 ----------------

class RetrieveReq(BaseModel):
    task_id: int
    query: str
    use_arxiv: bool = True
    use_s2: bool = True
    use_openalex: bool = True

@router.post("/retrieve")
def retrieve(req: RetrieveReq, user=Depends(current_user)):
    """arXiv API + Semantic Scholar API 真实检索。保存来源/外部ID/原始链接，按链接去重（新增数准确统计）。"""
    _own_task(req.task_id, user["id"])
    found, errors = [], []
    if req.use_arxiv:
        try:
            found += sources.arxiv_search(req.query)
        except Exception as e:
            errors.append(f"arXiv: {type(e).__name__}: {e}")
    if req.use_s2:
        try:
            found += sources.semantic_scholar_search(req.query)
        except Exception as e:
            errors.append(f"SemanticScholar: {type(e).__name__}: {e}")
    if req.use_openalex:
        try:
            found += sources.openalex_search(req.query)
        except Exception as e:
            errors.append(f"OpenAlex: {type(e).__name__}: {e}")
    added = sum(db.insert_ignore(
        "INSERT OR IGNORE INTO r_papers(task_id,source,ext_id,title,authors,year,abstract,url,relevance_json,status,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (req.task_id, p["source"], p["ext_id"], p["title"], p["authors"], p["year"],
         p["abstract"], p["url"], "", "candidate", time.time()))
        for p in found if p.get("url"))
    db.log("research", "retrieve", {"task_id": req.task_id, "query": req.query, "found": len(found),
                                    "added": added, "errors": errors}, user=user["username"])
    if not found and errors:
        raise HTTPException(502, "检索失败：" + " | ".join(errors))
    return {"found": len(found), "added": added, "errors": errors}

@router.get("/papers")
def papers(task_id: int, user=Depends(current_user)):
    _own_task(task_id, user["id"])
    ps = db.rows("SELECT * FROM r_papers WHERE task_id=? ORDER BY status DESC, id", (task_id,))
    for p in ps:
        p["relevance_json"] = json.loads(p["relevance_json"] or "null")
        p["has_fulltext"] = bool(p.pop("fulltext", ""))  # 列表不回传全文，减小载荷
    return ps

class FulltextReq(BaseModel):
    paper_id: int
    text: str

@router.post("/fulltext")
def set_fulltext(req: FulltextReq, user=Depends(current_user)):
    """（改进新增）为已收录文献粘贴全文/正文节选。证据抽取与 quote 校验将扩展到全文并做段落级定位。"""
    p = db.one("SELECT * FROM r_papers WHERE id=?", (req.paper_id,))
    if not p:
        raise HTTPException(404, "文献不存在")
    if len(req.text.strip()) < 200:
        raise HTTPException(400, "全文文本过短（<200字符），请粘贴论文正文内容。")
    db.run("UPDATE r_papers SET fulltext=? WHERE id=?", (req.text.strip()[:200_000], req.paper_id))
    db.log("research", "fulltext", {"paper_id": req.paper_id, "chars": len(req.text)}, user=user["username"])
    return {"ok": True, "chars": len(req.text)}

# ---------------- AI 初筛 + 人工收录 ----------------

class ScreenReq(BaseModel):
    task_id: int

@router.post("/screen")
def screen(req: ScreenReq, user=Depends(current_user)):
    """AI 相关性初筛（依据=标题+摘要，给理由）；收录/排除由人工决定，与 AI 评级分离记录。"""
    t = _own_task(req.task_id, user["id"])
    ps = db.rows("SELECT id,title,year,abstract FROM r_papers WHERE task_id=? AND status='candidate' ORDER BY id LIMIT 40",
                 (req.task_id,))
    if not ps:
        raise HTTPException(400, "没有待筛选的候选文献，请先检索。")
    listing = "\n\n".join(f"[{p['id']}] ({p['year']}) {p['title']}\n摘要: {(p['abstract'] or '（无摘要）')[:600]}" for p in ps)
    data = llm.complete_json(
        "你是文献筛选助理。相关性判断只能依据给定的标题与摘要，不得使用外部想象；摘要缺失时评级最高为 medium 并注明。",
        f"研究问题：{t['question']}\n范围：{t['scope_json']}\n\n候选文献：\n{listing}\n\n"
        f"输出 JSON 数组：[{{id, relevance(high/medium/low), reason(引用摘要中的具体信息), aspect(对应研究问题的哪个方面)}}]",
        max_tokens=4000)
    for item in data:
        db.run("UPDATE r_papers SET relevance_json=? WHERE id=? AND task_id=?",
               (json.dumps(item, ensure_ascii=False), item.get("id"), req.task_id))
    db.log("research", "screen", {"task_id": req.task_id, "screened": len(data)}, user=user["username"])
    return {"screened": len(data)}

class IncludeReq(BaseModel):
    paper_id: int
    decision: str  # included / excluded

@router.post("/include")
def include(req: IncludeReq, user=Depends(current_user)):
    """人工复核收录决定（菱形节点，与 AI 评级分离记录）。"""
    if req.decision not in ("included", "excluded"):
        raise HTTPException(400, "decision 仅允许 included / excluded")
    db.run("UPDATE r_papers SET status=? WHERE id=?", (req.decision, req.paper_id))
    db.log("research", "include", {"paper_id": req.paper_id, "decision": req.decision}, user=user["username"])
    return {"ok": True}

# ---------------- 证据卡（quote 强校验 + 段落级定位） ----------------

_PUNCT_MAP = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
                             "\u2013": "-", "\u2014": "-", "\u00ad": "", "\ufb01": "fi", "\ufb02": "fl"})

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").translate(_PUNCT_MAP)).lower().strip()

def _alnum(s: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", _norm(s))

def locate_quote(quote: str, abstract: str, fulltext: str):
    """quote 逐字命中摘要或全文；命中全文时返回段落号。命不中返回 None（拒绝入库，防伪造引用）。"""
    q = _norm(quote)
    if not q:
        return None
    qa = _alnum(quote)
    if q in _norm(abstract or "") or (qa and qa in _alnum(abstract or "")):
        return "abstract"
    if fulltext:
        for i, para in enumerate(re.split(r"\n\s*\n|\n", fulltext), 1):
            if para.strip() and (q in _norm(para) or (qa and qa in _alnum(para))):
                return f"fulltext 第{i}段"
        if q in _norm(fulltext) or (qa and qa in _alnum(fulltext)):  # 跨段引用
            return "fulltext"
    return None

class EvidenceReq(BaseModel):
    task_id: int

@router.post("/extract_evidence")
def extract_evidence(req: EvidenceReq, user=Depends(current_user)):
    """从已收录文献抽取证据卡。quote 必须逐字命中摘要或全文（服务端校验+定位），否则拒绝入库并计数。"""
    t = _own_task(req.task_id, user["id"])
    ps = db.rows("SELECT id,title,year,abstract,fulltext FROM r_papers WHERE task_id=? AND status='included'",
                 (req.task_id,))
    if not ps:
        raise HTTPException(400, "还没有人工确认收录的文献。请先在筛选页收录。")
    listing = "\n\n".join(
        f"[paper_id={p['id']}] ({p['year']}) {p['title']}\nABSTRACT: {(p['abstract'] or '')[:900]}"
        + (f"\nFULLTEXT(节选): {p['fulltext'][:2500]}" if p["fulltext"] else "")
        for p in ps)
    data = llm.complete_json(
        "你是证据抽取助理。每条 claim 必须来自某篇给定文献；quote 字段必须从该文献给出的 ABSTRACT 或 FULLTEXT 文本中"
        "【原样逐字符复制】一段连续英文原文（10-40 个单词），不得改写、不得翻译、不得用省略号拼接、不得增删标点。"
        "paper_id 必须原样返回给定的数字。摘要与全文均为空的文献跳过。",
        f"研究问题：{t['question']}\n\n已收录文献：\n{listing}\n\n"
        f"抽取 5-12 条与研究问题相关的证据。输出 JSON 数组：[{{paper_id, claim(中文陈述), quote(原句英文逐字), note(与研究问题的关联)}}]",
        max_tokens=4000)
    src = {p["id"]: p for p in ps}
    created, dropped = [], 0
    for e in data:
        try:
            pid_ = int(e.get("paper_id"))
        except (TypeError, ValueError):
            pid_ = None
        p = src.get(pid_)
        quote = (e.get("quote") or "").strip()
        loc = locate_quote(quote, p["abstract"], p["fulltext"]) if p else None
        if not loc:
            dropped += 1  # 依据核验失败：拒绝入库（防伪造引用）
            continue
        eid = db.run("INSERT INTO r_evidence(task_id,paper_id,claim,quote,note,location,status,created_at) "
                     "VALUES(?,?,?,?,?,?,?,?)",
                     (req.task_id, p["id"], e.get("claim", ""), quote, e.get("note", ""), loc, "proposed", time.time()))
        created.append(eid)
    db.log("research", "extract_evidence", {"task_id": req.task_id, "created": created, "dropped_unverified": dropped},
           user=user["username"])
    return {"created": len(created), "dropped_unverified": dropped}

@router.get("/evidence")
def evidence(task_id: int, user=Depends(current_user)):
    _own_task(task_id, user["id"])
    return db.rows("""SELECT e.*, p.title AS paper_title, p.url AS paper_url, p.year AS paper_year
                      FROM r_evidence e JOIN r_papers p ON p.id=e.paper_id WHERE e.task_id=? ORDER BY e.id""",
                   (task_id,))

class ReviewEvidenceReq(BaseModel):
    evidence_id: int
    decision: str  # approved / rejected
    note: str = ""

@router.post("/review_evidence")
def review_evidence(req: ReviewEvidenceReq, user=Depends(current_user)):
    """人工逐条核验证据（可打开原文链接对照）。改进：记录核验人与核验时间（可交接、可追责）。"""
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision 仅允许 approved / rejected")
    e = db.one("SELECT * FROM r_evidence WHERE id=?", (req.evidence_id,))
    if not e:
        raise HTTPException(404, "证据不存在")
    note = e["note"] + (f"\n[人工批注·{user['username']}] {req.note}" if req.note else "")
    db.run("UPDATE r_evidence SET status=?, note=?, reviewer=?, reviewed_at=? WHERE id=?",
           (req.decision, note, user["username"], time.time(), req.evidence_id))
    db.log("research", "review_evidence", {"evidence_id": req.evidence_id, "decision": req.decision, "note": req.note},
           user=user["username"])
    return {"ok": True}

# ---------------- 综述与交接 ----------------

class SynthReq(BaseModel):
    task_id: int

@router.post("/synthesize")
def synthesize(req: SynthReq, user=Depends(current_user)):
    """基于人工核验通过(approved)的证据生成综述：逐句标注 [E#]，只能使用给定证据。"""
    t = _own_task(req.task_id, user["id"])
    es = db.rows("""SELECT e.id,e.claim,p.title,p.year FROM r_evidence e
                    JOIN r_papers p ON p.id=e.paper_id WHERE e.task_id=? AND e.status='approved'""", (req.task_id,))
    if not es:
        raise HTTPException(400, "还没有人工核验通过(approved)的证据，无法生成有依据的综述。")
    listing = "\n".join(f"[E{e['id']}] {e['claim']} —— 来源:《{e['title']}》({e['year']})" for e in es)
    md = llm.complete(
        "你是学术写作助理。综述中的每一个实质性论断后必须紧跟证据编号标注（如 [E12]），只能使用给定证据，"
        "不得引入证据之外的论文、数据或结论；无证据支撑的内容不要写。输出 Markdown。",
        f"研究问题：{t['question']}\n\n已核验证据（唯一可用素材）：\n{listing}\n\n"
        f"写一篇 500-800 字的中文结构化小型综述（问题背景、主要发现分主题归纳、方法对比、局限与开放问题），逐条标注 [E#]。",
        max_tokens=3000)
    prev = db.one("SELECT MAX(version) v FROM r_synth WHERE task_id=?", (req.task_id,))
    ver = (prev["v"] or 0) + 1
    sid = db.run("INSERT INTO r_synth(task_id,version,content_md,status,created_at) VALUES(?,?,?,?,?)",
                 (req.task_id, ver, md, "draft", time.time()))
    db.log("research", "synthesize", {"task_id": req.task_id, "synth_id": sid, "version": ver}, user=user["username"])
    return {"synth_id": sid, "version": ver, "content_md": md}

@router.get("/synth")
def synth(task_id: int, user=Depends(current_user)):
    _own_task(task_id, user["id"])
    return db.rows("SELECT * FROM r_synth WHERE task_id=? ORDER BY version DESC", (task_id,))

class ApproveSynthReq(BaseModel):
    synth_id: int
    decision: str  # approved / draft

@router.post("/approve_synth")
def approve_synth(req: ApproveSynthReq, user=Depends(current_user)):
    if req.decision not in ("approved", "draft"):
        raise HTTPException(400, "decision 仅允许 approved / draft")
    db.run("UPDATE r_synth SET status=? WHERE id=?", (req.decision, req.synth_id))
    db.log("research", "approve_synth", {"synth_id": req.synth_id, "decision": req.decision}, user=user["username"])
    return {"ok": True}

@router.get("/events")
def events(task_id: int = 0, user=Depends(current_user)):
    """任务时间线：本模块全部动作（检索/初筛/收录/抽取/核验/综述/批准）含操作人、时间、参数与异常。"""
    evs = db.rows("SELECT * FROM events WHERE module='research' AND user=? ORDER BY id DESC LIMIT 200",
                  (user["username"],))
    if task_id:
        evs = [e for e in evs if f'"task_id": {task_id}' in (e.get("detail") or "")
               or f'"task_id":{task_id}' in (e.get("detail") or "")]
    return evs

@router.get("/export/{task_id}")
def export(task_id: int, user=Depends(current_user)):
    """导出交接包：综述(最新已批准版) + 证据核验记录（原句/位置/核验人/时间）+ 参考文献表（真实链接）。"""
    t = _own_task(task_id, user["id"])
    s = db.one("SELECT * FROM r_synth WHERE task_id=? AND status='approved' ORDER BY version DESC LIMIT 1", (task_id,)) \
        or db.one("SELECT * FROM r_synth WHERE task_id=? ORDER BY version DESC LIMIT 1", (task_id,))
    es = db.rows("""SELECT e.*, p.title,p.year,p.url FROM r_evidence e JOIN r_papers p ON p.id=e.paper_id
                    WHERE e.task_id=? AND e.status='approved'""", (task_id,))
    refs = db.rows("""SELECT DISTINCT p.title,p.year,p.url,p.source FROM r_evidence e
                      JOIN r_papers p ON p.id=e.paper_id WHERE e.task_id=? AND e.status='approved'""", (task_id,))
    lines = [f"# 调研交接包：{t['question']}", "",
             f"综述版本：v{s['version'] if s else '-'}（状态：{s['status'] if s else '无'}）· 导出人：{user['username']}", "",
             s["content_md"] if s else "（尚未生成综述）", "", "## 证据核验记录", ""]
    for e in es:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["reviewed_at"])) if e["reviewed_at"] else "—"
        lines += [f"- [E{e['id']}] {e['claim']}",
                  f"  - 原文依据：\"{e['quote']}\"（命中位置：{e['location'] or 'abstract'}）",
                  f"  - 来源：《{e['title']}》({e['year']}) {e['url']}",
                  f"  - 核验：{e['reviewer'] or '—'} @ {when}", ""]
    lines += ["## 参考文献", ""] + [f"- 《{r['title']}》({r['year']}) [{r['source']}] {r['url']}" for r in refs]
    db.log("research", "export", {"task_id": task_id}, user=user["username"])
    return {"markdown": "\n".join(lines)}

@router.get("/events")
def events(user=Depends(current_user)):
    return db.rows("SELECT * FROM events WHERE module='research' AND user=? ORDER BY id DESC LIMIT 100", (user["username"],))
