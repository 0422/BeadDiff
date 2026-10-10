// 2026-10-11：本次修改原因：为真实消息格式、独立解压及请求筛选提供用户可运行的回归检查。
const test = require("node:test");
const assert = require("node:assert/strict");
const zlib = require("node:zlib");
const protocol = require("./beaddiff-protocol.js");

function message(request, key = "plwFetch") {
  return { type: protocol.SERVICE_TYPE, message: { uuid: "test-uuid", key, data: [request], "__$$__MESSAGE__$$__": true } };
}

const payload = { pageContent: '<script>window.rawData={"title":"中文 & + %"}</script>', itemId: "TEST-001", source: "temu", site: "US" };

test("识别 pfti 并保留原消息及实际 UUID", async () => {
  const source = message({ url: "/open/fetch/pfti", method: "POST", data: payload });
  const before = JSON.stringify(source);
  const material = await protocol.envelope(protocol.candidate(source));
  assert.deepEqual(material.envelope.payload, payload);
  assert.equal(material.envelope.eventId, "earth:test-uuid");
  material.envelope.payload.pageContent = "changed";
  assert.equal(JSON.stringify(source), before);
});

test("配置、登录和采集箱请求不会混入商品分支", () => {
  for (const path of ["/open/v3/getTs", "/api/open/niu/check_login", "/api/open/niu/push_collect_box"]) {
    assert.equal(protocol.candidate(message({ url: path, method: "POST", data: payload })), null);
  }
  assert.equal(protocol.candidate(message({ url: "/open/fetch/pfti", method: "GET", data: payload })), null);
  assert.equal(protocol.candidate(message({ url: "/open/fetch/pfti", method: "POST", data: payload }, "browser.storage.local.set")), null);
});

test("按原 Sp 的编码顺序独立解压中文材料", async () => {
  const compressed = zlib.gzipSync(Buffer.from(encodeURIComponent(JSON.stringify(payload)))).toString("base64");
  const source = message({ url: "/open/fetch/pfti", method: "POST", data: encodeURIComponent(compressed), isZip: true });
  const material = await protocol.envelope(protocol.candidate(source));
  assert.deepEqual(material.envelope.payload, payload);
});

test("commonFetch 的表单正文可静态解码", async () => {
  const source = message({ url: "https://kuajing-plw.happyporsche.com/open/fetch/pfti", method: "POST", body: new URLSearchParams(payload).toString() }, "commonFetch");
  const material = await protocol.envelope(protocol.candidate(source));
  assert.deepEqual(material.envelope.payload, payload);
});

test("接入配置仅允许本机明确路径", () => {
  assert.equal(protocol.endpoint("http://127.0.0.1:18765/api/v1/captures"), "http://127.0.0.1:18765/api/v1/captures");
  for (const url of ["https://example.com/api/v1/captures", "http://localhost:18765/api/v1/captures", "http://127.0.0.1:18765/other"]) {
    assert.throws(() => protocol.endpoint(url));
  }
  assert.throws(() => protocol.config({ endpoint: "http://127.0.0.1:18765/api/v1/captures", token: "short" }));
});
