// 2026-10-10：本次修改原因：增加独立本机转发、IndexedDB 队列和 MV3 唤醒重试，不接管妙手响应。
(() => {
  "use strict";
  const protocol = globalThis.BeadDiffProtocol;
  const CONFIG_KEY = "beaddiff.connection.v1";
  const ALARM = "beaddiff.retry.v1";
  const MAX_JOBS = 100;
  const MAX_QUEUE_BYTES = 256 * 1024 * 1024;
  const BLOCKED_TIME = 253402300799000;
  const DEFAULT_CONFIG = { endpoint: "http://127.0.0.1:18765/api/v1/captures", token: "", enabled: false };
  let databasePromise;
  let draining = false;
  let requestAgain = false;

  function database() {
    if (!databasePromise) {
      databasePromise = new Promise((resolve, reject) => {
        const request = indexedDB.open("beaddiff-forward-queue", 1);
        request.onupgradeneeded = () => {
          const db = request.result;
          db.createObjectStore("jobs", { keyPath: "id" }).createIndex("nextAttempt", "nextAttempt");
          db.createObjectStore("meta");
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }).catch(error => { databasePromise = undefined; throw error; });
    }
    return databasePromise;
  }

  function done(transaction) {
    return new Promise((resolve, reject) => {
      transaction.oncomplete = () => resolve();
      transaction.onabort = () => reject(transaction.error || new Error("本地队列事务已中止。"));
      transaction.onerror = () => {};
    });
  }

  function result(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function emptyStats() {
    return { pending: 0, bytes: 0, delivered: 0, missed: 0, lastError: "", lastQueued: "", lastDelivered: "", lastState: "" };
  }

  async function readConfig() {
    const stored = await chrome.storage.local.get(CONFIG_KEY);
    return { ...DEFAULT_CONFIG, ...stored[CONFIG_KEY] };
  }

  async function reportError(message, missed = false) {
    console.warn("[BeadDiff]", message);
    try {
      const db = await database();
      const tx = db.transaction("meta", "readwrite");
      const completed = done(tx);
      const store = tx.objectStore("meta");
      const stats = await result(store.get("stats")) || emptyStats();
      stats.lastError = String(message).slice(0, 500);
      if (missed) stats.missed += 1;
      store.put(stats, "stats");
      await completed;
    } catch {
      // 队列本身不可写时仍在后台 Console 明示错误，不打印商品正文或密钥。
    }
  }

  async function enqueue(material) {
    const db = await database();
    const tx = db.transaction(["jobs", "meta"], "readwrite");
    const completed = done(tx);
    const jobs = tx.objectStore("jobs"), meta = tx.objectStore("meta");
    const stats = await result(meta.get("stats")) || emptyStats();
    const existing = await result(jobs.get(material.envelope.eventId));
    if (!existing) {
      if (stats.pending >= MAX_JOBS || stats.bytes + material.size > MAX_QUEUE_BYTES) {
        stats.missed += 1;
        stats.lastError = "待同步队列已满，本次材料未暂存。请先启动 BeadDiff 清空积压，再重新采集该商品。";
        console.warn("[BeadDiff]", stats.lastError);
      } else {
        jobs.put({ id: material.envelope.eventId, envelope: material.envelope, size: material.size,
                   attempts: 0, nextAttempt: Date.now(), lastError: "", createdAt: new Date().toISOString() });
        stats.pending += 1;
        stats.bytes += material.size;
        stats.lastQueued = new Date().toISOString();
      }
      meta.put(stats, "stats");
    }
    await completed;
  }

  async function nextJob() {
    const db = await database();
    const tx = db.transaction("jobs", "readonly");
    const completed = done(tx);
    const cursor = await result(tx.objectStore("jobs").index("nextAttempt").openCursor(IDBKeyRange.upperBound(Date.now())));
    const job = cursor ? cursor.value : null;
    await completed;
    return job;
  }

  async function finishJob(job, response) {
    const db = await database();
    const tx = db.transaction(["jobs", "meta"], "readwrite");
    const completed = done(tx);
    const jobs = tx.objectStore("jobs"), meta = tx.objectStore("meta");
    const stats = await result(meta.get("stats")) || emptyStats();
    const existing = await result(jobs.get(job.id));
    if (existing) {
      jobs.delete(job.id);
      stats.pending = Math.max(0, stats.pending - 1);
      stats.bytes = Math.max(0, stats.bytes - existing.size);
      stats.delivered += 1;
      stats.lastDelivered = new Date().toISOString();
      stats.lastState = String(response.state || "已接收");
      stats.lastError = "";
      meta.put(stats, "stats");
    }
    await completed;
  }

  async function failJob(job, message, permanent) {
    const db = await database();
    const tx = db.transaction(["jobs", "meta"], "readwrite");
    const completed = done(tx);
    const jobs = tx.objectStore("jobs"), meta = tx.objectStore("meta");
    const stats = await result(meta.get("stats")) || emptyStats();
    const current = await result(jobs.get(job.id));
    if (current) {
      current.attempts += 1;
      current.lastError = String(message).slice(0, 500);
      current.nextAttempt = permanent ? BLOCKED_TIME : Date.now() + Math.min(60000 * (2 ** Math.min(current.attempts - 1, 4)), 300000);
      jobs.put(current);
      stats.lastError = current.lastError;
      meta.put(stats, "stats");
    }
    await completed;
  }

  async function retryAll() {
    const db = await database();
    const tx = db.transaction("jobs", "readwrite");
    const completed = done(tx);
    const cursorRequest = tx.objectStore("jobs").openCursor();
    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result;
      if (!cursor) return;
      const job = cursor.value;
      job.nextAttempt = Date.now();
      cursor.update(job);
      cursor.continue();
    };
    await completed;
  }

  async function fetchWithTimeout(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      // 重定向被拒绝，避免把接入密钥发到其他地址。
      return await fetch(url, { ...options, signal: controller.signal, redirect: "error", cache: "no-store", credentials: "omit" });
    } finally {
      clearTimeout(timer);
    }
  }

  async function drain() {
    if (draining) { requestAgain = true; return; }
    draining = true;
    try {
      let count = 0;
      do {
        requestAgain = false;
        let connection = await readConfig();
        if (!connection.enabled || !connection.token) return;
        connection = protocol.config(connection);
        while (count < 20) {
          const job = await nextJob();
          if (!job) break;
          count += 1;
          try {
            const response = await fetchWithTimeout(connection.endpoint, {
              method: "POST", headers: { "Content-Type": "application/json", "Authorization": "Bearer " + connection.token },
              body: JSON.stringify(job.envelope),
            });
            const body = await response.json().catch(() => ({}));
            if (!response.ok || body.accepted !== true || typeof body.captureId !== "string") {
              const error = new Error("HTTP " + response.status + "：" + String(body.error || "接收端未确认保存"));
              error.permanent = [400, 401, 403, 413, 415].includes(response.status);
              throw error;
            }
            await finishJob(job, body);
          } catch (error) {
            await failJob(job, error.name === "AbortError" ? "连接超时，材料已保留；请检查 BeadDiff 是否运行。" : String(error.message), Boolean(error.permanent));
            // 当前连接失败时停止整批，避免对同一不可用服务连续投递所有材料。
            break;
          }
          connection = await readConfig();
          if (!connection.enabled || !connection.token) break;
          connection = protocol.config(connection);
        }
      } while (requestAgain && count < 20);
    } catch (error) {
      await reportError(error.message || String(error));
    } finally {
      draining = false;
    }
  }

  async function status() {
    const connection = await readConfig();
    const db = await database();
    const tx = db.transaction(["meta", "jobs"], "readonly");
    const completed = done(tx);
    const statsRequest = tx.objectStore("meta").get("stats");
    const entries = [];
    const cursorRequest = tx.objectStore("jobs").openCursor();
    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result;
      if (!cursor || entries.length >= 20) return;
      const job = cursor.value;
      entries.push({ itemId: String(job.envelope.payload.itemId || ""), source: String(job.envelope.payload.source || ""),
                     createdAt: job.createdAt, attempts: job.attempts, blocked: job.nextAttempt === BLOCKED_TIME, lastError: job.lastError });
      cursor.continue();
    };
    const stats = await result(statsRequest) || emptyStats();
    await completed;
    return { connection, stats, entries, limits: { count: MAX_JOBS, bytes: MAX_QUEUE_BYTES } };
  }

  async function testConnection(value) {
    const connection = protocol.config(value);
    const response = await fetchWithTimeout(new URL("/api/v1/status", connection.endpoint).href, {
      headers: { "Authorization": "Bearer " + connection.token },
    });
    const body = await response.json();
    if (!response.ok || body.service !== "BeadDiff" || !body.ready) {
      throw new Error(body.error || "接收地址未返回 BeadDiff 身份，请确认桌面端已更新并启动。");
    }
    return { version: body.version, message: "连接成功，接入密钥已验证。" };
  }

  async function control(message) {
    switch (message.command) {
      case "status": return status();
      case "save": {
        const connection = protocol.config(message.connection || {});
        await chrome.storage.local.set({ [CONFIG_KEY]: connection });
        await retryAll();
        void drain();
        return { message: "设置已保存。" };
      }
      case "test": return testConnection(message.connection || {});
      case "retry": await retryAll(); void drain(); return { message: "已安排立即重试，请稍后刷新同步状态。" };
      default: throw new Error("未知 BeadDiff 操作。");
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message && message.type === protocol.CONTROL_TYPE) {
      // 控制消息只接受本扩展自己的设置页；商品页不能读取接入密钥。
      if (sender.id !== chrome.runtime.id || String(sender.url || "").split(/[?#]/)[0] !== chrome.runtime.getURL("beaddiff-options.html")) return false;
      void control(message).then(value => sendResponse({ ok: true, value }), error => sendResponse({ ok: false, error: error.message || String(error) }));
      return true;
    }
    const selected = protocol.candidate(message);
    if (selected) {
      void (async () => {
        const connection = await readConfig();
        if (!connection.enabled) return;
        const material = await protocol.envelope(selected);
        await enqueue(material);
        void drain();
      })().catch(error => { void reportError("商品转发准备失败：" + (error.message || String(error)), true); });
    }
    // 对妙手消息不调用 sendResponse，不返回 Promise，也不声明本分支需要响应通道。
    return false;
  });

  chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void drain(); });
  chrome.runtime.onStartup.addListener(() => { void drain(); });
  chrome.runtime.onInstalled.addListener(() => { void drain(); });
  // 2026-10-11：本次修改原因：兼容 Chrome 旧版 alarms.create 的 void 返回值，避免后台启动时报错。
  try {
    const alarmResult = chrome.alarms.create(ALARM, { periodInMinutes: 1 });
    if (alarmResult && typeof alarmResult.catch === "function") alarmResult.catch(error => { void reportError("重试调度失败：" + error.message); });
  } catch (error) {
    void reportError("重试调度失败：" + error.message);
  }
  void drain();
})();
