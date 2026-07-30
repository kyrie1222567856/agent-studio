"""多用户登录与数据隔离（本次改进新增，对应报告"后续计划③/未实现项"）。
密码 PBKDF2-SHA256 加盐哈希入库；会话 token 存服务端可撤销；前端以 Bearer 头携带。
所有业务数据带 owner_id，接口按当前用户过滤——不同账号数据不混淆。"""
import hashlib, secrets, time
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from . import db

router = APIRouter(prefix="/api/auth", tags=["auth"])

def _hash(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 120_000).hex()

class Cred(BaseModel):
    username: str
    password: str

def _issue(uid: int):
    token = secrets.token_urlsafe(32)
    db.run("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, uid, time.time()))
    return token

@router.post("/register")
def register(req: Cred):
    u, p = req.username.strip(), req.password
    if not (3 <= len(u) <= 24) or len(p) < 6:
        raise HTTPException(400, "用户名 3-24 字符，密码至少 6 位。")
    if db.one("SELECT id FROM users WHERE username=?", (u,)):
        raise HTTPException(400, "用户名已存在，请直接登录。")
    salt = secrets.token_hex(16)
    uid = db.run("INSERT INTO users(username,pw_hash,salt,created_at) VALUES(?,?,?,?)",
                 (u, _hash(p, salt), salt, time.time()))
    db.log("auth", "register", {"user_id": uid}, user=u)
    return {"token": _issue(uid), "username": u}

@router.post("/login")
def login(req: Cred):
    u = db.one("SELECT * FROM users WHERE username=?", (req.username.strip(),))
    if not u or _hash(req.password, u["salt"]) != u["pw_hash"]:
        raise HTTPException(401, "用户名或密码错误。")
    db.log("auth", "login", {}, user=u["username"])
    return {"token": _issue(u["id"]), "username": u["username"]}

@router.post("/logout")
def logout(authorization: str = Header("")):
    token = authorization.removeprefix("Bearer ").strip()
    db.run("DELETE FROM sessions WHERE token=?", (token,))
    return {"ok": True}

def current_user(authorization: str = Header("")) -> dict:
    """FastAPI 依赖：校验会话，返回 {id, username}。业务路由统一使用。"""
    token = authorization.removeprefix("Bearer ").strip()
    if token:
        s = db.one("SELECT u.id,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,))
        if s:
            return s
    raise HTTPException(401, "未登录或会话已失效，请重新登录。")

@router.get("/me")
def me(authorization: str = Header("")):
    return current_user(authorization)
