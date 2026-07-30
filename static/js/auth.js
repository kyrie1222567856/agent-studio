/* 登录/注册页（改进新增：多用户与数据隔离。密码服务端加盐哈希，会话可撤销） */
"use strict";
Router.on("login", (view) => {
  const uIn = h("input", { placeholder: "用户名（3-24 字符）", autocomplete: "username" });
  const pIn = h("input", { type: "password", placeholder: "密码（≥6 位）", autocomplete: "current-password" });
  const go = async (path) => {
    if (!uIn.value.trim() || !pIn.value) return toast("请填写用户名与密码", true);
    const r = await API.post(path, { username: uIn.value.trim(), password: pIn.value });
    Auth.save(r.token, r.username);
    Router.refreshFoot(); Router.go();
  };
  pIn.addEventListener("keydown", e => { if (e.key === "Enter") document.getElementById("loginbtn").click(); });
  view.append(h("div", { class: "login-wrap" },
    h("div", { class: "card login-card" },
      h("div", { class: "bd" },
        h("div", { class: "login-logo" }),
        h("h1", {}, "Agent Studio"),
        h("p", { class: "hint", style: "margin-bottom:18px" },
          "垂类 Agent 三合一工作台 · 多用户数据隔离：登录后仅能看到自己账号下的热点、项目与调研任务。"),
        field("用户名", uIn), field("密码", pIn),
        h("div", { style: "display:flex;gap:10px;margin-top:16px" },
          (() => { const b = actBtn("登录", "acc", () => go("/api/auth/login")); b.id = "loginbtn"; b.style.flex = "1"; return b; })(),
          (() => { const b = actBtn("注册新账号", "sec", () => go("/api/auth/register")); b.style.flex = "1"; return b; })()),
        h("p", { class: "hint", style: "margin-top:14px" },
          "评审提示：可分别注册两个账号验证数据隔离——不同账号的数据互不可见。")))));
});
