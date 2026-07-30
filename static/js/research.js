/* 任务三 · AI 科研协作平台（文献证据工作台）
   管线：任务发起 → 真实检索(arXiv/S2) → AI 初筛 → ◇人工收录(可补全文) →
   证据卡(quote 强校验+段落级定位) → ◇逐条核验(记录核验人) → 综述(逐句引用) → ◇批准 → 版本化交接 */
"use strict";
(() => {
  const S = { tid: null, stage: "retrieve" };

  Router.on("research", async (view, tid) => {
    view.style.setProperty("--acc", "var(--rs)");
    view.style.setProperty("--acc-soft", "var(--rs-soft)");
    if (tid) { S.tid = +tid; return renderTask(view); }
    renderList(view);
  });

  async function renderList(view) {
    const tasks = await API.get("/api/research/tasks");
    const qIn = h("input", { placeholder: "研究问题（如：LLM 在自动作文评分中的应用与局限）" });
    const kwIn = h("input", { placeholder: "检索关键词提示（英文更佳，如 automated essay scoring LLM）" });
    view.append(
      h("div", { class: "pagehead" },
        h("h1", {}, "03 · AI 科研协作平台 — 文献证据工作台"),
        h("div", { class: "sub" }, "真实检索(arXiv / Semantic Scholar) · 证据回链原文并定位段落 · AI 分析与人工核验分离 · 版本化交接")),
      h("div", { class: "grid g2" },
        h("div", { class: "card" },
          h("div", { class: "hd" }, h("h3", {}, "发起调研任务"),
            actBtn("创建", "acc sm", async () => {
              if (!qIn.value.trim()) return toast("请填写研究问题", true);
              const r = await API.post("/api/research/tasks", { question: qIn.value, scope: { keywords: kwIn.value } });
              location.hash = "#/research/" + r.task_id;
            })),
          h("div", { class: "bd" }, field("研究问题", qIn), field("范围/关键词", kwIn),
            h("div", { class: "notice" }, "平台红线：不生成不存在的论文；每条证据的 quote 必须逐字命中摘要或全文，否则后端拒绝入库；关键判断由研究者确认并记录核验人。"))),
        h("div", { class: "card" },
          h("div", { class: "hd" }, h("h3", {}, "任务列表")),
          h("div", { class: "bd" }, tasks.length ? tasks.map(t =>
            h("div", { style: "padding:10px 0;border-bottom:1px solid var(--line)" },
              h("a", { href: "#/research/" + t.id, style: "font-weight:600" }, t.question),
              h("div", { class: "hint" }, `阶段 ${t.stage} · 文献 ${t.counts.papers}（收录 ${t.counts.included}）· 证据 ${t.counts.evidence} · ${fmtTime(t.created_at)}`)))
            : emptyBox("暂无任务", "以真实科研问题发起——例如课程项目相关工作调研。")))));
  }

  async function renderTask(view) {
    view.innerHTML = "";
    const t = await API.get("/api/research/tasks/" + S.tid);
    const [papers, evidence, synths] = await Promise.all([
      API.get("/api/research/papers?task_id=" + S.tid),
      API.get("/api/research/evidence?task_id=" + S.tid),
      API.get("/api/research/synth?task_id=" + S.tid)]);
    const included = papers.filter(p => p.status === "included");
    const approved = evidence.filter(e => e.status === "approved");
    const approvedSynth = synths.find(s => s.status === "approved");

    view.append(
      h("div", { class: "pagehead" },
        h("h1", {}, t.question),
        h("div", { class: "sub" }, h("a", { href: "#/research" }, "← 返回任务列表"), ` ｜ 范围：${t.scope_json.keywords || "—"}`)),
      rail([
        { key: "retrieve", label: "① 检索", state: S.stage === "retrieve" ? "on" : papers.length ? "done" : "todo" },
        { key: "screen", label: "② 初筛/收录", state: S.stage === "screen" ? "on" : included.length ? "done" : "todo", gate: true, gatePassed: included.length > 0 },
        { key: "evidence", label: "③ 证据核验", state: S.stage === "evidence" ? "on" : approved.length ? "done" : "todo", gate: true, gatePassed: approved.length > 0 },
        { key: "synthesis", label: "④ 综述与交接", state: S.stage === "synthesis" ? "on" : approvedSynth ? "done" : "todo", gate: true, gatePassed: !!approvedSynth },
      ], (k) => { S.stage = k; renderTask(view); }),
      railLegend());

    if (S.stage === "retrieve") view.append(secRetrieve(view, t, papers));
    if (S.stage === "screen") view.append(secScreen(view, papers));
    if (S.stage === "evidence") view.append(secEvidence(view, evidence, included));
    if (S.stage === "synthesis") view.append(secSynth(view, synths, approved));
    view.append(await secTimeline());
  }

  /* 任务时间线：AI/工具调用与人工确认全记录（含运行状态与异常原因），对应任务书"任务时间线/运行记录"要求 */
  async function secTimeline() {
    const evs = await API.get("/api/research/events?task_id=" + S.tid);
    const label = { create_task: "发起任务", retrieve: "真实检索(工具调用)", screen: "AI 初筛", include_decision: "◇人工收录决策",
      fulltext: "补充全文资料", extract_evidence: "AI 证据抽取(含反伪造校验)", review_evidence: "◇人工核验",
      synthesize: "AI 生成综述", approve_synth: "◇人工批准", export: "导出交接包" };
    return h("div", { class: "card", style: "margin-top:18px" },
      h("div", { class: "hd" }, h("h3", {}, "任务时间线 · 运行记录"),
        h("span", { class: "hint", style: "margin:0" }, "AI 处理与人工确认分离记录；工具调用参数、结果计数与异常原因均留痕")),
      h("div", { class: "bd tight" },
        evs.length ? tbl(["时间", "操作人", "动作", "参数 / 结果 / 异常"],
          evs.map(e => {
            let d = {}; try { d = JSON.parse(e.detail); } catch (_) {}
            const isHuman = (e.action || "").match(/include|review|approve|create_task|export/);
            return h("tr", {},
              h("td", { class: "mono" }, fmtTime(e.ts)),
              h("td", { class: "mono" }, e.user || "—"),
              h("td", {}, badge(label[e.action] || e.action, isHuman ? "b-human" : "b-run")),
              h("td", { class: "mono" }, (d.errors && d.errors.length ? "⚠ " + d.errors.join("；") + " ｜ " : "") +
                e.detail.replace(/"errors": \[[^\]]*\],? ?/, "").slice(0, 150)));
          }))
        : h("p", { class: "hint", style: "padding:8px 10px" }, "尚无记录。")));
  }

  function secRetrieve(view, t, papers) {
    const qIn = h("input", { value: t.scope_json.keywords || "" });
    const axCk = h("input", { type: "checkbox", checked: "" });
    const s2Ck = h("input", { type: "checkbox", checked: "" });
    const oaCk = h("input", { type: "checkbox", checked: "" });
    return h("div", { class: "grid" },
      h("div", { class: "card" },
        h("div", { class: "hd" }, h("h3", {}, "真实文献检索"),
          actBtn("执行检索", "acc", async () => {
            const r = await API.post("/api/research/retrieve", { task_id: S.tid, query: qIn.value, use_arxiv: axCk.checked, use_s2: s2Ck.checked, use_openalex: oaCk.checked });
            toast(`检索到 ${r.found} 条，新增 ${r.added} 条` + (r.errors.length ? `；${r.errors.join("；")}` : "")); renderTask(view);
          })),
        h("div", { class: "bd" }, field("检索式（英文）", qIn),
          h("div", { style: "display:flex;gap:18px;font-size:13.5px;flex-wrap:wrap" },
            h("label", {}, axCk, " arXiv"), h("label", {}, s2Ck, " Semantic Scholar"), h("label", {}, oaCk, " OpenAlex")),
          h("div", { class: "hint" }, "三个来源均为公开正规 API，任一失败不影响其余（失败原因逐条展示）。Semantic Scholar 公共池偶发 429 限流，系统自动退避重试，仍失败可稍后再试或在 .env 配置免费 S2_API_KEY；OpenAlex 免密钥、限流宽松，可作稳定兜底。每条记录保存来源、外部 ID、原始链接与年份，按链接去重。"))),
      h("div", { class: "card" },
        h("div", { class: "hd" }, h("h3", {}, `检索结果（${papers.length}）`),
          papers.length ? h("button", { class: "btn sec sm", onclick: () => { S.stage = "screen"; renderTask(view); } }, "下一步：初筛 →") : null),
        h("div", { class: "bd tight" }, papers.length ? h("div", { style: "max-height:440px;overflow:auto" },
          tbl(["来源", "年份", "题目", "状态"], papers.map(p => h("tr", {},
            h("td", { class: "mono" }, p.source), h("td", { class: "mono" }, p.year),
            h("td", {}, h("a", { href: p.url, target: "_blank", rel: "noopener" }, p.title)),
            h("td", {}, statusBadge(p.status))))))
          : emptyBox("暂无文献", "执行检索从真实数据库获取候选。"))));
  }

  function secScreen(view, papers) {
    const cand = papers.filter(p => p.status === "candidate");
    const bar = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, `AI 相关性初筛（待筛 ${cand.length}）`),
        actBtn("AI 初筛（给出评级与理由）", "acc", async () => {
          const r = await API.post("/api/research/screen", { task_id: S.tid });
          toast(`已评级 ${r.screened} 篇——收录与否由你决定`); renderTask(view);
        })),
      h("div", { class: "bd" }, h("div", { class: "hint" }, "AI 评级仅依据标题与摘要并给出理由；「收录/排除」是人工决策，与 AI 评级分离记录。收录后可为文献补充全文，证据将可定位到段落。")));
    const list = papers.filter(p => p.relevance_json || p.status !== "candidate").map(p => {
      const r = p.relevance_json || {};
      const ftTa = h("textarea", { placeholder: "粘贴论文正文（≥200字符）。补充后证据抽取可命中全文并定位到第 N 段。", style: "min-height:110px;font-size:12.5px" });
      return h("div", { class: "evcard" },
        h("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" },
          h("a", { href: p.url, target: "_blank", rel: "noopener", style: "font-weight:600" }, p.title),
          h("span", { class: "mono" }, p.year), statusBadge(p.status),
          r.relevance ? badge("AI: " + r.relevance, r.relevance === "high" ? "b-ok" : r.relevance === "medium" ? "b-human" : "b-bad") : null,
          p.has_fulltext ? badge("已有全文", "b-run") : null),
        r.reason ? h("div", { class: "hint" }, `AI 理由：${r.reason} ｜ 对应方面：${r.aspect || "—"}`) : null,
        h("details", {}, h("summary", { style: "cursor:pointer;font-size:12.5px;color:var(--muted)" }, "摘要"),
          h("p", { style: "font-size:12.5px;color:var(--muted)" }, p.abstract || "（无摘要）")),
        p.status === "included" ? h("details", { style: "margin-top:6px" },
          h("summary", { style: "cursor:pointer;font-size:12.5px;color:var(--muted)" }, p.has_fulltext ? "更新全文" : "补充全文（改进新增）"),
          ftTa, actBtn("保存全文", "sec sm", async () => {
            await API.post("/api/research/fulltext", { paper_id: p.id, text: ftTa.value });
            toast("全文已保存，证据抽取将覆盖全文"); renderTask(view);
          })) : null,
        p.status === "candidate" ? h("div", { style: "margin-top:8px;display:flex;gap:8px" },
          actBtn("✓ 收录", "human sm", async () => { await API.post("/api/research/include", { paper_id: p.id, decision: "included" }); renderTask(view); }),
          actBtn("排除", "bad sm", async () => { await API.post("/api/research/include", { paper_id: p.id, decision: "excluded" }); renderTask(view); })) : null);
    });
    return h("div", {}, bar, ...list, list.length ? null : emptyBox("请先执行检索", ""));
  }

  function secEvidence(view, evidence, included) {
    const bar = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, `证据卡抽取（已收录文献 ${included.length} 篇）`),
        actBtn("AI 抽取证据卡", "acc", async () => {
          const r = await API.post("/api/research/extract_evidence", { task_id: S.tid });
          toast(`入库 ${r.created} 条；${r.dropped_unverified} 条因 quote 无法在原文中核验被系统拒绝`); renderTask(view);
        })),
      h("div", { class: "bd" }, h("div", { class: "hint" },
        "反伪造机制：每条证据的 quote 必须逐字命中该论文摘要或全文，后端强校验并给出命中位置（abstract / fulltext 第N段），不匹配即丢弃并计数。核验通过(approved)的证据才能进入综述。")));
    const list = evidence.map(e => {
      const noteIn = h("input", { placeholder: "人工批注（可空）", style: "font-size:12px" });
      return h("div", { class: "evcard" },
        h("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" },
          h("b", {}, `[E${e.id}] ${e.claim}`), statusBadge(e.status),
          badge("命中：" + (e.location || "abstract"), "b-run"),
          e.reviewer ? h("span", { class: "mono" }, `核验：${e.reviewer} @ ${fmtTime(e.reviewed_at)}`) : null),
        h("div", { class: "q" }, "“" + e.quote + "”"),
        h("div", { class: "hint" }, "来源：", h("a", { href: e.paper_url, target: "_blank", rel: "noopener" }, `《${e.paper_title}》(${e.paper_year})`), ` ｜ ${e.note || ""}`),
        e.status === "proposed" ? h("div", { style: "margin-top:8px;display:flex;gap:8px;flex-wrap:wrap" },
          noteIn,
          actBtn("✓ 核验通过", "human sm", async () => { await API.post("/api/research/review_evidence", { evidence_id: e.id, decision: "approved", note: noteIn.value }); renderTask(view); }),
          actBtn("退回", "bad sm", async () => { await API.post("/api/research/review_evidence", { evidence_id: e.id, decision: "rejected", note: noteIn.value }); renderTask(view); })) : null);
    });
    return h("div", {}, bar, ...list, evidence.length ? null : emptyBox("暂无证据卡", "先收录文献，再执行 AI 抽取。"));
  }

  function secSynth(view, synths, approved) {
    const bar = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, `综述草稿（可用已核验证据 ${approved.length} 条）`),
        actBtn("生成综述新版本", "acc", async () => {
          await API.post("/api/research/synthesize", { task_id: S.tid }); renderTask(view);
        }),
        actBtn("导出交接包", "ok", async () => {
          const r = await API.get("/api/research/export/" + S.tid);
          downloadText("research_handoff.md", r.markdown);
        })),
      h("div", { class: "bd" }, h("div", { class: "hint" }, "综述只允许使用核验通过的证据，逐句标注 [E#]；导出包含证据原句、命中位置、核验人/时间与真实文献链接，可直接交给下一位协作者。")));
    const list = synths.map(s => h("div", { class: "card", style: "margin-bottom:14px" },
      h("div", { class: "hd" }, h("h3", {}, `综述 v${s.version}`), statusBadge(s.status), h("span", { class: "mono" }, fmtTime(s.created_at)),
        s.status === "draft" ? actBtn("✓ 批准此版本", "human sm", async () => {
          await API.post("/api/research/approve_synth", { synth_id: s.id, decision: "approved" }); renderTask(view);
        }) : null),
      h("div", { class: "bd" }, h("pre", { class: "md" }, s.content_md))));
    return h("div", {}, bar, ...list, synths.length ? null : emptyBox("暂无综述", "证据核验通过后生成。"));
  }
})();
