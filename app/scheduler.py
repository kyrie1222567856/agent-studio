"""热点定时自动抓取（本次改进新增，对应报告"后续计划①/未实现项"）。
每个用户可在前端为某个游戏开启自动更新并设定频率；后台协程每 30s 巡检，
到期即在线程池中执行真实 RSS 抓取，写入该用户的热点池，并把 last_run / next_run /
最近一次结果留痕在配置中——"来源、更新时间、更新频率清楚可见"。"""
import asyncio, time
from . import db
from .routers.marketing import do_fetch  # 复用与手动抓取完全相同的真实链路

CHECK_EVERY = 30  # 秒

def _due(cfg):
    return cfg.get("enabled") and time.time() >= cfg.get("next_run", 0)

async def loop():
    while True:
        try:
            for row in db.rows("SELECT key,value FROM settings WHERE key LIKE 'mkt_schedule:%'"):
                import json
                key, cfg = row["key"], json.loads(row["value"])
                if not _due(cfg):
                    continue
                owner_id = int(key.split(":", 1)[1])
                username = (db.one("SELECT username FROM users WHERE id=?", (owner_id,)) or {}).get("username", "")
                try:
                    r = await asyncio.to_thread(do_fetch, owner_id, cfg["game"],
                                                cfg.get("news_queries", []), cfg.get("reddits", []))
                    cfg["last_result"] = {"fetched": r["fetched"], "added": r["added"], "errors": r["errors"]}
                    db.log("marketing", "auto_fetch", {"game": cfg["game"], **cfg["last_result"]}, user=username)
                except Exception as e:  # 单个用户失败不影响其他调度
                    cfg["last_result"] = {"error": f"{type(e).__name__}: {e}"}
                    db.log("marketing", "auto_fetch_failed", cfg["last_result"], user=username)
                cfg["last_run"] = time.time()
                cfg["next_run"] = time.time() + max(5, cfg.get("interval_min", 30)) * 60
                db.setting_set(key, cfg)
        except Exception:
            pass  # 调度器本体永不因异常退出
        await asyncio.sleep(CHECK_EVERY)
