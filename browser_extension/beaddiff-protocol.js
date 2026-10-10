// 2026-10-10：本次修改原因：根据妙手 5.0.9 消息结构独立识别并解包 pfti 商品材料。
(() => {
  "use strict";
  const SERVICE_TYPE = "__$$earth_browser_extension$$__service_request_key__";
  const MESSAGE_MARKER = "__$$__MESSAGE__$$__";
  const CONTROL_TYPE = "beaddiff:control:v1";
  const MAX_BYTES = 32 * 1024 * 1024;
  const KEYS = new Set(["plwFetch", "javaPlwFetch", "commonFetch", "commonXhr"]);

  function candidate(message) {
    if (!message || message.type !== SERVICE_TYPE) return null;
    const service = message.message;
    if (!service || !service[MESSAGE_MARKER] || !KEYS.has(service.key)) return null;
    if (!Array.isArray(service.data) || !service.data[0]) return null;
    const request = service.data[0];
    if (typeof request.url !== "string") return null;
    let url;
    try {
      url = new URL(request.url, request.baseUrl || "https://kuajing-plw.happyporsche.com");
    } catch {
      return null;
    }
    if (url.pathname !== "/open/fetch/pfti" || !["http:", "https:"].includes(url.protocol)) return null;
    if (String(request.method || "GET").toUpperCase() !== "POST") return null;
    return { request, key: service.key, uuid: String(service.uuid || ""), requestUrl: url.href };
  }

  function endpoint(value) {
    const url = new URL(String(value).trim());
    if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.username || url.password || url.search || url.hash) {
      throw new Error("接收地址必须是 http://127.0.0.1:端口/api/v1/captures。");
    }
    if (url.pathname !== "/api/v1/captures" || Number(url.port || 80) < 1024) {
      throw new Error("请复制 BeadDiff 连接设置中的完整接收地址（端口至少 1024）。");
    }
    return url.href;
  }

  function config(value) {
    const token = String(value.token || "").trim();
    if (token.length < 24 || token.length > 256 || !/^[A-Za-z0-9_-]+$/.test(token)) {
      throw new Error("请从 BeadDiff 复制完整接入密钥，不要填写妙手账号或密码。");
    }
    return { endpoint: endpoint(value.endpoint), token, enabled: Boolean(value.enabled) };
  }

  async function decompress(data) {
    if (typeof data !== "string") throw new Error("isZip 请求的 data 应为压缩字符串。");
    if (data.length > MAX_BYTES) throw new Error("压缩采集材料超过 32 MB。");
    const binary = atob(decodeURIComponent(data));
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")).getReader();
    const decoder = new TextDecoder();
    let total = 0, text = "";
    try {
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        total += part.value.byteLength;
        if (total > MAX_BYTES) throw new Error("解压后的商品材料超过 32 MB。");
        text += decoder.decode(part.value, { stream: true });
      }
      text += decoder.decode();
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
    // 原后台 Sp()：gzip -> 字符串 -> decodeURIComponent -> JSON.parse。
    return JSON.parse(decodeURIComponent(text));
  }

  function bodyObject(data) {
    if (typeof data === "string") {
      try { data = JSON.parse(data); }
      catch { data = Object.fromEntries(new URLSearchParams(data)); }
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error("pfti 正文不是可识别的商品对象。");
    }
    if (!("pageContent" in data) && !("itemId" in data) && !("rawData" in data)) {
      throw new Error("pfti 正文中未发现 pageContent、itemId 或 rawData。");
    }
    return data;
  }

  async function envelope(selected) {
    let body = selected.key === "commonFetch" ? selected.request.body : selected.request.data;
    if (["plwFetch", "javaPlwFetch"].includes(selected.key) && selected.request.isZip) {
      body = await decompress(body);
    }
    const result = {
      eventId: "earth:" + (selected.uuid || crypto.randomUUID()),
      requestUrl: selected.requestUrl,
      payload: bodyObject(body),
    };
    // JSON 克隆保证新增分支不修改原监听器仍在处理的消息对象。
    const serialized = JSON.stringify(result);
    const size = new TextEncoder().encode(serialized).byteLength;
    if (size > MAX_BYTES) throw new Error("商品材料超过 BeadDiff 接收接口的 32 MB 限制。");
    return { envelope: JSON.parse(serialized), size };
  }

  const api = Object.freeze({ SERVICE_TYPE, CONTROL_TYPE, MAX_BYTES, candidate, endpoint, config, envelope });
  globalThis.BeadDiffProtocol = api;
  // 供用户自行运行的 node:test 回归文件读取；浏览器内没有 module 对象。
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
