// 2026-10-11：本次修改原因：让用户配置本机同步，验证密钥并查看真实队列结果。
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  let loaded = false;
  let refreshing = false;

  async function call(command, extra = {}) {
    const reply = await chrome.runtime.sendMessage({ type: "beaddiff:control:v1", command, ...extra });
    if (!reply || !reply.ok) throw new Error(reply && reply.error || "后台未响应，请检查扩展已重新加载且使用 beaddiff-worker.js。");
    return reply.value;
  }

  function showMessage(text, error = false) {
    const message = byId("message");
    message.textContent = text;
    message.className = error ? "error" : "";
    message.hidden = false;
  }

  function connection() {
    return { endpoint: byId("endpoint").value.trim(), token: byId("token").value.trim(), enabled: byId("enabled").checked };
  }

  function time(value) {
    return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "尚无";
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const state = await call("status");
      if (!loaded) {
        byId("endpoint").value = state.connection.endpoint;
        byId("token").value = state.connection.token;
        byId("enabled").checked = state.connection.enabled;
        loaded = true;
      }
      byId("connection-state").textContent = state.connection.enabled ? "同步已启用" : "同步未启用";
      byId("pending").textContent = state.stats.pending;
      byId("delivered").textContent = state.stats.delivered;
      byId("bytes").textContent = (state.stats.bytes / 1024 / 1024).toFixed(1) + " MB";
      byId("last-state").textContent = "最近接收确认：" + time(state.stats.lastDelivered) + (state.stats.lastState ? " · " + state.stats.lastState : "");
      byId("last-error").hidden = !state.stats.lastError;
      byId("last-error").textContent = "最近失败：" + state.stats.lastError;
      byId("missed").hidden = !state.stats.missed;
      byId("missed").textContent = "累计 " + state.stats.missed + " 次材料准备或暂存失败，未自动补回。请排除问题后重新采集对应商品。";
      const jobs = byId("jobs");
      jobs.replaceChildren();
      for (const entry of state.entries) {
        const row = document.createElement("tr");
        for (const value of [entry.itemId || "未提供", entry.source || "—", time(entry.createdAt), String(entry.attempts),
                             entry.blocked ? "需修正设置后重试 · " + entry.lastError : entry.lastError || "等待发送"]) {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.appendChild(cell);
        }
        jobs.appendChild(row);
      }
      byId("empty").hidden = state.stats.pending > 0;
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      refreshing = false;
    }
  }

  async function action(id, work) {
    const control = byId(id);
    control.disabled = true;
    try {
      const response = await work();
      showMessage(response.message || "操作完成。");
      await refresh();
    } catch (error) {
      showMessage(error.name === "AbortError" ? "连接超时，请先启动 BeadDiff 并确认地址。" : error.message, true);
    } finally {
      control.disabled = false;
    }
  }

  byId("settings-form").addEventListener("submit", event => {
    event.preventDefault();
    void action("save", () => call("save", { connection: connection() }));
  });
  byId("test").addEventListener("click", () => { void action("test", () => call("test", { connection: connection() })); });
  byId("retry").addEventListener("click", () => { void action("retry", () => call("retry")); });
  byId("refresh").addEventListener("click", () => { void refresh(); });
  byId("show-token").addEventListener("click", () => {
    const visible = byId("token").type === "password";
    byId("token").type = visible ? "text" : "password";
    byId("show-token").textContent = visible ? "隐藏" : "显示";
  });
  void refresh();
  setInterval(() => { void refresh(); }, 3000);
})();
