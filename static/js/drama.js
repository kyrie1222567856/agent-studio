/* 任务二 · AI 漫剧工作流
   管线：剧本导入/结构化 → ◇锁定一致性资产 → 分镜关键帧 → ◇确认分镜 →
   生成任务(external / comfyui / simulated) → 评价修改(含视频逐帧) → ◇采用/废弃 → 导出交接 */
"use strict";
(() => {
  const S = { pid: null, tab: "script", comfy: false };

  Router.on("drama", async (view, pid) => {
    view.style.setProperty("--acc", "var(--dr)");
    view.style.setProperty("--acc-soft", "var(--dr-soft)");
    if (pid) { S.pid = +pid; return renderProject(view); }
    renderList(view);
  });

  async function renderList(view) {
    const [projects, ps] = await Promise.all([API.get("/api/drama/projects"), API.get("/api/drama/presets")]);
    S.comfy = ps.comfyui;
    view.append(
      h("div", { class: "pagehead" },
        h("h1", {}, "02 · AI 漫剧创作工作流"),
        h("div", { class: "sub" }, "方向A · 真人剧 —— 剧本结构化 · 一致性资产 · 分镜关键帧 · 生成编排 · 评价重跑 · 版本留痕")),
      h("div", { class: "grid g2" },
        h("div", { class: "card" },
          h("div", { class: "hd" }, h("h3", {}, "本次真实任务（方向已定：真人剧，共 2 集）")),
          h("div", { class: "bd" }, ps.presets.map(p =>
            h("div", { style: "border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:10px" },
              h("b", {}, p.title), h("div", { class: "hint" }, `${p.lang} · ${p.spec.duration} · ${p.spec.ratio}`),
              h("div", { class: "hint" }, p.spec.notes),
              actBtn("以此规格创建项目", "acc sm", async () => {
                const r = await API.post("/api/drama/projects", { title: p.title, lang: p.lang, spec: p.spec });
                location.hash = "#/drama/" + r.project_id;
              }))))),
        h("div", { class: "card" },
          h("div", { class: "hd" }, h("h3", {}, "我的项目")),
          h("div", { class: "bd" }, projects.length ? projects.map(p =>
            h("div", { style: "display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--line)" },
              h("a", { href: "#/drama/" + p.id, style: "font-weight:600" }, p.title),
              statusBadge(p.status), h("span", { class: "mono" }, fmtTime(p.created_at))))
            : emptyBox("暂无项目", "从左侧真实任务规格创建，或自定义原创故事项目。")))));
  }

  async function renderProject(view) {
    view.innerHTML = "";
    const p = await API.get("/api/drama/projects/" + S.pid);
    const [scripts, assets, shots, ps] = await Promise.all([
      API.get("/api/drama/scripts?project_id=" + S.pid),
      API.get("/api/drama/assets?project_id=" + S.pid),
      API.get("/api/drama/shots?project_id=" + S.pid),
      API.get("/api/drama/presets")]);
    S.comfy = ps.comfyui;
    const structured = scripts.some(s => s.struct_json);
    const lockedAssets = assets.filter(a => a.status === "locked");
    const confirmedShots = shots.filter(s => s.status === "confirmed");

    view.append(
      h("div", { class: "pagehead" },
        h("h1", {}, p.title),
        h("div", { class: "sub" }, `${p.lang} · ${p.spec_json.duration || ""} · ${p.spec_json.ratio || ""} ｜ `,
          h("a", { href: "#/drama" }, "← 返回项目列表"))),
      rail([
        { key: "script", label: "① 剧本/结构化", state: S.tab === "script" ? "on" : structured ? "done" : "todo" },
        { key: "assets", label: "② 一致性资产", state: S.tab === "assets" ? "on" : lockedAssets.length ? "done" : "todo", gate: true, gatePassed: lockedAssets.length > 0 },
        { key: "shots", label: "③ 分镜关键帧", state: S.tab === "shots" ? "on" : confirmedShots.length ? "done" : "todo", gate: true, gatePassed: confirmedShots.length > 0 },
        { key: "tasks", label: "④ 生成·评价·重跑", state: S.tab === "tasks" ? "on" : "todo", gate: true, gatePassed: false },
        { key: "export", label: "⑤ 导出交接", state: S.tab === "export" ? "on" : "todo" },
      ], (k) => { S.tab = k; renderProject(view); }),
      railLegend());

    if (S.tab === "script") view.append(await tabScript(view, scripts));
    if (S.tab === "assets") view.append(tabAssets(view, assets, structured));
    if (S.tab === "shots") view.append(tabShots(view, shots, lockedAssets, structured));
    if (S.tab === "tasks") view.append(await tabTasks(view, confirmedShots));
    if (S.tab === "export") view.append(await tabExport());
  }

  /* ① 剧本 */
  async function tabScript(view, scripts) {
    const ta = h("textarea", { placeholder: "粘贴题目提供的剧本原文（PDF/DOCX 内容），或原创故事文本…", style: "min-height:160px" });
    const importCard = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, "导入真实剧本（版本化）"),
        actBtn("导入为新版本", "acc", async () => {
          if (ta.value.trim().length < 30) { toast("剧本文本过短", true); return; }
          await API.post("/api/drama/import_script", { project_id: S.pid, raw_text: ta.value });
          renderProject(view);
        })),
      h("div", { class: "bd" }, ta,
        h("div", { class: "hint" }, "输入来源与版本自动留痕；结构化结果可人工编辑修正（原稿角色异名/语病以人物表与剧情逻辑为准）。")));

    const list = scripts.map(s => {
      const st = s.struct_json;
      const ed = st ? h("textarea", { style: "min-height:180px;font-family:var(--mono);font-size:12px" }, JSON.stringify(st, null, 2)) : null;
      return h("div", { class: "card", style: "margin-bottom:14px" },
        h("div", { class: "hd" }, h("h3", {}, `剧本 v${s.version}`), statusBadge(s.status),
          h("span", { class: "mono" }, `${(s.raw_text || "").length} 字 · ${fmtTime(s.created_at)}`),
          !st ? actBtn("AI 结构化提取", "acc sm", async () => { await API.post("/api/drama/structure", { script_id: s.id }); renderProject(view); }) : null),
        st ? h("div", { class: "bd" },
          h("div", { class: "kv", style: "margin-bottom:10px" },
            h("dt", {}, "角色"), h("dd", {}, (st.characters || []).map(c => `${c.name}(${c.role})`).join("、")),
            h("dt", {}, "场景"), h("dd", {}, (st.scenes || []).map(c => c.name).join("、")),
            h("dt", {}, "修正记录"), h("dd", {}, (st.fixes || []).join("；") || "—")),
          h("details", {}, h("summary", { style: "cursor:pointer;font-size:13px;color:var(--muted)" }, "查看/人工编辑结构化 JSON"),
            ed, actBtn("保存人工修改", "human sm", async () => {
              try { await API.post("/api/drama/structure/save", { script_id: s.id, struct: JSON.parse(ed.value) }); toast("已保存人工修正"); }
              catch (e) { toast("JSON 解析失败：" + e.message, true); }
            }))) : null);
    });
    return h("div", {}, importCard, ...list);
  }

  /* ② 资产 */
  function tabAssets(view, assets, structured) {
    const KIND = { character: "角色", scene: "场景", prop: "道具" };
    const kindSel = h("select", {}, Object.entries(KIND).map(([k, v]) => h("option", { value: k }, v)));
    const nameIn = h("input", { placeholder: "资产名（如 Reese / 修车店 / 电动轮椅）" });
    const noteIn = h("input", { placeholder: "备注（外形/服装要点）" });
    const create = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, "新建一致性资产"),
        actBtn("创建", "acc sm", async () => {
          if (!nameIn.value.trim()) return toast("请填写资产名", true);
          await API.post("/api/drama/assets", { project_id: S.pid, kind: kindSel.value, name: nameIn.value, notes: noteIn.value });
          renderProject(view);
        })),
      h("div", { class: "bd" },
        structured ? null : h("div", { class: "notice" }, "建议先完成剧本结构化，资产 Prompt 将引用剧本中的角色/场景设定。"),
        h("div", { class: "grid g3" }, field("类型", kindSel), field("名称", nameIn), field("备注", noteIn))));

    const cards = assets.map(a => {
      const fileIn = h("input", { type: "file", accept: "image/*", style: "font-size:12px" });
      return h("div", { class: "card", style: "margin-bottom:14px" },
        h("div", { class: "hd" },
          h("h3", {}, `[${KIND[a.kind]}] ${a.name}`),
          badge("v" + a.version, "b-run"), statusBadge(a.status),
          h("span", { class: "mono" }, "ASSET#" + a.id)),
        h("div", { class: "bd" },
          h("div", { style: "display:flex;gap:16px;flex-wrap:wrap" },
            a.image_path ? h("img", { class: "imgthumb", src: "/api/drama/file/" + a.image_path, alt: a.name }) : null,
            h("div", { style: "flex:1;min-width:280px" },
              a.prompt ? h("details", { open: a.status !== "locked" ? "" : null },
                h("summary", { style: "cursor:pointer;font-size:13px" }, `出图 Prompt（${(a.prompt.prompts || []).length} 条）· 一致性锁定要素：${(a.prompt.consistency_keys || []).join(" / ")}`),
                (a.prompt.prompts || []).map(pp => h("div", { class: "evcard" },
                  h("b", { style: "font-size:12.5px" }, pp.label),
                  h("div", { class: "q" }, pp.prompt),
                  pp.negative ? h("div", { class: "hint" }, "负面：" + pp.negative) : null)),
                h("div", { class: "hint" }, a.prompt.usage_note || "")) : h("p", { class: "hint" }, "尚未生成 Prompt。"),
              h("div", { style: "display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center" },
                a.status !== "locked" ? actBtn(a.prompt ? "重新生成 Prompt" : "AI 生成出图 Prompt", "acc sm", async () => {
                  await API.post("/api/drama/assets/prompt", { asset_id: a.id }); renderProject(view);
                }) : null,
                a.status !== "locked" ? h("span", {}, fileIn) : null,
                a.status !== "locked" ? actBtn("上传外部出图结果", "sec sm", async () => {
                  if (!fileIn.files[0]) return toast("请先选择图片（外部工具人工执行后的产出）", true);
                  const fd = new FormData(); fd.append("asset_id", a.id); fd.append("file", fileIn.files[0]);
                  await API.form("/api/drama/assets/upload", fd); renderProject(view);
                }) : null,
                a.status !== "locked"
                  ? actBtn("✓ 锁定此版本（供镜头引用）", "human sm", async () => {
                      await API.post("/api/drama/assets/lock", { asset_id: a.id, action: "lock" }); renderProject(view);
                    })
                  : actBtn("开新版本迭代", "ghost sm", async () => {
                      await API.post("/api/drama/assets/lock", { asset_id: a.id, action: "new_version" }); renderProject(view);
                    }))))));
    });
    return h("div", {}, create,
      h("div", { class: "notice" }, "出图由外部工具（即梦 / GPT Image / ComfyUI）执行——本工作流负责 Prompt 编排、版本管理与锁定；锁定前必须有参考图（服务端约束）。"),
      ...cards, assets.length ? null : emptyBox("暂无资产", "为主要角色与场景建立基准资产，锁定后供所有镜头引用。"));
  }

  /* ③ 分镜 */
  function tabShots(view, shots, lockedAssets, structured) {
    const sceneIn = h("input", { placeholder: "场景名（可空=剧情第一场）" });
    const nIn = h("input", { type: "number", value: 6, min: 2, max: 12 });
    const gen = h("div", { class: "card", style: "margin-bottom:16px" },
      h("div", { class: "hd" }, h("h3", {}, "AI 生成分镜草案（服务端强制引用锁定资产）"),
        actBtn("生成分镜", "acc", async () => {
          await API.post("/api/drama/storyboard", { project_id: S.pid, scene: sceneIn.value, n_shots: +nIn.value });
          renderProject(view);
        })),
      h("div", { class: "bd" }, h("div", { class: "grid g2" }, field("场景", sceneIn), field("镜头数", nIn)),
        h("div", { class: "hint" }, `当前可引用的锁定资产：${lockedAssets.map(a => `[#${a.id}]${a.name} v${a.version}`).join("、") || "无（生成将被服务端拒绝）"}`),
        structured ? null : h("div", { class: "hint", style: "color:var(--bad)" }, "尚未完成剧本结构化，生成将被服务端拒绝。")));

    const rowsEls = shots.map(s => {
      const j = s.shot_json;
      const ed = h("textarea", { style: "min-height:130px;font-family:var(--mono);font-size:12px" }, JSON.stringify(j, null, 2));
      return h("div", { class: "card", style: "margin-bottom:12px" },
        h("div", { class: "hd" },
          h("h3", {}, `镜头 ${j.seq} · ${j.scene || ""} · ${j.size || ""}`), statusBadge(s.status),
          h("span", { class: "mono" }, `引用资产 ${s.asset_ids.map(i => "#" + i).join(",") || "—"}`)),
        h("div", { class: "bd" },
          h("div", { class: "kv" },
            h("dt", {}, "机位/动作"), h("dd", {}, `${j.camera || ""} ｜ ${j.action || ""}`),
            h("dt", {}, "台词"), h("dd", {}, j.line || "—"),
            h("dt", {}, "首/尾帧"), h("dd", {}, `${j.first_frame || ""} → ${j.last_frame || ""}`),
            j.risk ? h("dt", {}, "风险") : null, j.risk ? h("dd", { style: "color:var(--bad)" }, "⚠ " + j.risk) : null),
          h("details", { style: "margin-top:8px" },
            h("summary", { style: "cursor:pointer;font-size:13px;color:var(--muted)" }, "人工编辑镜头 JSON"),
            ed, actBtn("保存修改", "sec sm", async () => {
              try { await API.post("/api/drama/shots/save", { shot_id: s.id, shot: JSON.parse(ed.value) }); toast("已保存"); renderProject(view); }
              catch (e) { toast("JSON 解析失败", true); }
            })),
          s.status === "draft" ? h("div", { style: "margin-top:10px" },
            actBtn("✓ 人工确认此镜头 → 进入生成", "human sm", async () => {
              await API.post("/api/drama/shots/save", { shot_id: s.id, shot: j, status: "confirmed" }); renderProject(view);
            })) : null));
    });
    return h("div", {}, gen, ...rowsEls, shots.length ? null : emptyBox("暂无分镜", "生成草案后逐镜检查动作、首尾帧衔接与资产引用，再人工确认。"));
  }

  /* ④ 生成任务 */
  async function tabTasks(view, confirmedShots) {
    if (!confirmedShots.length) return emptyBox("没有已确认的镜头", "生成任务只针对人工确认过的镜头——请先在「分镜关键帧」确认。");
    const blocks = [];
    for (const s of confirmedShots) {
      const tasks = await API.get("/api/drama/tasks?shot_id=" + s.id);
      const modeSel = h("select", {},
        h("option", { value: "external" }, "external · 外部工具人工执行"),
        S.comfy ? h("option", { value: "comfyui" }, "comfyui · 自动出图（已配置）") : null,
        h("option", { value: "simulated" }, "simulated · 模拟接口（仅验证编排）"));
      blocks.push(h("div", { class: "card", style: "margin-bottom:16px" },
        h("div", { class: "hd" }, h("h3", {}, `镜头 ${s.shot_json.seq} · ${s.shot_json.scene || ""}`),
          modeSel,
          actBtn("编排关键帧任务", "acc sm", async () => {
            await API.post("/api/drama/tasks", { shot_id: s.id, kind: "keyframe", mode: modeSel.value }); renderProject(view);
          }),
          actBtn("编排视频段任务", "sec sm", async () => {
            await API.post("/api/drama/tasks", { shot_id: s.id, kind: "video", mode: modeSel.value }); renderProject(view);
          })),
        h("div", { class: "bd" },
          tasks.length ? tasks.map(t => taskCard(view, t)) : h("p", { class: "hint" }, "尚无生成任务。"))));
    }
    return h("div", {},
      h("div", { class: "notice" },
        "external：Prompt 交由即梦/Kling/Seedance/ComfyUI 人工执行后回传结果；",
        S.comfy ? "comfyui：经 HTTP API 自动提交与取图（真实调用）；" : "comfyui：未配置（.env 设置 COMFYUI_URL/COMFYUI_WORKFLOW 后可用）；",
        "simulated：全程标注为模拟，仅验证编排链路，不计为真实生成。"),
      ...blocks);
  }

  function taskCard(view, t) {
    const fileIn = h("input", { type: "file", accept: "image/*,video/mp4", style: "font-size:12px" });
    const framesIn = h("input", { type: "file", accept: "image/*", multiple: "", style: "font-size:12px" });
    const failIn = h("input", { placeholder: "失败原因（失败沉淀）", style: "font-size:12px" });
    const insIn = h("input", { placeholder: "修改指令（可空=按评价修改）", style: "font-size:12px" });
    const p = t.prompt || {}, isVideo = (t.result_path || "").endsWith(".mp4");
    const frames = (t.params || {}).frames || [];
    const modeBadge = t.mode === "simulated" ? badge("模拟接口", "b-sim") :
                      t.mode === "comfyui" ? badge("ComfyUI 自动", "b-run") : badge("外部工具", "b-run");
    return h("div", { class: "evcard" },
      h("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" },
        h("b", {}, `${t.kind === "keyframe" ? "关键帧" : "视频段"} v${t.version}`),
        modeBadge, statusBadge(t.status),
        h("span", { class: "mono" }, `TASK#${t.id}${t.parent_id ? " ← #" + t.parent_id : ""}`)),
      h("div", { class: "q" }, p.prompt || ""),
      h("div", { class: "hint" }, `参数：${JSON.stringify(p.params || {})} ｜ 资产引用：${typeof p.asset_refs === "string" ? p.asset_refs : JSON.stringify(p.asset_refs || "")}`),
      p.change_log ? h("div", { class: "notice info", style: "margin:8px 0" }, "修改记录：" + p.change_log.map(x => typeof x === "string" ? x : JSON.stringify(x)).join("；")) : null,
      t.result_path && !isVideo ? h("img", { class: "imgthumb", src: "/api/drama/file/" + t.result_path, style: "margin:8px 0" }) : null,
      isVideo ? h("video", { src: "/api/drama/file/" + t.result_path, controls: "", style: "max-width:220px;border-radius:8px;margin:8px 0;display:block" }) : null,
      frames.length ? h("div", { style: "display:flex;gap:6px;margin:8px 0" },
        frames.map(f => h("img", { class: "imgthumb", style: "max-width:90px;max-height:90px", src: "/api/drama/file/" + f }))) : null,
      t.fail_reason ? h("div", { class: "notice err", style: "margin:8px 0" }, "失败沉淀：" + t.fail_reason) : null,
      t.eval_json ? h("div", { style: "margin:8px 0" },
        tbl(["维度", "分", "问题", "修改方向"],
          (t.eval_json.dims || []).map(d => h("tr", {}, h("td", {}, d.name), h("td", {}, scoreEl(d.score)), h("td", {}, d.issue), h("td", {}, d.fix)))),
        h("p", { class: "hint" }, `结论：${t.eval_json.verdict || ""} · ${t.eval_json.overall || ""}`)) : null,
      h("div", { style: "display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px" },
        /* comfyui 模式：提交与取图 */
        t.mode === "comfyui" && t.status === "pending" ? actBtn("提交到 ComfyUI", "acc sm", async () => {
          await API.post("/api/drama/tasks/dispatch_comfy", { task_id: t.id }); toast("已提交，稍后点击「查询结果」"); renderProject(view);
        }) : null,
        t.mode === "comfyui" && t.status === "submitted" ? actBtn("查询结果", "acc sm", async () => {
          const r = await API.post("/api/drama/tasks/poll_comfy", { task_id: t.id });
          toast(r.status === "running" ? "ComfyUI 仍在执行中" : "状态：" + r.status); renderProject(view);
        }) : null,
        /* external/simulated：人工回传 */
        t.mode !== "comfyui" && t.status === "pending" ? h("span", {}, fileIn) : null,
        t.mode !== "comfyui" && t.status === "pending" ? actBtn("回传生成结果", "sec sm", async () => {
          if (!fileIn.files[0]) return toast("请选择结果文件", true);
          const fd = new FormData(); fd.append("task_id", t.id); fd.append("status", "generated"); fd.append("file", fileIn.files[0]);
          await API.form("/api/drama/tasks/result", fd); renderProject(view);
        }) : null,
        t.status === "pending" ? h("span", {}, failIn) : null,
        t.status === "pending" ? actBtn("标记失败", "bad sm", async () => {
          const fd = new FormData(); fd.append("task_id", t.id); fd.append("status", "failed"); fd.append("fail_reason", failIn.value || "未填写");
          await API.form("/api/drama/tasks/result", fd); renderProject(view);
        }) : null,
        /* 视频逐帧评价（改进新增） */
        t.status === "generated" && isVideo ? h("span", {}, framesIn) : null,
        t.status === "generated" && isVideo ? actBtn("上传视频截帧(1-4张)", "sec sm", async () => {
          if (!framesIn.files.length) return toast("请选择 1-4 张视频截帧", true);
          const fd = new FormData(); fd.append("task_id", t.id);
          [...framesIn.files].slice(0, 4).forEach(f => fd.append("files", f));
          await API.form("/api/drama/tasks/frames", fd); renderProject(view);
        }) : null,
        t.status === "generated" && !t.eval_json ? actBtn(isVideo ? "逐帧多模态评价" : "多模态一致性评价", "acc sm", async () => {
          await API.post("/api/drama/tasks/evaluate", { task_id: t.id }); renderProject(view);
        }) : null,
        ["generated", "failed"].includes(t.status) ? h("span", {}, insIn) : null,
        ["generated", "failed"].includes(t.status) ? actBtn("修改 Prompt → 新版本", "sec sm", async () => {
          await API.post("/api/drama/tasks/revise", { task_id: t.id, instruction: insIn.value }); renderProject(view);
        }) : null,
        t.status === "generated" ? actBtn("✓ 采用", "human sm", async () => {
          await API.post("/api/drama/tasks/decide", { task_id: t.id, decision: "adopted", reason: "人工确认可用" }); renderProject(view);
        }) : null,
        t.status === "generated" ? actBtn("废弃", "bad sm", async () => {
          const reason = prompt("废弃原因（记录留痕）：") || "";
          await API.post("/api/drama/tasks/decide", { task_id: t.id, decision: "discarded", reason }); renderProject(view);
        }) : null));
  }

  /* ⑤ 导出 */
  async function tabExport() {
    const pre = h("pre", { class: "md" }, "（点击上方按钮生成——仅包含已确认镜头与已采用结果）");
    const wrap = h("div", { class: "card" },
      h("div", { class: "hd" }, h("h3", {}, "镜头交付清单（交给后期剪辑环节）"),
        actBtn("生成并下载清单", "acc sm", async () => {
          const r = await API.get("/api/drama/export/" + S.pid);
          downloadText("shots_handoff.md", r.markdown);
          pre.textContent = r.markdown;
        })),
      h("div", { class: "bd" }, pre));
    const ev = await API.get("/api/drama/events");
    return h("div", {}, wrap,
      h("div", { class: "card", style: "margin-top:16px" },
        h("div", { class: "hd" }, h("h3", {}, "操作留痕")),
        h("div", { class: "bd tight" }, tbl(["时间", "操作人", "动作", "详情"],
          ev.slice(0, 50).map(e => h("tr", {},
            h("td", { class: "mono" }, fmtTime(e.ts)), h("td", { class: "mono" }, e.user || "—"),
            h("td", {}, e.action), h("td", { class: "mono" }, e.detail.slice(0, 110))))))));
  }
})();
