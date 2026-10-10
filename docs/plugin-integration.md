<!-- 2026-10-10：本次修改原因：明确插件到桌面端的可审阅接入契约，保留妙手原有上传链路。 -->
# 妙手插件接入 BeadDiff

本轮只创建 BeadDiff 项目文件，没有改动 `D:\tradeSoftwares\kuajing-erp-plugin-v3-5x (2)` 中的安装文件。

## 接入位置

前期定位已确认插件向 `/open/fetch/pfti` 提交 `pageContent`、`itemId`、`source`、`site`、`afterUrl` 和 `productExtInfo`。该请求通常只返回 `result: success`，因此应转发**请求材料**。

建议在扩展后台收到对应上传消息、尚未压缩或转换 `pageContent` 时复制业务字段，创建独立转发任务。不要在商品网页直接访问本机端口。页面脚本、content script 和 extension service worker 是不同执行环境，监听位置必须根据实际 `chrome.runtime` 消息格式确认。

## 本机接口

```text
POST http://127.0.0.1:18765/api/v1/captures
Content-Type: application/json
Authorization: Bearer <从连接设置复制的随机密钥>
```

正文采用 README 中的 `eventId + requestUrl + payload` 对象。限制 32 MB；必须带 `Content-Length`（fetch 会自动处理）。监听地址和端口以软件界面显示为准。

```json
{
  "accepted": true,
  "captureId": "原始记录 ID",
  "state": "已解析",
  "productId": "商品 ID",
  "duplicate": false
}
```

`accepted:true` 表示材料已保存。`state` 可为“已解析”“待补充”“重复商品”“解析失败”。解析失败已留档，应查看原因，不应因为业务解析失败无限重发。

| HTTP 状态 | 含义及处理 |
|---|---|
| 200 | 已持久化；根据 state 检查解析结果 |
| 400 | JSON 或业务封装错误；修正格式 |
| 401 | 密钥无效；重新配置 |
| 403 | 请求来源不是扩展后台；调整发送位置 |
| 413 | 请求过大或长度无效 |
| 415 | Content-Type 错误 |
| 500 / 网络失败 | 本机未成功确认持久化；保留队列，使用相同 eventId 重试 |

健康检查：`GET http://127.0.0.1:18765/health`，无需密钥，仅返回软件标识和就绪状态。

## 后续插件改动方案

待用户确认插件修改后，先备份/复制一份插件目录，再实施以下具体改动：

| 文件 | 改动 |
|---|---|
| beaddiff-worker.js（新增） | 作为后台入口，加载原 background.js 与独立转发模块 |
| beaddiff-forwarder.js（新增） | 监听已核实的 pfti 消息结构，提取上传前材料并异步投递 |
| manifest.json | 将 service_worker 指向新入口；检查回环地址权限 |
| 接入配置页面（新增） | 输入并保存本机地址/密钥，提供状态与重试入口 |

当前为 MV3、经典 worker，后续需要按实际脚本执行环境选择 `importScripts` 包装。先验证消息是如何封装 URL 和 FormData 的，不能仅根据 background.js 的文件名猜测。

转发分支必须满足：

1. 不修改原 pfti / check_login / push_collect_box 请求参数，不接管原 sendResponse。
2. 不等待 BeadDiff 返回才允许妙手继续；本机软件关闭时原上传仍可成功。
3. 失败重试复用 eventId；已存在商品保留人工编辑，新的原始材料另行留档。
4. 本地队列需限制大小，并明确显示待同步数量和失败原因，避免静默丢失材料。
5. 启动后验证扩展 worker 正常、妙手仍能采集、BeadDiff 能收到相同 itemId 的材料。

## 首轮验收顺序

先用一个真实 Temu 商品验证标题、主图、规格图片、规格组合、币种和来源价格。来源价格不自动用于售价，库存、重量和尺寸不猜填。

再验证同一 eventId 重试只产生一条接收记录、重新采集同一商品不覆盖人工修改、软件关闭时插件原上传仍正常。最后用一件已审核商品导出，到实际妙手入口检查文件格式与映射。之前定位的是“Temu 全托管采集箱”，不要预先假设所有渠道都使用“公共采集箱”的同一导入入口。
