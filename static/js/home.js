/* 总览页：三模块入口 + 交付对照 + 运行状态 */
"use strict";
Router.on("home", async (view) => {
  view.style.removeProperty("--acc");
  let health = null;
  try { health = await API.get("/api/health"); } catch (_) {}
  const mods = [
    { href: "#/marketing", num: "共同必做 01", title: "AI 游戏营销创作工作流", acc: "var(--mk)",
      desc: "真实热点驱动的 YouTube 游戏内容创作：鸣潮 / 终末地 / 异环。热点手动或定时自动更新，来源与时间可追溯，脚本经评价-修改-人工确认后带溯源导出。",
      chain: "RSS热点(手动/定时) → 去重聚类 → 匹配判断 → ◇选题确认 → 脚本 → 评价 → 修改 → ◇定稿导出" },
    { href: "#/drama", num: "共同必做 02", title: "AI 漫剧创作工作流", acc: "var(--dr)",
      desc: "方向A真人剧（超能末世EP1 / 大力甜心EP1）的制作过程产品化：结构化剧本、一致性资产、分镜、生成编排（外部回传 / ComfyUI 自动 / 标注模拟）、关键帧与视频逐帧评价、版本留痕。",
      chain: "剧本结构化 → ◇资产锁定 → 分镜 → ◇镜头确认 → 生成任务 → 评价(含逐帧) → 重跑 → ◇采用导出" },
    { href: "#/research", num: "六选一方向", title: "AI 科研协作平台 · 文献证据工作台", acc: "var(--rs)",
      desc: "面向研究生课程项目的相关工作调研：arXiv/Semantic Scholar 真实检索，证据逐条回链原文（摘要或全文并定位段落），AI 分析与人工核验分离并记录核验人。",
      chain: "真实检索 → AI初筛 → ◇人工收录(可补全文) → 证据核验(quote强校验+段落定位) → ◇逐条核验 → 引用式综述 → ◇批准交接" },
  ];
  view.append(
    h("div", { class: "home-hero" },
      h("h1", {}, "垂类 Agent · 三合一工作台"),
      h("p", {}, "两项共同必做工作流 + 所选方向（AI 科研协作平台）统一交付。每条链路由真实数据源与真实模型调用驱动，菱形节点为人工确认边界，全过程版本化留痕；多用户登录，数据按账号隔离。")),
    h("div", { class: "grid g3" }, mods.map(m =>
      h("a", { class: "card mod-card", href: m.href, style: `--acc:${m.acc}` },
        h("div", { class: "bd" },
          h("div", { class: "num" }, m.num),
          h("h2", {}, m.title),
          h("p", {}, m.desc),
          h("div", { class: "chain" }, m.chain))))),
    h("div", { class: "grid g2", style: "margin-top:16px" },
      h("div", { class: "card" },
        h("div", { class: "hd" }, h("h3", {}, "运行状态")),
        h("div", { class: "bd" }, h("div", { class: "kv" },
          h("dt", {}, "服务"), h("dd", {}, health ? "● 正常" : "○ 后端不可达"),
          h("dt", {}, "当前账号"), h("dd", {}, "@" + Auth.username),
          h("dt", {}, "LLM 提供方"), h("dd", {}, health ? `${health.llm.provider} / ${health.llm.model}` : "—"),
          h("dt", {}, "LLM 密钥"), h("dd", {}, health && health.llm.configured ? "● 已配置" : "○ 未配置（编辑 .env 后重启）"),
          h("dt", {}, "多模态评价"), h("dd", {}, health && health.llm.vision ? "● 可用（Anthropic）" : "○ 当前端点不支持，漫剧图像评价将提示改用文本维度"),
          h("dt", {}, "ComfyUI 自动出图"), h("dd", {}, (() => {
            if (!health) return "—";
            if (health.comfyui) return "● 已配置";
            const d = health.comfy_diag || {};
            if (!d.url_set && !d.workflow_set) return "○ 未配置（.env 设置 COMFYUI_URL 与 COMFYUI_WORKFLOW 后重启，详见《ComfyUI接入指南.md》）";
            if (!d.url_set) return "○ 缺 COMFYUI_URL（如 http://127.0.0.1:8188），改 .env 后重启";
            if (!d.workflow_found) return "○ 工作流模板文件不存在：" + (d.workflow_path || "COMFYUI_WORKFLOW") + "（检查路径，改后重启）";
            return "○ 未配置";
          })())))),
      h("div", { class: "card" },
        h("div", { class: "hd" }, h("h3", {}, "真实运行与模拟边界（对照交付标准）")),
        h("div", { class: "bd", style: "font-size:13px;color:var(--muted)" },
          h("p", {}, "· 热点/文献来源：真实 RSS 与公开 API，保存来源与时间，支持定时自动更新，换输入可复跑。"),
          h("p", {}, "· AI 处理：真实模型调用；未配密钥时明确报 424，不返回伪造结果。"),
          h("p", {}, "· 漫剧图像/视频生成：external 由外部工具人工执行回传；comfyui 经 HTTP API 真实自动出图（需配置）；「simulated」任务全程标注为模拟。"),
          h("p", {}, "· 人工确认：菱形节点必须由人操作，操作人、时间与 AI 动作分离记录在操作留痕中。")))));
});
