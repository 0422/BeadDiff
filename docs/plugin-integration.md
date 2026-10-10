<!-- 2026-10-10：本次修改原因：明确插件到桌面端的可审阅接入契约，保留妙手原有上传链路。 -->
# 妙手插件接入 BeadDiff

<!-- 早期记录：本轮只创建 BeadDiff 项目文件，没有改动 D:\tradeSoftwares\kuajing-erp-plugin-v3-5x (2) 中的安装文件。 -->
<!-- 2026-10-11：本次修改原因：新增真实消息转发分支、可加载插件副本与首轮联调步骤。 -->
现已生成带 BeadDiff 转发分支的开发版插件：`E:\workspace\BeadDiff\browser_extension\unpacked`。源插件目录 `D:\tradeSoftwares\kuajing-erp-plugin-v3-5x (2)` 的文件没有改动。
2026-10-11 已增加兼容性的 `options_page` 声明；若此前已加载过副本，请在扩展管理页点击“重新加载”，再打开“详情”。

## 现在如何启用

1. 关闭并重新启动 BeadDiff，让新增的连接测试接口生效：`conda activate learner`，在项目目录执行 `python main.py`。
2. 打开 Chrome 的 `chrome://extensions/`（Edge 使用 `edge://extensions/`），开启“开发者模式”。先关闭当前妙手插件的开关，避免同一页面运行两套采集插件。不要卸载原插件。
3. 点击“加载已解压的扩展程序”，选择 **`E:\workspace\BeadDiff\browser_extension\unpacked`**。原 manifest 的 key 已保留，开发版可能与旧版产生同一扩展 ID；以浏览器实际显示的安装来源为准。如果出现 ID 冲突且不能加载，先停止在此步，并记录浏览器提示，不要删除原插件数据。
4. 在开发版插件的“详情”中打开“扩展选项”（或右键插件图标 → 选项）。这会打开“采集同步到 BeadDiff”页面。工具栏点击行为仍保留妙手的原弹窗。
5. 在 BeadDiff“连接设置”复制接收地址和密钥，粘贴到扩展选项，勾选“启用采集同步”并点击“保存设置”。再点击“测试连接”，应显示“连接成功，接入密钥已验证”。
6. 刷新 Temu 商品详情页，点击原插件的“采集此商品”。扩展选项显示接收确认；BeadDiff“采集记录”出现同一商品 ID。商品页面必须刷新，旧页面仍可能绑定已停用的扩展上下文。
7. 检查妙手采集箱仍出现该商品，并在 BeadDiff 核对标题、实际 SKU 和图片。若是“待补充”或“解析失败”，先检查该条原始材料，不代表本机转发失败。

不要把 `browser_extension` 上层目录直接当成可加载插件目录。可加载目录是其下的 **`unpacked`**，包含实际的 `manifest.json` 与完整第三方运行文件。

## 此次实现

| 项目 | 行为 |
|---|---|
| 后台入口 | `beaddiff-worker.js` 先加载原 `background.js`，再加载独立转发脚本；分支加载失败保留原监听器 |
| 消息筛选 | 匹配 `__$$earth_browser_extension$$__service_request_key__`，取 `message.key` 及 `message.data[0]` |
| 采集条件 | 仅处理 `plwFetch/javaPlwFetch/commonFetch/commonXhr` 中的 POST `/open/fetch/pfti` |
| 压缩材料 | 按原 `Sp()` 逻辑独立解码 gzip、URL 编码和 JSON，不改原消息对象 |
| 原上传链路 | 不修改原 `background.js`，不调用妙手请求的 sendResponse，不等待本机转发结果 |
| 重试去重 | 采用原消息 UUID 生成 eventId；同一任务重试保持原 ID |
| 持久化 | 在扩展独立的 IndexedDB 中暂存，只有收到 accepted:true 与 captureId 才移除任务 |
| 重试调度 | 使用 MV3 alarms 定时唤醒，网络失败保留任务并退避重试；保存设置/立即重试可重新激活失败任务 |
| 错误处理 | 参数、密钥及协议错误暂停该任务，设置页显示原因；超限材料不暂存并记录失败计数，须重新采集 |
| 连接设置 | 独立扩展选项页，地址只允许本机 127.0.0.1；密钥不写入源码，不复制账号登录请求 |

队列限制为 100 条或 256 MB，总接口请求体上限为 32 MB。停用同步会暂停新增材料和发送，但保留已有队列。打开浏览器、启动 BeadDiff 并保持同步启用后，可点击“立即重试”。本版没有自动补采历史商品：需要刷新页面后重新触发采集。

`manifest.original.json` 保存调研时的原配置；JSON 不支持注释，修改原因记录在本页及新增脚本的日期注释中。开发版新增 `alarms` 权限、独立 `options_ui`，后台入口改为包装 worker。原 `<all_urls>` 权限已包含本机地址，未增加网页登录范围。开发版要求 Chrome/Chromium 120 及以上。

生成时跳过原目录中的 `_metadata` 商店签名校验文件，它不适用于开发版；原目录中的 `_metadata` 保留。已核对副本的 `background.js` SHA256 与源文件一致。

## 维护与回退

源码在 `browser_extension`，可加载副本在 `browser_extension/unpacked`。修改分支后需同步文件到副本，并在扩展管理页“重新加载”，刷新商品页面。不要手工修改原压缩后台来混入分支。

如需重新准备一个新的开发版副本，可在项目目录运行以下命令。脚本不会覆盖已经存在的输出目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare_plugin.ps1 -OutputName unpacked_v2
```

脚本默认从用户提供的原插件目录复制。若原插件更新了版本或 key，先重新检查源码并更新准备好的 manifest，再生成副本。

回退时先让待同步队列完成，停用开发版并重新启用原插件，刷新商品页。不要在还有待同步材料时清除或卸载开发版扩展，否则浏览器中的暂存数据可能丢失。

本次只执行文件准备及静态语法/配置检查，未启动软件、浏览器或实际采集，也未执行回归测试。用户可以自行运行：

```bat
python -m pytest tests -q
node --test browser_extension\test_protocol.cjs
```

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

<!-- 2026-10-11：本次修改原因：增加无副作用的密钥验证接口说明。 -->
扩展选项中的“测试连接”调用 `GET /api/v1/status`，携带相同 Bearer 密钥，验证地址和密钥而不创建采集记录。更新了桌面端代码后需要重启软件，此接口才会生效。

## 早期插件改动方案记录

<!-- 原方案：待用户确认插件修改后，先备份/复制一份插件目录，再实施以下具体改动。 -->
以下为早期设计；上面的“此次实现”描述已完成的实际文件与行为。

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
