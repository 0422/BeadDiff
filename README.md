<!-- 2026-10-10：本次修改原因：说明首版桌面工作台的启动方法、工作流程和已实现边界。 -->
# BeadDiff

运行在 Windows 本机的电商商品整理工作台。使用 **Python 3.12 + PySide6 + SQLite**，用于接收妙手采集插件的原始材料、解析商品、编辑 SKU、审核并导出妙手字段表格。

## 启动

当前 `learner` 环境已有 PySide6 和 openpyxl，无需重建 Conda 环境。

```bat
conda activate learner
cd /d E:\workspace\BeadDiff
python main.py
```

也可以双击项目中的 `start.bat`，直接使用已确认的解释器 `E:\pySpace\anaconda\envs\learner\python.exe`。解释器路径变动时请改启动脚本，或用上面的命令。

只有其他环境缺少依赖时，才需要执行：

```bat
python -m pip install -r requirements.txt
```

PyCharm 请将项目解释器设为 `E:\pySpace\anaconda\envs\learner\python.exe`，运行根目录的 `main.py`。

## 已实现

| 入口 | 功能 |
|---|---|
| 商品库 | 真实商品统计、搜索、来源筛选、状态筛选、勾选商品、批量审核、商品速览 |
| 商品编辑 | 基本信息、图片链接、属性、附件、规格维度、SKU 增删、统一填售价、库存/重量/尺寸编辑 |
| 采集记录 | 原始材料留档、解析状态和失败原因、查看原文、重新解析 |
| 导出记录 | 已审核商品导出、商品/SKU 数量、文件位置和导出版本追踪 |
| 连接设置 | 本机 HTTP 接收状态、地址/密钥复制、端口设置、接入协议 |

界面采用深色侧栏、浅色工作区、青绿色操作按钮和表格式商品管理。商品图片按需异步加载；采集文件处理和导出在后台执行。

## 首次使用

1. 启动软件，在“连接设置”查看本机接收服务是否运行。默认端口 `18765`；占用时可改端口并重启。接收失败仍可使用文件导入。
2. 当前妙手插件**尚未修改**，不会自动向 BeadDiff 发数据。可以先从“导入采集文件”导入包含 pfti 请求正文的 JSON、HAR 或 URL 编码表单 TXT。
3. 在商品库双击商品，核对标题、图片、币种和 SKU，并填写实际导出售价。
4. 保存会重置审核状态。完善后点击“保存并审核”，或回商品库勾选后批量审核。
5. 勾选已审核商品，点击“导出妙手表格”。到妙手核对导入结果，再在妙手编辑/发布。

程序不自动加载演示商品。`examples/demo_capture.json` 是明确标注的**虚构结构样本**，可用于体验导入和编辑；不是真实抓取结果，未提供可用图片，不应用于正式发布。

## 采集材料

已确认的实际流程是 Temu 页面材料通过 `/open/fetch/pfti` 上传到妙手相关服务。BeadDiff 接收的是同一份上传前材料，不依赖妙手返回商品 JSON。

支持的 JSON 形式：

```json
{
  "eventId": "每次采集生成 UUID，重试沿用原 UUID",
  "requestUrl": "https://kuajing-plw.happyporsche.com/open/fetch/pfti",
  "payload": {
    "source": "temu",
    "site": "US",
    "itemId": "实际商品 ID",
    "afterUrl": "https://www.temu.com/实际商品链接",
    "pageContent": "包含商品 JSON 的完整 HTML 字符串",
    "productExtInfo": "{\"sizeChatInfo\":null}"
  }
}
```

也支持直接导入 `payload` 对象及对象数组。HAR 只提取 pfti 的请求正文，不复制其中的请求头、Cookie 或响应。若浏览器省略了请求正文，请另存 Payload，或接通插件转发。

解析器静态读取页面中的 `window.rawData`、初始 JSON 和 OpenGraph 摘要；不执行网页脚本。首版映射 `store.goods` / `goodsName` / `skuList` / `specs` 等已知字段。实际页面存在版本差异；**目前没有完整真实 pfti 样本可验证全字段兼容性**。无法识别的材料仍留档，缺失项显示“待完善”，不虚构库存、规格、售价或 BOM。

插件接入详见 [docs/plugin-integration.md](docs/plugin-integration.md)。

## 导出说明

字段顺序来源于调研文件 `D:\noteSpace\Lee4More\09-Projects\BeadDiff\辅助工具\导入产品模板.xls`，共 22 列，一行一个 SKU。同一商品使用相同产品主编号，图片链接使用中文逗号 `，` 分隔。

本版通过 openpyxl 生成 `.xlsx`，表头在第 1 行，**没有复刻原 `.xls` 模板的前 8 行说明、格式和旧版二进制容器**。妙手是否接收该工作簿、是否需要表头定位和额外类目字段，必须用实际导入入口验证。若入口要求原 `.xls`，可先在 Excel 中按原模板复制数据；下一步再按验证结果实现原模板导出，不能仅更改文件后缀。

来源价格可能使用不同单位，因此只显示作参考；导出售价必须人工填写。超过两个来源规格维度时，需明确映射并确认。审核表示通过本软件的基础检查，仍需核对渠道要求及商品实际情况。

## 数据与源码

| 路径 | 用途 |
|---|---|
| main.py | 程序入口 |
| beaddiff/ui/ | 桌面界面、编辑窗口、样式和图片预览 |
| beaddiff/parsing.py | Temu 静态材料解析 |
| beaddiff/receiver.py | 带密钥的本机 HTTP 接收服务 |
| beaddiff/service.py | 文件导入、接收、去重与重新解析流程 |
| beaddiff/storage.py | SQLite 商品、采集、版本和导出记录 |
| beaddiff/exporter.py | 妙手 22 列导出 |
| data/beaddiff.sqlite3 | 首次启动后创建的数据库 |
| data/captures/ | 原始采集 JSON 文件 |
| data/settings.json | 本机接收端口与随机密钥，请勿公开 |
| data/logs/beaddiff.log | 运行异常日志 |
| tests/ | 解析、去重、编辑审核和导出的回归测试 |

源码与数据分离，`data/` 已加入 `.gitignore`。备份时请先关闭软件，再复制完整 `data/`。默认只允许一个实例使用同一数据目录。可通过 `BEADDIFF_DATA_DIR` 环境变量指定其他数据目录。

## 后续工作

优先接通插件分支并导入一个真实 Temu 商品，校准图片、SKU、币种和描述字段；然后实际验证妙手模板导入。此后再加入批量内容处理、图片生成、串珠物料/BOM 校验及渠道模板版本管理。

本次按用户要求没有启动、编译或执行测试；仅做源文件语法树和静态接口检查。用户确认运行效果后，可自行执行回归测试：

```bat
python -m pytest tests -q
```
