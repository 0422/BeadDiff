// 2026-10-10：本次修改原因：先加载原妙手后台，再加载独立的 BeadDiff 转发分支。
importScripts("background.js");
try {
  importScripts("beaddiff-protocol.js", "beaddiff-forwarder.js");
} catch (error) {
  // 分支初始化失败不撤销原后台已经注册的监听器。
  console.error("[BeadDiff] 转发分支加载失败，请查看扩展错误或重新安装分支文件。", error);
}
