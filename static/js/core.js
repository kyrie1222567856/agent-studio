/* 核心工具：DOM 构建 / API 客户端(Bearer 会话 + 统一错误提示) / Hash 路由(登录守卫) /
   共享组件（管线轨道、徽章、表格、加载态） */
"use strict";

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

function toast(msg, err) {
  const t = h("div", { class: "toast" + (err ? " err" : "") }, msg);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), err ? 8000 : 3500);
}

/* ---- 会话 ---- */
const Auth = {
  get token() { return localStorage.getItem("as_token") || ""; },
  get username() { return localStorage.getItem("as_user") || ""; },
  save(token, username) { localStorage.setItem("as_token", token); localStorage.setItem("as_user", username); },
  clear() { localStorage.removeItem("as_token"); localStorage.removeItem("as_user"); },
};

/* 全局请求指示器：任何进行中的 POST 显示顶栏进度条；超过 1.5s 显示"AI 处理中 · 已用时"悬浮徽标，
   解决 LLM 长调用（30-90s 属正常）看似"无反应"的问题 */
const Busy = {
  n: 0, t0: 0, timer: null,
  start(url) {
    this.n++; document.getElementById("netbar").classList.add("on");
    if (this.n === 1) {
      this.t0 = Date.now();
      this.timer = setTimeout(() => {
        const pill = document.getElementById("aipill");
        pill.classList.add("on");
        pill._iv = setInterval(() => {
          pill.querySelector("b").textContent = Math.round((Date.now() - this.t0) / 1000) + "s";
        }, 1000);
        pill.querySelector("span").textContent = url.includes("/api/") ? "AI / 服务处理中" : "处理中";
      }, 1500);
    }
  },
  end() {
    this.n = Math.max(0, this.n - 1);
    if (this.n === 0) {
      clearTimeout(this.timer);
      const pill = document.getElementById("aipill");
      clearInterval(pill._iv); pill.classList.remove("on"); pill.querySelector("b").textContent = "";
      document.getElementById("netbar").classList.remove("on");
    }
  },
};

const API = {
  async req(method, url, body, isForm) {
    const opt = { method, headers: {} };
    if (Auth.token) opt.headers["Authorization"] = "Bearer " + Auth.token;
    if (body) {
      if (isForm) opt.body = body;
      else { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    }
    let r;
    const track = method !== "GET";
    if (track) Busy.start(url);
    try { r = await fetch(url, opt); }
    catch (e) { toast("网络请求失败：" + e.message, true); throw e; }
    finally { if (track) Busy.end(); }
    if (r.status === 401 && !url.startsWith("/api/auth/")) {  // 会话失效 → 登录页
      Auth.clear(); Router.go();
      throw new Error("未登录");
    }
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      toast(`[${r.status}] ${detail}`, true);
      throw new Error(detail);
    }
    return r.json();
  },
  get: (u) => API.req("GET", u),
  post: (u, b) => API.req("POST", u, b),
  form: (u, fd) => API.req("POST", u, fd, true),
};

/* ---- 按钮加载态 ---- */
function busy(btn, fn) {
  return async (...a) => {
    if (btn.disabled) return;
    const old = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>' + btn.textContent;
    try { await fn(...a); } finally { btn.disabled = false; btn.innerHTML = old; }
  };
}
function actBtn(label, cls, fn) {
  const b = h("button", { class: "btn " + (cls || "") }, label);
  b.addEventListener("click", busy(b, fn));
  return b;
}

/* ---- 管线轨道（签名组件）：stages=[{key,label,state:'todo|on|done',gate,gatePassed}] ---- */
function rail(stages, onClick) {
  const el = h("div", { class: "rail" });
  stages.forEach((s, i) => {
    if (i > 0) el.append(h("span", { class: "link" }));
    if (s.gate) el.append(h("span", { class: "gate" + (s.gatePassed ? " passed" : ""), title: "人工确认节点" }));
    el.append(h("button", {
      class: "chip" + (s.state === "on" ? " on" : s.state === "done" ? " done" : ""),
      onclick: () => onClick && onClick(s.key),
    }, s.label));
  });
  return el;
}
const railLegend = () => h("div", { class: "rail-legend" },
  h("span", {}, h("span", { class: "g" }), "菱形 = 人工确认节点（AI 不可越过）"),
  h("span", {}, "绿色 = 已完成阶段"));

