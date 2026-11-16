# 本工作区检索约定

用户于 2026-10-18 要求：安装既有四源采集 Skill，更新搜索流程，将 WoS 加入同一个 Skill；AI 使用 WoS 优先官方 API。随后用户要求在本机配置，并使 Codex 与内置 AI 都能直接搜索；共用入口为 `工具/科研流程/scholarly_search.py`，通过本机设置页共享加密凭证，不新增自动定时任务。

## 运行入口与范围

- 从工作区根目录运行 `工具/科研流程/.venv/Scripts/python.exe .agents/skills/scholarly-paper-collector/scripts/collect_papers.py`，不新建 Python 环境。
- 先查 `科研知识库/文献/library.json`、阅读卡片及相关历史检索。复用已有文献 ID 和附件；此次机器结果保存在项目 `output/文献检索/`，不另建正式书目库。
- 采集程序只生成检索结果、检索账本和 BibTeX；正式收录沿现有看板/Zotero 操作，不直接改 Zotero 数据库或正式阅读状态。
- WoS 官方 API 默认优先。原始查询必须通过 `--wos-query` 指定；Starter / Expanded 的字段和权限分别按官方说明判断。详见 [wos-api.md](wos-api.md)。
- 多源共同使用时，把同一研究问题分别翻译成各来源支持的查询；记录时间范围、实际请求、上游总数与实际取回数，达到结果上限不代表全部收齐。
- 开放全文默认不下载。用户需要获取全文时先查已有附件，通过工作区现有获取/导入入口登记真实路径、失败状态和阅读范围。

## 配置与凭证

用 `--check-config` 查看各来源是否已配置，只输出布尔状态，不显示密钥或邮箱。密钥遵循工作区要求，仅由用户在本机设置中填写并供给进程，不发送到聊天、不作为命令行参数、不写入 Skill、检索账本或示例文件。本机共用入口从 Windows DPAPI 配置读取，独立上游采集脚本仍支持环境变量/私有配置读取；不要把本机凭证复制到明文配置。

- `WOS_API_KEY`：WoS API Key；`WOS_API` 为 `starter`（默认）或 `expanded`，`WOS_DATABASE` 默认 `WOS`。
- `OPENALEX_API_KEY`：启用 OpenAlex；没有 Key 时保留“待配置”，不把跳过当成零命中。
- `SEMANTIC_SCHOLAR_API_KEY`：可选；匿名遇 429 立即记录限流，不持续重试。
- `SPC_CONTACT_EMAIL`：Crossref 的真实联系邮箱；无邮箱时按公共接口保守限速。不要使用示例邮箱。
- arXiv 无需 Key；全局连续请求至少间隔 3 秒。
- `UNPAYWALL_EMAIL` 仅用于可选开放全文位置补查，不为普通元数据查询自动逐 DOI 调用。
- `SPC_CACHE_DIR` 可指定缓存；默认使用当前用户的 `LOCALAPPDATA`（未设置时为用户主目录）下的 `ResearchWorkbench/Cache/scholarly`。

## 流程与交付

1. 明确问题、时间窗、研究类型和需要的来源，先列本地已有证据及缺口。
2. 有 WoS 权限时先做 WoS API 查询；OpenAlex 扩展发现、Crossref 核对身份与出版信息、Semantic Scholar 补相关论文、arXiv 补预印本。按任务选源，不强制每次全库搜索。
3. 保留原始 API 响应缓存，按分页接续到本次上限或实际结束；失败保留已取回页和状态。401/403 是权限问题，429 是限流/额度问题，不能改成“查无论文”。
4. 按 DOI、WoS UID、OpenAlex/S2/arXiv ID 去重；同题但 DOI 不同的记录不自动合并。保留来源各自的引用数与查询时间，不能混成 WoS 引用指标。
5. 对照正式库给已有记录附 `workspace_matches` 和现有附件位置；不重复下载、不升级阅读状态。
6. 按相关性筛选，再把实际题录/摘要/原文交给 `deep-research` 或既有分析流程；区分发现、摘要读取、全文取得和精读。

结果写入同一任务输出目录下的 `papers/index.json`、`papers/bibtex.bib` 和 `search-log.json`。已存在的结果默认保留，明确刷新机器结果才使用 `--refresh`；分析正文不自动覆盖。`p001` 等是本次输出内部编号，不是工作区正式文献 ID。

## 验收边界

离线测试覆盖 WoS 两种 API 解析与分页、缺密钥、认证头脱敏、四源分页、限流等待、Windows 文本提取和跨来源身份保留。用既有 Python 运行 `-m unittest discover -s .agents/skills/scholarly-paper-collector/scripts/tests -p test_workspace_search.py`。技能元数据另用 skill-creator 的 `quick_validate.py` 验证；真实联网只作小量查询，不消耗未配置的授权，不声明本机没有执行的服务验收。
