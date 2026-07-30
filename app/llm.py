"""LLM 调用层：Anthropic 原生 API 或 OpenAI 兼容端点（DeepSeek / Moonshot / 通义等）。
所有调用真实发生；未配置密钥时抛 LLMNotConfigured（全局映射为 HTTP 424），绝不返回伪造结果。"""
import os, json, re, base64
import httpx

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "deepseek-chat")
TIMEOUT = httpx.Timeout(180.0, connect=15.0)


class LLMNotConfigured(Exception):
    pass


class LLMBadOutput(Exception):
    """模型输出无法解析为 JSON（多为超长截断或格式漂移），映射为 502 并提示重试。"""
    pass


def _check(need_vision=False):
    if PROVIDER == "anthropic" and not ANTHROPIC_KEY:
        raise LLMNotConfigured("未配置 ANTHROPIC_API_KEY。请在 .env 中填写后重启，或将 LLM_PROVIDER 设为 openai 并配置兼容端点。")
    if PROVIDER == "openai":
        if not OPENAI_KEY:
            raise LLMNotConfigured("未配置 OPENAI_API_KEY（OpenAI 兼容端点，如 DeepSeek）。请在 .env 中填写后重启。")
        if need_vision:
            raise LLMNotConfigured("当前 OpenAI 兼容端点未启用多模态评价；图像一致性评价请改用 Anthropic 端点，或仅使用文本维度评价。")


def complete(system: str, user: str, max_tokens: int = 4000, images: list | None = None) -> str:
    """images: [(media_type, base64), ...]，仅 Anthropic 路径支持多模态。"""
    _check(need_vision=bool(images))
    if PROVIDER == "anthropic":
        content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
                   for mt, b64 in (images or [])]
        content.append({"type": "text", "text": user})
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"},
                       json={"model": ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": system,
                             "messages": [{"role": "user", "content": content}]},
                       timeout=TIMEOUT)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    r = httpx.post(f"{OPENAI_BASE}/chat/completions",
                   headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                   json={"model": OPENAI_MODEL, "max_tokens": max_tokens,
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": user}]},
                   timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def complete_json(system: str, user: str, max_tokens: int = 4000, images: list | None = None):
    """要求模型只输出 JSON，并做健壮解析；解析失败自动重试一次，再失败抛 LLMBadOutput(502)。"""
    sys2 = system + "\n\n重要：只输出一个合法 JSON 对象或数组，不要输出任何解释文字、前言或 Markdown 代码围栏；确保 JSON 完整闭合。"
    text = complete(sys2, user, max_tokens=max_tokens, images=images)
    try:
        return parse_json(text)
    except Exception:
        text2 = complete(sys2 + "\n上一次输出不是合法/完整的 JSON，请重新输出，务必完整闭合且更精简。",
                         user, max_tokens=max_tokens, images=images)
        try:
            return parse_json(text2)
        except Exception:
            raise LLMBadOutput("模型两次输出均无法解析为 JSON（可能内容过长被截断）。请重试，或减少输入长度/镜头数后再试。"
                               f" 输出片段：{text2[:180]}")


def parse_json(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.S)
    # 统一花引号/全角引号，避免 JSON 解析失败
    t = t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"[\[{].*[\]}]", t, flags=re.S)
    if m:
        frag = m.group(0)
        try:
            return json.loads(frag)
        except json.JSONDecodeError:
            # 截断修复：去掉最后一个不完整元素后补全括号
            for cut in range(len(frag) - 1, max(len(frag) - 4000, 0), -1):
                if frag[cut] in "}]":
                    head = frag[:cut + 1]
                    opens = head.count("[") - head.count("]")
                    braces = head.count("{") - head.count("}")
                    fixed = head + "}" * max(0, braces) + "]" * max(0, opens)
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        continue
    raise json.JSONDecodeError("no valid json", t[:80], 0)


_MT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}

def img_to_b64(path: str):
    mt = _MT.get(str(path).rsplit(".", 1)[-1].lower(), "image/png")
    with open(path, "rb") as f:
        return mt, base64.b64encode(f.read()).decode()


def status():
    return {"provider": PROVIDER,
            "model": ANTHROPIC_MODEL if PROVIDER == "anthropic" else OPENAI_MODEL,
            "configured": bool(ANTHROPIC_KEY if PROVIDER == "anthropic" else OPENAI_KEY),
            "vision": PROVIDER == "anthropic" and bool(ANTHROPIC_KEY)}