/* ---- 徽章 / 分数 / 表格 / 表单 ---- */
function badge(text, cls) { return h("span", { class: "badge " + cls }, text); }
function statusBadge(s) {
  const map = { draft: ["草稿", "b-draft"], structured: ["已结构化", "b-run"], candidate: ["候选", "b-draft"],
    confirmed: ["已确认 ✓", "b-ok"], rejected: ["已否决", "b-bad"], evaluated: ["已评价", "b-run"],
    pending: ["待生成", "b-draft"], submitted: ["已提交 ComfyUI", "b-run"], generated: ["已生成", "b-run"],
    failed: ["失败", "b-bad"], adopted: ["已采用 ✓", "b-ok"], discarded: ["已废弃", "b-bad"],
    locked: ["已锁定 ✓", "b-ok"], included: ["已收录 ✓", "b-ok"], excluded: ["已排除", "b-bad"],
    proposed: ["待核验", "b-human"], approved: ["核验通过 ✓", "b-ok"], active: ["进行中", "b-run"] };
  const [t, c] = map[s] || [s, "b-draft"];
  return badge(t, c);
}
function scoreEl(v, max) {
  max = max || 10;
  const cls = v >= max * 0.75 ? "s-hi" : v >= max * 0.5 ? "s-md" : "s-lo";
  return h("span", { class: "score " + cls }, v);
}
function tbl(headers, rows) {  // 语义化表格（thead/tbody）
  return h("table", { class: "tbl" },
    h("thead", {}, h("tr", {}, headers.map(x => h("th", {}, x)))),
    h("tbody", {}, rows));
}
function fmtTime(ts) {
  if (!ts) return "";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return isNaN(d) ? String(ts).slice(0, 16) : d.toLocaleString("zh-CN", { hour12: false });
}
function field(label, input) { return h("div", { class: "field" }, h("label", {}, label), input); }
function downloadText(name, text) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/markdown" })), download: name });
  a.click();
}
function emptyBox(title, sub) { return h("div", { class: "empty" }, h("b", {}, title), sub || ""); }

/* ---- Hash 路由（登录守卫） ---- */
const Router = {
  routes: {},
  on(name, fn) { this.routes[name] = fn; },
  async go() {
    const view = document.getElementById("view");
    view.innerHTML = "";
    if (!Auth.token) { this.routes.login(view); return; }   // 未登录 → 登录页
    const hash = location.hash.replace(/^#\/?/, "") || "home";
    const [name, ...args] = hash.split("/");
    document.querySelectorAll(".navlink").forEach(a =>
      a.classList.toggle("active", a.dataset.route === (name || "home")));
    const fn = this.routes[name] || this.routes.home;
    try { await fn(view, ...args); } catch (e) { view.append(emptyBox("页面加载失败", e.message)); }
    document.getElementById("sidebar").classList.remove("open");
  },
  refreshFoot() {
    const uf = document.getElementById("user-foot");
    uf.innerHTML = "";
    if (Auth.username) {
      uf.append(h("span", {}, "@" + Auth.username, " · "),
        h("a", { href: "#", onclick: async (e) => {
          e.preventDefault();
          try { await API.post("/api/auth/logout"); } catch (_) {}
          Auth.clear(); Router.go(); Router.refreshFoot();
        } }, "退出"));
    }
  },
  async start() {
    window.addEventListener("hashchange", () => this.go());
    document.getElementById("menubtn").onclick = () =>
      document.getElementById("sidebar").classList.toggle("open");
    this.refreshFoot();
    try {
      const s = await API.get("/api/health");
      document.getElementById("llm-foot").textContent =
        `LLM: ${s.llm.provider}/${s.llm.model} ${s.llm.configured ? "●已配置" : "○未配置"}`;
      if (!s.llm.configured) toast("LLM 密钥未配置：AI 环节将不可用。请编辑 .env 后重启服务。", true);
    } catch (_) {}
    this.go();
  },
};
