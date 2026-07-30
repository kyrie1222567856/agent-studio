# Agent Studio — 垂类 Agent 三合一工作台

一套网页统一交付三项任务（同一站点、三个页面），多用户登录、数据按账号隔离：

| 模块 | 页面 | 核心链路 |
|---|---|---|
| 共同必做 01 · AI 游戏营销创作工作流 | `#/marketing` | 真实热点获取(RSS，手动/**定时自动更新**) → 去重聚类 → 匹配判断 → ◇人工确认选题 → 脚本生成 → 多维评价 → 自动修改(版本化) → ◇人工定稿 → 导出(**含热点溯源与评价记录**) |
| 共同必做 02 · AI 漫剧创作工作流 | `#/drama` | 剧本导入/结构化 → ◇一致性资产锁定(服务端约束) → 分镜关键帧(**服务端强制引用锁定资产**) → ◇镜头确认 → 生成任务(外部回传 / **ComfyUI HTTP API 自动出图** / 标注模拟) → 多模态一致性评价(关键帧 & **视频逐帧**) → 修改重跑 → ◇采用/废弃 → 导出交接 |
| 六选一方向 · AI 科研协作平台 | `#/research` | 真实检索(arXiv+Semantic Scholar) → AI 初筛(带理由) → ◇人工收录(**可补充全文**) → 证据卡(quote 逐字强校验 + **段落级定位**) → ◇逐条核验(**记录核验人/时间**) → 引用式综述 → ◇批准 → 版本化交接包导出 |

◇ = 人工确认节点（界面上以琥珀色菱形标注，AI 不可越过；所有确认动作连同操作人写入操作留痕）。

## 快速启动（本地）

环境：Python 3.10+。

```bash
pip install -r requirements.txt
cp .env.example .env        # 填写 LLM 密钥（二选一即可）
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 打开 http://localhost:8000 → 注册账号 → 使用
```

### .env 配置

```ini
# 方式一：Anthropic（支持漫剧模块的图像多模态一致性评价）
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-sonnet-4-6

# 方式二：OpenAI 兼容端点（DeepSeek / Moonshot / 通义等；无多模态评价）
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.deepseek.com/v1
# OPENAI_MODEL=deepseek-chat

# 可选：ComfyUI 自动出图
# COMFYUI_URL=http://127.0.0.1:8188
# COMFYUI_WORKFLOW=./comfyui_workflow.example.json
```

密钥只存在于服务端 `.env`（已加入 `.gitignore`），不进入前端与代码仓库。

## 部署（提交"可直接访问的网页"）

任选其一：

- **Zeabur（最简单，中文界面，国内可访问）**：zeabur.com 用 GitHub 登录 → 新建项目 → Deploy from GitHub 选本仓库（自动识别 Python）→ Settings 填 Start Command `uvicorn app.main:app --host 0.0.0.0 --port $PORT` → Variables 里逐条添加 .env 的变量 → Networking 生成公开域名即可访问。
- **Render.com（免费档）**：New Web Service → 连接仓库 → Build `pip install -r requirements.txt` → Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT` → 在 Environment 中配置 `.env` 各变量。
- **Railway / Zeabur**：同上，识别 `requirements.txt` 后填 Start 命令即可。
- **Docker**：`docker build -t agent-studio . && docker run -p 8000:8000 --env-file .env agent-studio`
- 校内服务器：直接按"快速启动"运行，配合 `nohup` 或 `systemd`。

注意：SQLite 数据库与上传文件存放于 `data/`（可用环境变量 `DATA_DIR` 重定向到持久卷）。免费平台重启可能清空非持久目录，演示前请重新走一遍链路或挂载持久卷。定时抓取由应用进程内调度，多实例部署时请只保留一个实例或关闭多余实例的调度。

## 真实数据源清单

| 用途 | 来源 | 形式 | 留痕字段 |
|---|---|---|---|
| 游戏热点 | Google News RSS（按游戏关键词搜索） | 公开 RSS | 来源名 / 原始链接 / 发布时间 / 抓取时间 |
| 游戏热点 | Reddit 子版 hot RSS（WutheringWaves 等） | 公开 RSS | 同上 |
| 文献 | arXiv API | 公开 API | 来源 / 外部ID / 原始链接 / 年份 |
| 文献 | Semantic Scholar Graph API | 公开 API | 同上 + 引用数 |

所有来源可在前端替换为其他游戏/检索式后重新运行（"换一批输入仍能运行"）。

## 真实运行与模拟边界（如实说明）

- **真实实现并运行**：注册登录与数据隔离、热点/文献抓取（手动+定时）、LLM 聚类/匹配/脚本/评价/修改/结构化/初筛/证据抽取/综述（需配置密钥）、证据 quote 逐字后端校验与段落定位、全部人工确认与版本留痕（含操作人）、Markdown 导出、ComfyUI 自动出图（需配置其地址与工作流模板）。
- **外部人工执行**：`external` 模式下漫剧图像/视频生成由外部工具（即梦 / GPT Image / Kling / Seedance）人工执行，本系统负责 Prompt 编排、任务状态、结果回传、评价与版本管理——界面明确标注。
- **明确标注的模拟**：`simulated` 模式仅用于验证编排链路，界面以紫色虚线徽章标注"模拟接口"，不计为真实生成。
- **未实现**：视频片段的自动抽帧（当前由用户上传截帧后逐帧评价）；研究模块的 PDF 自动解析（当前粘贴全文文本）。

## 目录结构

```
app/
  main.py          入口 + .env 载入 + 全局错误处理 + 调度器启动(lifespan)
  db.py            SQLite 存储层（三模块 schema + 用户/会话/设置 + 迁移 + 全局写锁）
  auth.py          注册/登录/会话（PBKDF2；current_user 依赖，全部业务路由启用）
  llm.py           LLM 抽象（Anthropic / OpenAI 兼容；JSON 健壮解析；多模态）
  sources.py       真实数据源（RSS / arXiv / Semantic Scholar）
  scheduler.py     热点定时自动抓取（后台协程，复用手动抓取链路）
  comfy.py         ComfyUI HTTP API 客户端（可选，占位符工作流模板）
  routers/
    marketing.py   任务一 API（含定时配置与溯源导出）
    drama.py       任务二 API（含文件上传 / comfyui 模式 / 逐帧评价）
    research.py    任务三 API（含 quote 反伪造校验 / 全文定位 / 核验人）
static/            前端（原生 JS SPA + 统一设计系统，无构建步骤）
data/              运行时数据（SQLite + 上传文件），已 gitignore
comfyui_workflow.example.json   ComfyUI 工作流模板示例（SDXL 文生图，9:16）
```

## 常见失败与提示

- 未登录 / 会话失效 → 401，前端自动跳转登录页。
- LLM 未配置 → 接口返回 424，前端 toast 明确提示编辑 `.env`。
- 外部来源超时/被限流 → 返回 502 并列出各来源失败原因，可重试或减少来源。
- 证据 quote 无法在摘要/全文中命中 → 该条被拒绝入库并计数展示（反伪造机制生效，属预期行为）。
- ComfyUI 未配置却选择 comfyui 模式 → 400 并说明配置方法。
- 分镜生成前未锁定资产 / 未结构化剧本 → 400（服务端强约束）。
