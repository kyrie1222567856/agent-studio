/* 任务一 · 游戏营销热点工作流
   管线：热点获取(手动/定时) → 候选话题 → 匹配判断 → ◇人工确认选题 → 脚本工作台 → ◇确认导出 */
"use strict";
(() => {
  const S = { game: "", stage: "sources", brief: null, cfg: null };

  Router.on("marketing", async (view) => {
    view.style.setProperty("--acc", "var(--mk)");
    view.style.setProperty("--acc-soft", "var(--mk-soft)");
    if (!S.cfg) S.cfg = await API.get("/api/marketing/config");
    if (!S.game) S.game = Object.keys(S.cfg.default_games)[0];
    render(view);
  });

  async function render(view) {
    view.innerHTML = "";
    const briefs = await API.get("/api/marketing/briefs");
    const topics = await API.get("/api/marketing/topics?game=" + encodeURIComponent(S.game));
    const gatePassed = topics.some(t => t.status === "confirmed") || briefs.length > 0;
    const confirmedScript = briefs.length > 0; // 粗略：留痕页 gate 由确认脚本事件体现

    view.append(
      h("div", { class: "pagehead" },
        h("h1", {}, "01 · AI 游戏营销创作工作流"),
        h("div", { class: "sub" }, "真实热点驱动 · 目标平台 YouTube · 来源/更新时间/更新频率全程可追溯")),
      rail([
        { key: "sources", label: "① 热点获取", state: S.stage === "sources" ? "on" : "todo" },
        { key: "topics", label: "② 候选话题池", state: S.stage === "topics" ? "on" : topics.length ? "done" : "todo" },
        { key: "match", label: "③ 匹配判断", state: topics.some(t => t.match_json) ? "done" : "todo" },
        { key: "script", label: "④ 脚本工作台", state: S.stage === "script" ? "on" : gatePassed ? "done" : "todo", gate: true, gatePassed },
        { key: "audit", label: "⑤ 留痕与导出", state: S.stage === "audit" ? "on" : "todo", gate: true, gatePassed: false },
      ], (k) => { S.stage = k === "match" ? "topics" : k; render(view); }),
      railLegend());

    if (S.stage === "sources") view.append(await secSources(view));
    else if (S.stage === "topics") view.append(await secTopics(view, topics));
    else if (S.stage === "script") view.append(await secScript(view, briefs));
    else if (S.stage === "audit") view.append(await secAudit());
  }

  /* ① 来源与热点（手动拉取 + 定时自动更新配置） */
  async function secSources(view) {
    const games = S.cfg.default_games;
    const sel = h("select", { onchange: (e) => { S.game = e.target.value; render(view); } },
      Object.keys(games).map(g => h("option", { value: g, selected: g === S.game ? "" : null }, g)));
    const custom = games[S.game] || { news_queries: [S.game], reddit: [] };
    const qIn = h("input", { value: (custom.news_queries || []).join(", ") });
    const rIn = h("input", { value: (custom.reddit || []).join(", ") });
    const parse = v => v.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    const [hs, sched] = await Promise.all([
      API.get("/api/marketing/hotspots?game=" + encodeURIComponent(S.game)),
      API.get("/api/marketing/schedule")]);

    const intIn = h("input", { type: "number", value: sched.interval_min || 30, min: 5, style: "width:90px" });
    const schedCard = h("div", { class: "card" },
      h("div", { class: "hd" }, h("h3", {}, "定时自动更新（后台调度器）"),
        sched.enabled ? badge("运行中 · 每 " + sched.interval_min + " 分钟", "b-ok") : badge("未开启", "b-draft")),
      h("div", { class: "bd" },
        h("div", { style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap" },
          "更新频率：", intIn, "分钟 / 次",
          actBtn(sched.enabled ? "更新配置" : "开启自动更新", "acc sm", async () => {
            await API.post("/api/marketing/schedule", { game: S.game, news_queries: parse(qIn.value), reddits: parse(rIn.value), interval_min: +intIn.value, enabled: true });
            toast("自动更新已开启，将按频率抓取当前来源"); render(view);
          }),
          sched.enabled ? actBtn("停止", "ghost sm", async () => {
            await API.post("/api/marketing/schedule", { game: S.game, interval_min: +intIn.value, enabled: false });
            render(view);
          }) : null),
        sched.enabled ? h("div", { class: "hint" },
          `目标：《${sched.game}》 ｜ 上次运行：${sched.last_run ? fmtTime(sched.last_run) : "尚未运行"} ｜ 下次运行：${fmtTime(sched.next_run)}`,
          sched.last_result ? ` ｜ 上次结果：${sched.last_result.error ? "失败 " + sched.last_result.error : `抓取 ${sched.last_result.fetched} 条 / 新增 ${sched.last_result.added} 条`}` : "") : 
          h("div", { class: "hint" }, "开启后服务端每到间隔即自动拉取当前配置的真实来源，来源与更新时间全部留痕；也可继续手动拉取。")));

    return h("div", { class: "grid" },
      h("div", { class: "grid g2" },
        h("div", { class: "card" },
          h("div", { class: "hd" }, h("h3", {}, "监测配置 · 真实来源"),
            actBtn("手动拉取热点", "acc", async () => {
              const r = await API.post("/api/marketing/fetch", { game: S.game, news_queries: parse(qIn.value), reddits: parse(rIn.value) });
              toast(`抓取 ${r.fetched} 条，其中新增 ${r.added} 条` + (r.errors.length ? `；部分来源失败：${r.errors.join("；")}` : ""), r.errors.length > 0 && r.fetched === 0);
              render(view);
            })),
          h("div", { class: "bd" },
            field("目标游戏", sel),
            field("Google News 搜索词（逗号分隔）", qIn),
            field("Reddit 子版（逗号分隔）", rIn),
            h("div", { class: "hint" }, "来源为正规 RSS/公开接口；每条记录保存来源、原始链接、发布时间与抓取时间，按 URL 去重。"))),
        schedCard),
      h("div", { class: "card" },
        h("div", { class: "hd" }, h("h3", {}, `热点原始条目（${hs.length}）`),
          hs.length ? h("button", { class: "btn sec sm", onclick: () => { S.stage = "topics"; render(view); } }, "下一步：聚类 →") : null),
        h("div", { class: "bd tight" },
          hs.length ? h("div", { style: "max-height:420px;overflow:auto" },
            tbl(["来源", "标题", "发布时间", "抓取时间"], hs.slice(0, 80).map(x => h("tr", {},
              h("td", { class: "mono" }, x.source),
              h("td", {}, h("a", { href: x.url, target: "_blank", rel: "noopener" }, x.title.slice(0, 60))),
              h("td", { class: "mono" }, (x.published_at || "").slice(0, 22)),
              h("td", { class: "mono" }, (x.fetched_at || "").slice(0, 19))))))
          : emptyBox("还没有热点数据", "手动拉取或开启定时自动更新，从真实 RSS 接口获取近期条目。"))));
  }

  /* ②③ 候选话题池 + 匹配判断 */
  async function secTopics(view, topics) {
    const bar = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, `候选话题池 · ${S.game}`),
        actBtn("AI 去重聚类（生成/追加候选话题）", "acc", async () => {
          const r = await API.post("/api/marketing/cluster", { game: S.game });
          toast(`生成 ${r.topics.length} 个候选话题`); render(view);
        })));
    const cards = topics.length ? topics.map(t => topicCard(view, t))
      : [emptyBox("话题池为空", "先在「热点获取」拉取条目，再执行 AI 去重聚类。")];
    return h("div", {}, bar, ...cards);
  }

  function topicCard(view, t) {
    const m = t.match_json;
    const angleIn = h("input", { placeholder: "确认采用的创作角度（可从 AI 建议中选）" });
    const consIn = h("input", { placeholder: "限制条件（时长/语言/避讳点等，可空）" });
    return h("div", { class: "card", style: "margin-bottom:14px" },
      h("div", { class: "hd" },
        h("h3", {}, t.title), statusBadge(t.status),
        h("span", { class: "mono" }, `#${t.id} · 合并 ${t.hotspot_ids.length} 条来源 · ${fmtTime(t.created_at)}`)),
      h("div", { class: "bd" },
        h("p", { style: "font-size:13.5px" }, t.summary.summary || ""),
        h("p", { class: "hint" }, `时效判断：${t.summary.freshness || "—"} ｜ 合并依据：${t.summary.why_grouped || "—"}`),
        m ? h("div", { style: "margin-top:12px" },
          h("div", { style: "display:flex;gap:10px;align-items:center;margin-bottom:8px" },
            scoreEl(m.score, 100), h("b", {}, m.verdict),
            h("span", { class: "hint" }, `平台 ${m.platform} · 受众 ${m.audience}`)),
          h("div", { class: "kv" },
            h("dt", {}, "依据"), h("dd", {}, (m.reasons || []).map(r => h("div", {}, "· " + r))),
            h("dt", {}, "风险"), h("dd", {}, (m.risks || []).map(r => h("div", { style: "color:var(--bad)" }, "⚠ " + r))),
            h("dt", {}, "可行角度"), h("dd", {}, (m.angles || []).map(a =>
              h("div", {}, h("b", {}, typeof a === "string" ? a : a.name || a.angle || ""), " — ",
                typeof a === "string" ? "" : (a.desc || a.description || a.note || "")))))) : null,
        t.status === "candidate" ? h("div", { style: "margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end" },
          m ? null : actBtn("AI 匹配判断", "acc sm", async () => { await API.post("/api/marketing/match", { topic_id: t.id }); render(view); }),
          m ? h("div", { style: "flex:1;min-width:260px" }, field("创作角度", angleIn), field("限制条件", consIn)) : null,
          m ? actBtn("✓ 人工确认选题 → 生成 Brief", "human sm", async () => {
            if (!angleIn.value.trim()) { toast("请先填写确认采用的创作角度（人工决策）", true); return; }
            await API.post("/api/marketing/confirm_topic", { topic_id: t.id, decision: "confirmed", angle: angleIn.value, constraints: consIn.value });
            toast("选题已确认，Brief 已创建"); S.stage = "script"; render(view);
          }) : null,
          m ? actBtn("否决", "bad sm", async () => {
            await API.post("/api/marketing/confirm_topic", { topic_id: t.id, decision: "rejected" }); render(view);
          }) : null) : null));
  }

  /* ④ 脚本工作台 */
  async function secScript(view, briefs) {
    if (!briefs.length) return emptyBox("还没有已确认的 Brief", "脚本必须基于人工确认的选题生成——请先在「候选话题池」完成匹配判断与人工确认。");
    if (!S.brief || !briefs.find(b => b.id === S.brief)) S.brief = briefs[0].id;
    const b = briefs.find(x => x.id === S.brief);
    const scripts = await API.get("/api/marketing/scripts?brief_id=" + S.brief);

    const briefSel = h("select", { onchange: (e) => { S.brief = +e.target.value; render(view); } },
      briefs.map(x => h("option", { value: x.id, selected: x.id === S.brief ? "" : null }, `Brief#${x.id} · ${x.topic_title}`)));
    const head = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, "创作 Brief"), briefSel,
        actBtn("生成脚本 v1", "acc", async () => {
          await API.post("/api/marketing/generate_script", { brief_id: S.brief }); render(view);
        })),
      h("div", { class: "bd" }, h("div", { class: "kv" },
        h("dt", {}, "游戏"), h("dd", {}, b.game),
        h("dt", {}, "平台 / 受众 / 目标"), h("dd", {}, `${b.platform} ／ ${b.audience} ／ ${b.goal}`),
        h("dt", {}, "确认角度"), h("dd", {}, b.constraints.angle || "—"),
        h("dt", {}, "限制条件"), h("dd", {}, b.constraints.constraints || "—"))));

    const vers = scripts.map(s => scriptCard(view, s, scripts));
    return h("div", {}, head, vers.length ? vers : emptyBox("尚无脚本版本", "点击「生成脚本 v1」，基于已确认热点与 Brief 生成。"));
  }

  function scriptCard(view, s, all) {
    const c = s.content_json, ev = s.eval_json;
    const insIn = h("input", { placeholder: "人工修改指令（可空=按评价自动修改低分部分）" });
    const parent = s.parent_id ? all.find(x => x.id === s.parent_id) : null;
    return h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" },
        h("h3", {}, `脚本 v${s.version} · ${c.title || ""}`), statusBadge(s.status),
        h("span", { class: "mono" }, `#${s.id}${parent ? " ← 修改自 v" + parent.version : ""} · ${fmtTime(s.created_at)}`)),
      h("div", { class: "bd" },
        h("p", {}, h("b", {}, "开场钩子(0-3s)："), c.hook || ""),
        h("div", { style: "margin:10px 0" }, tbl(["秒", "旁白/台词", "屏幕文字", "镜头"],
          (c.segments || []).map(g => h("tr", {},
            h("td", { class: "mono" }, g.sec), h("td", {}, g.vo), h("td", {}, g.screen_text), h("td", {}, g.shot))))),
        h("p", { class: "hint" }, `CTA：${c.cta || ""} ｜ 标签：${(c.tags || []).join(" ")}`),
        h("p", { class: "hint" }, `事实依据：${typeof c.facts_used === "string" ? c.facts_used : JSON.stringify(c.facts_used || "")}`),
        c.change_log ? h("div", { class: "notice info" }, h("b", {}, "本版修改记录："),
          (c.change_log || []).map(x => h("div", {}, "· " + (typeof x === "string" ? x : JSON.stringify(x))))) : null,
        ev ? h("div", { style: "margin-top:10px" },
          h("b", { style: "font-size:13.5px" }, "多维评价"),
          h("div", { style: "margin-top:6px" }, tbl(["维度", "分", "问题定位", "修改建议"],
            (ev.dims || []).map(d => h("tr", {},
              h("td", {}, d.name), h("td", {}, scoreEl(d.score)), h("td", {}, d.issue), h("td", {}, d.suggestion))))),
          h("p", { class: "hint" }, "总评：" + (ev.overall || ""))) : null,
        h("div", { style: "margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:center" },
          !ev ? actBtn("AI 多维评价", "acc sm", async () => { await API.post("/api/marketing/evaluate", { script_id: s.id }); render(view); }) : null,
          ev && s.status !== "confirmed" ? h("div", { style: "flex:1;min-width:240px" }, insIn) : null,
          ev && s.status !== "confirmed" ? actBtn("按评价修改 → 新版本", "sec sm", async () => {
            await API.post("/api/marketing/revise", { script_id: s.id, instruction: insIn.value }); render(view);
          }) : null,
          s.status !== "confirmed" ? actBtn("✓ 人工确认此版为最终脚本", "human sm", async () => {
            await API.post("/api/marketing/confirm_script", { script_id: s.id });
            toast("脚本已确认，导出将附热点溯源与评价记录"); render(view);
          }) : actBtn("导出 Markdown（含溯源）", "ok sm", async () => {
            const r = await API.get("/api/marketing/export/" + s.id);
            downloadText(r.filename, r.markdown);
          }))));
  }

  /* ⑤ 留痕 */
  async function secAudit() {
    const ev = await API.get("/api/marketing/events");
    return h("div", { class: "card" },
      h("div", { class: "hd" }, h("h3", {}, "操作留痕（人工确认与 AI 处理边界记录）")),
      h("div", { class: "bd tight" }, tbl(["时间", "操作人", "动作", "详情"],
        ev.map(e => h("tr", {},
          h("td", { class: "mono" }, fmtTime(e.ts)),
          h("td", { class: "mono" }, e.user || "—"),
          h("td", {}, badge(e.action, e.action.startsWith("confirm") ? "b-human" : e.action.startsWith("auto") ? "b-ok" : "b-run")),
          h("td", { class: "mono" }, e.detail.slice(0, 120)))))));
  }
})();
