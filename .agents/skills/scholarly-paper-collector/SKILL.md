---
name: scholarly-paper-collector
description: 使用 WoS、OpenAlex、Crossref、Semantic Scholar 与 arXiv 搜索、去重和核实学术题录，保留可复现检索记录；WoS 优先官方 API。用于找论文、补查最新文献、构建综述候选集及导出 BibTeX，不用于普通网页搜索。
---

# 统一文献检索

本工作区只用这个 Skill 管理五个来源。Codex 和科研区内置 DeepSeek 共用 `工具/科研流程/scholarly_search.py` 的检索与本机配置。Skill 是操作说明和辅助程序，具体检索由程序调用官方 API 完成。

## 工作流程

1. 先查 `科研知识库/文献/library.json`、阅读卡片和已有检索记录，复用正式文献 ID、全文路径及已知背景。
2. 将问题转成适合各库的词和时间窗。WoS 使用明确的字段检索式，有 API 权限时先查询；其他库补充发现、出版身份、相关工作与预印本。用户限定来源时照办。WoS 语法和权限见 [wos-api.md](references/wos-api.md)。
3. 通过共用入口执行有限分页检索。记录实际来源、请求、上游总数、取回数量、时间和错误。缺权限、429、零命中和达到本次上限必须区分；不能声称已穷尽整个领域。
4. 按 DOI 和来源稳定 ID 去重，同题不同 DOI 不自动合并；各库引用数保持各自来源。核查预印本与正式出版关系后再归并。
5. 根据真实题录、摘要与可得原文筛选证据。全文获取沿现有工作区/Zotero 流程登记，不重复下载；题录和摘要不视为已核查全文。深度综合再用 `deep-research`，不因 Skill 自带报告功能而跳过原文核查。

## 本机共用入口

在工作区根目录使用既有 Python，不安装新环境：

```powershell
& '工具/科研流程/.venv/Scripts/python.exe' '工具/科研流程/scholarly_search.py' --check-config
& '工具/科研流程/.venv/Scripts/python.exe' '工具/科研流程/scholarly_search.py' --query 'terahertz starch spectroscopy' --wos-query 'TS=(terahertz AND starch AND spectroscop*)' --from-year 2023 --max-results 15
```

来源可用 `--sources wos,openalex,crossref,semantic_scholar,arxiv` 选择；共用入口每来源 1–100 条。只搜 Crossref 可省略 WoS 检索式。内置 DeepSeek 对用户明确的“搜索/检索/找……论文/文献”请求，先生成受限查询计划，由同一程序调用接口，再基于实际返回结果回答。

凭证只由用户在 `http://127.0.0.1:8503` 的“连接与设置 → 软件连接 → 文献检索接口”填写。Windows DPAPI 加密保存；检查配置只显示状态。禁止要求把 Key 发到聊天、写进参数、Skill、报告或检索记录。WoS 和 OpenAlex 未填 Key 时说明待配置；Crossref、arXiv 无需 Key；Semantic Scholar 匿名可能限流。

看板可直接输入中文研究问题，自动生成英文查询后检索；高级设置可先预览并调整。`provider_queries`保存开放来源各自的检索词，`include_groups`保存核心概念同义词组；WoS字段式单独维护。默认排序只按题录/摘要关键词匹配，不用期刊声望、引用数或贡献词代替科研相关性。

每次机器结果保存在 `output/文献检索/<检索ID>/`，包含 `papers/index.json`、`papers/bibtex.bib`、`search-log.json`。它们是候选检索产物，正式收录仍通过工作区/Zotero。`p001` 等仅是当次结果编号，不能作为正式库文献 ID。最近检索可离线重开；人工保留/排除沿原SQLite按检索ID和当次编号保存，可导出保留项。转为持续提醒沿原watch-rules和来源接续，不复制论文库。分区仅作用户筛选条件，保留体系、年度与来源，未知不猜测。

## 其他采集与报告工具

补齐题录、XML 或 PDF 时沿原 ID 合并附件，禁止删除、覆盖或移出已有 PDF；同内容复用，版本不同另存并登记实际路径。PMC 开放附件沿现有 `pmc_fulltext.py` 查询官方 Cloud 版本及 DOI 身份，不猜版本路径。WoS Starter 提供题录与查询能力，不能据此声称一定获得 PDF 或年度分区；分区沿工作区独立来源维护。

需要独立运行上游 `scripts/collect_papers.py`、分析包、中文报告或离线验收时，读 [workspace-workflow.md](references/workspace-workflow.md)；其独立模式使用环境变量，与本机设置页共用模式有区别。报告字段与排名见 [metadata-schema.md](references/metadata-schema.md)、[ranking.md](references/ranking.md)、[report-guidelines.md](references/report-guidelines.md)。来源与许可见 [upstream.md](references/upstream.md)，开放获取边界见 [source-policy.md](references/source-policy.md)。
