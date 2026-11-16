# Research Workbench · 科研工作台

Windows x64 预览版提供一键安装器及核心、可选环境组件；下载入口见 [Releases](https://github.com/588ttggx/research-workbench/releases)。

在本机管理科研项目、知识笔记和文献，并按需连接 DeepSeek、Zotero 与本地检索。

## 安装

首发为 Windows x64 预览版。前往 [Releases](https://github.com/588ttggx/research-workbench/releases)，下载 `ResearchWorkbench-Setup-0.1.0-preview.1.exe`，双击后选择一个空目录。安装器自动准备随版本提供的 Python 3.13 / 3.12、现有依赖、Node.js、SurrealDB 和 Open Notebook，无需提前安装 Git、Python、Node 或 Docker。

在线安装时从同一 Release 下载经过 SHA-256 校验的组件。只需基本工作台时保持默认选择；需要本地检索时勾选 Qwen3 Embedding 4B，安装器会同时准备 Ollama 与模型。这个模型负责检索嵌入，聊天仍使用你配置的外部模型服务。

离线使用时，把安装 EXE 与所选组件的 ZIP 放在同一目录后双击 EXE；也可将 `Install.cmd`、`Install.ps1`、`manifest.json` 和全部必需 ZIP 放在同一目录，双击 `Install.cmd`。核心组件是 `core.zip`、`runtime-python313.zip`、`runtime-python312.zip`、`runtime-open-notebook.zip`、`runtime-node.zip`、`runtime-surreal.zip`。离线检索还需 `runtime-ollama.zip`、`runtime-qwen4b.zip` 和全部 `runtime-qwen4b-part*.zip`。

安装后通过桌面 **Research Workbench** 打开工作台，入口为 `http://127.0.0.1:8503`。默认关闭后台自动任务；在“连接与设置”中配置自己的 AI 凭据，再启用需要的功能。API 调用费用由使用者自己的账户承担。

这是空白工作区：不包含作者的论文、科研记录、账户、API 密钥或数据库。PDF 文件和识别功能按已有工作台设计处理；发布不替换 PDF 组件。

## 环境与组件

核心运行环境已按发行版本打包，安装时重建与目标路径绑定的 Python 入口。后端和 Open Notebook 使用各自的隔离环境，程序只监听本机地址。

安装器可选附带现有 Qwen3 Embedding 4B / Ollama、R 及扩展包、Graphviz、PowerShell 7；版本与大小见 `manifest.json`。大模型被分成多个附件，安装器会校验并自动还原，无需手工拼接。

Zotero、OCR 所需 WSL / GPU 驱动、n8n 和专有科学软件仍按原接口接入，本版不复制整台电脑或已有 Linux 系统。PaddleOCR-VL 的专用识别方案保留，相关环境锁和配置说明随源码提供；其系统级安装尚未纳入本版一键安装。DeepSeek 等服务需要使用者自己的账号与密钥。

首次发行只接受空安装目录，避免覆盖已有科研资料。需要保留旧版本时，请在另一个目录安装；不要在同一电脑同时运行两个占用相同端口的工作台。升级与资料迁移功能尚未作为本版交付。

本版安装器未购买代码签名证书，Windows 可能显示发布者未知。请核对本仓库来源及附件校验值；安装失败时保留的诊断位于安装目录。停止工作台可双击安装目录内的 `停止科研区.cmd`。

## 开发与重建

自研集成源码位于 `工具/科研流程`，前端源码和锁文件在其 `frontend` 子目录，任务规则和科研技能位于 `.agents`。

发行工具在 `工具/科研流程/distribution`：

- `publish_source.py`：按允许清单导出并扫描源码。
- `build_runtime.py`：从匹配的现有 Python 与服务环境生成独立运行组件。
- `build_release.py`：组合源码、配置模板、许可与环境清单。
- `initialize.py`：创建空白资料目录、生成本机凭据并重建 Python 启动入口。
- `Install.ps1` / `Launch.ps1`：校验安装与复用既有服务管理入口。

从源码重建需要匹配的环境及依赖锁文件。前端的两个目标分别为 `npm run build` 和 `npm run build:knowledge`。普通使用者直接下载安装包，无需执行这些命令。

## 许可和第三方内容

自研工作台源码按 **AGPL-3.0-only** 发布，见 `LICENSE`。第三方软件、字体、模型与库保留各自许可；不能用本项目许可替代它们的条款。环境包保留依赖元数据及许可，版本和来源见 `runtime_inventory.json`、`THIRD_PARTY_NOTICES.md`。

此版本保持本地单用户架构。公开部署为多人网络服务需要另行实现认证、访问控制和资料隔离。
