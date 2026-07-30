"""真实数据源接入层。所有来源均为正规公开 API / RSS，保留来源、原始链接、发布时间与抓取时间。
不含任何预置假数据；网络失败时向上抛出错误并由前端展示失败原因。"""
import datetime, urllib.parse
import xml.etree.ElementTree as ET
import os, time
import httpx

UA = {"User-Agent": "AgentStudio/1.0 (student capstone project; contact via repo)"}
TIMEOUT = 25.0

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

# ---------------- 热点来源（任务一） ----------------

def google_news_rss(query: str, hl="zh-CN", gl="CN"):
    """Google News RSS 搜索：真实、带发布时间与原始链接。"""
    q = urllib.parse.quote(query)
    ceid = f"{gl}:{'zh-Hans' if hl.startswith('zh') else hl}"
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
    r = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = []
    for item in root.iter("item"):
        out.append({
            "source": f"GoogleNews({query})",
            "title": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
            "published_at": (item.findtext("pubDate") or "").strip(),
            "fetched_at": now_iso(),
        })
    return out

ATOM = "{http://www.w3.org/2005/Atom}"

def reddit_rss(subreddit: str, sort="hot"):
    """Reddit 子版热帖 RSS（Atom 格式）。"""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?limit=25"
    r = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = []
    for e in root.iter(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        out.append({
            "source": f"Reddit(r/{subreddit})",
            "title": (e.findtext(f"{ATOM}title") or "").strip(),
            "url": link.get("href") if link is not None else "",
            "published_at": (e.findtext(f"{ATOM}updated") or "").strip(),
            "fetched_at": now_iso(),
        })
    return out

def youtube_channel_rss(channel_id: str, label: str = ""):
    """YouTube 频道 RSS（官方公开接口），用于跟踪目标游戏官方频道近期发布。"""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    r = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = []
    for e in root.iter(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        out.append({
            "source": f"YouTube({label or channel_id})",
            "title": (e.findtext(f"{ATOM}title") or "").strip(),
            "url": link.get("href") if link is not None else "",
            "published_at": (e.findtext(f"{ATOM}published") or "").strip(),
            "fetched_at": now_iso(),
        })
    return out

# ---------------- 文献来源（任务三） ----------------

def arxiv_search(query: str, max_results=15):
    url = ("https://export.arxiv.org/api/query?search_query=all:" + urllib.parse.quote(query)
           + f"&start=0&max_results={max_results}&sortBy=relevance")
    r = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    out = []
    for e in root.iter(f"{ATOM}entry"):
        authors = [a.findtext(f"{ATOM}name") or "" for a in e.findall(f"{ATOM}author")]
        aid = (e.findtext(f"{ATOM}id") or "").strip()
        out.append({
            "source": "arXiv", "ext_id": aid.rsplit("/", 1)[-1],
            "title": " ".join((e.findtext(f"{ATOM}title") or "").split()),
            "authors": ", ".join(authors[:6]),
            "year": (e.findtext(f"{ATOM}published") or "")[:4],
            "abstract": " ".join((e.findtext(f"{ATOM}summary") or "").split()),
            "url": aid,
        })
    return out

def semantic_scholar_search(query: str, limit=15):
    url = ("https://api.semanticscholar.org/graph/v1/paper/search?query=" + urllib.parse.quote(query)
           + f"&limit={limit}&fields=title,abstract,year,authors,url,externalIds,citationCount")
    hdrs = dict(UA)
    if os.environ.get("S2_API_KEY"):        # 免费申请的 S2 key 可绕开共享限流池
        hdrs["x-api-key"] = os.environ["S2_API_KEY"]
    r = None
    for attempt in range(4):  # 公共接口共享限流(429)常见，指数退避重试
        r = httpx.get(url, headers=hdrs, timeout=TIMEOUT, follow_redirects=True)
        if r.status_code != 429:
            break
        time.sleep(2 * (attempt + 1))
    if r.status_code == 429:
        raise RuntimeError("Semantic Scholar 公共接口限流(429)，已重试仍被限制——请稍等约1分钟后重试，或先只勾选 arXiv")
    r.raise_for_status()
    out = []
    for p in r.json().get("data", []):
        out.append({
            "source": "SemanticScholar",
            "ext_id": p.get("paperId", ""),
            "title": p.get("title", ""),
            "authors": ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:6]),
            "year": str(p.get("year") or ""),
            "abstract": p.get("abstract") or "",
            "url": p.get("url") or "",
            "extra": {"citationCount": p.get("citationCount")},
        })
    return out


def openalex_search(query: str, limit=15):
    """OpenAlex：免密钥、限流宽松的学术索引，作为 S2 被限流时的稳定来源。"""
    url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(query)
           + f"&per-page={limit}&select=id,title,publication_year,authorships,primary_location,abstract_inverted_index,doi")
    r = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        inv = w.get("abstract_inverted_index") or {}
        words = {}
        for token, poss in inv.items():
            for pos in poss:
                words[pos] = token
        abstract = " ".join(words[i] for i in sorted(words)) if words else ""
        url_ = (w.get("doi") or (w.get("primary_location") or {}).get("landing_page_url")
                or w.get("id") or "")
        out.append({
            "source": "OpenAlex", "ext_id": (w.get("id") or "").rsplit("/", 1)[-1],
            "title": w.get("title") or "",
            "authors": ", ".join(a.get("author", {}).get("display_name", "")
                                 for a in (w.get("authorships") or [])[:6]),
            "year": str(w.get("publication_year") or ""),
            "abstract": abstract, "url": url_,
        })
    return out
