# Gemini 图文翻译中台

一个可用于商务演示与合作洽谈的高级图文翻译工作台，基于 Google Gemini 2.5 Flash Image Preview API。新界面采用 [NiceGUI](https://nicegui.io/) 构建，提供现代化的交互、会话追踪与履历导出能力。

## 亮点功能
- 🎯 **一键批处理**：多图批量上传、自动进度跟踪、成功/异常统计。
- 🧠 **智能提示词**：内置商用翻译提示词模版，可按目标语言自动适配。
- 🗂️ **全链路留痕**：SQLite 记录每次会话，可导出 CSV 供运营复盘。
- 📦 **交付视图**：原图与译稿并排预览，支持单张/整体 ZIP 下载。
- 🧱 **模块化架构**：Gemini 客户端、持久化、业务编排按职能拆分，便于扩展。

## 快速开始
1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 配置密钥：
   ```bash
   set GEMINI_API_KEY=sk-...
   ```
   或者在界面内填写，界面输入会优先生效。
3. 启动体验：
   ```bash
   python app.py
   ```
   默认在 `http://127.0.0.1:8080` 运行。

> **提示**：如果希望继续使用原始的 Gradio Demo，可执行 `python legacy_gradio_app.py`。

## 目录结构
- `app.py`：全新的 NiceGUI 主入口，提供商务级 UI 体验。
- `legacy_gradio_app.py`：保留的旧版 Gradio 脚本。
- `image_translate/`
  - `config.py`：路径、语言列表与提示词。
  - `gemini_client.py`：与 Gemini API 通讯的轻量客户端。
  - `persistence.py`：会话与文件级日志的 SQLite 封装。
  - `translation.py`：批处理编排与压缩打包服务。
- `data/`：SQLite 数据库与上传缓存。
- `outputs/`：每批次的生成产物与 ZIP。
- `exports/`：导出的 CSV 与对外分享材料。

## 开发小贴士
- 建议创建虚拟环境隔离依赖。
- 如果需要自定义提示词，可修改 `image_translate/config.py` 中的 `PROMPT_TEMPLATE`。
- NiceGUI 支持热重载，开发阶段可以加 `ui.run(reload=True)` 加速调试。
- 若运行在服务器，可将 `ui.run(host="0.0.0.0", port=8080)` 暴露给局域网或公网来演示。

祝展示顺利！
