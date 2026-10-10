<!-- 2026-10-11：本次修改原因：区分自写分支源码与可加载插件副本，避免加载错目录。 -->
# BeadDiff 插件转发分支

**浏览器加载目录：`E:\workspace\BeadDiff\browser_extension\unpacked`**。

本目录上层文件是自写分支源码及准备好的配置；`unpacked` 中包含完整的原妙手运行程序和转发分支，可在扩展管理页加载。

| 文件 | 作用 |
|---|---|
| beaddiff-worker.js | 包装后台入口，先加载原后台 |
| beaddiff-protocol.js | 已核实的 pfti 消息识别、独立解压与封装 |
| beaddiff-forwarder.js | 独立转发、暂存队列、重试与设置消息 |
| beaddiff-options.html / .css / .js | 本机连接设置和同步结果；manifest 同时声明 `options_ui` 与兼容性的 `options_page` |
| manifest.original.json | 原 manifest 配置留档 |
| manifest.beaddiff.json | 开发版配置，准备副本时复制为 manifest.json |
| test_protocol.cjs | 用户自行执行的消息封装回归检查 |
| unpacked/ | 已生成的可加载插件副本，不纳入源码版本管理 |

加载步骤、连接配置、重试限制和回退说明见 [插件接入文档](../docs/plugin-integration.md)。原插件目录的文件未改动，开发版的原 `background.js` 内容与源文件 SHA256 一致。

暂存数据在浏览器扩展的 IndexedDB 中，接收密钥在扩展本地存储中；这两项都不在本项目源码里。队列未完成时，请保留扩展数据。
