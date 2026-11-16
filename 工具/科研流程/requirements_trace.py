"""Maintain complete, line-preserving traceability for the approved architecture.

Numbered lists inside a chapter are not chapter headings. Original fragments,
line numbers and IDs never change; implementation overrides are kept separately.
"""
from collections import Counter
import re
import workflow as w

TITLES=['项目目标','总体架构','各软件职责','SiYuan顶层结构','统一ID体系','完整科研流程',
        '每日文献雷达','Failure / Lesson / Experience体系','Decision Log','项目经验库',
        '完整科研回溯','Figure必须可回溯','Environment复现','THz QC','AI规则','Research Graph',
        '项目关闭','数据管理原则','第一阶段实施','第二阶段','第三阶段','第四阶段',
        '不要开发的东西','真正需要自己开发的部分','跨系统自动化与同步规则','用户每天的真实体验','最终原则']


def capabilities():
    rows=[]
    def add(id,title,owner,batch,inputs,outputs,trigger,review,status,proof=(),remaining=''):
        rows.append(dict(id=id,title=title,owner=owner,batch=batch,input=inputs,output=outputs,
            trigger=trigger,human_review=review,status=status,evidence=list(proof),remaining=remaining))
    core='工具/科研流程/tests/test_research_core.py'
    catalog='工具/科研流程/tests/test_workspace_catalog.py'
    science='工具/科研流程/tests/test_reproducible_pipeline.py'
    professional='工具/科研流程/tests/test_professional_tools.py'
    interactions='工具/科研流程/tests/test_workspace_interactions.py'
    add('architecture','权威来源与成熟软件边界','各原生软件 / Markdown / SQLite','全批次',
        '原始 27 章与批准的修订','字段 Owner、统一 ID、单向索引和可重建展示','创建与同步时执行',
        '科研判断单独审核','已实现边界；跨软件全链待真实案例',[core], 'RSpace 与实际数据闭环后续验收')
    add('workspace','六区与单一维护入口','看板 / Markdown','第一批','现有论文、笔记、背景、报告与项目',
        '固定六区、统一搜索、同一详情编辑器、反向引用、历史恢复、可恢复归档','打开入口；保存正文后刷新依赖索引',
        '保存正文及采用科研建议由用户确认','已实现；归档隐藏、原稿导航、多笔记和快捷状态已实际界面验收',[catalog,interactions,'工具/科研流程/tests/workspace-graph.test.js','output/科研工作区重构/界面验收.json'])
    add('records','独立科研对象与完整模板','Markdown / SQLite','第一批','用户知识、项目思考与实验设计',
        '42 类模板；独立 Decision / Issue / Failure / Solution / Lesson / Experience / SOP','统一新建入口；保存后登记身份',
        'Gap、假设重要修改、根因、Claim、Lesson、Experience、SOP 与下一步实验需审核',
        '模板及审核已实现；实际经验积累待科研记录',[core])
    add('identity','稳定跨系统身份','SQLite 受控服务','第一批','统一 ID、External ID、Source URI、字段 Owner',
        '原有 ID 保留；新 ID 分配、映射、修订号、审计和并发检查','权威事件或索引同步',
        '身份冲突需核对','已实现并测试',[core])
    add('zotero','文献原生收录与附件','Zotero / 持久化收录队列','第一批','用户选择的 DOI、PDF 或无 DOI 题录',
        '正式 Zotero 条目、附件校验和书目索引；不重复录入元数据','用户选择后自动接续；未知写入先查询核实',
        '收录选择与 Zotero 原生授权；重复书目需核对','长期授权已保存；原生隔离收录与附件验收通过',
        ['工具/科研流程/tests/test_zotero_bridge.py','output/科研工作区重构/Zotero收录验收.json'],
        '无 DOI、未知写入核查、重复执行及附件双校验已通过；新选真实雷达文献的全链还需验收')
    add('note-sync','Better Notes 两端保留与知识主稿边界','Markdown / Zotero / Better Notes','第一批',
        '六份旧 Markdown 与 Zotero 原生 HTML 笔记','两端带校验值快照、版本对照和统一核对入口',
        '每次 Zotero 同步；相同版本不重复生成','冲突正文合并需用户核对',
        '原生窄连接已安装启用，六项旧双向注册通过 Better Notes API 解除；6 份 Markdown 与 34 份原生笔记正文未变，余下本工作区注册为 0',['工具/科研流程/tests/test_note_reconciliation.py','工具/科研流程/tests/test_zotero_note_boundary.py',interactions,'output/科研工作区重构/本轮验收汇总.json'],
        '连接包程序升级在设置页下载并原生安装；日常资料同步继续自动运行。已解除的对照转为可离线查看的历史，独立改稿不重复进入审核；重新出现注册重新核对对应项，冲突原稿保留')
    add('retrieval','本地检索与 AI 候选','Open Notebook / Qwen3 Embedding 4B / DeepSeek','第一批',
        '正式原文、笔记、阅读范围和固定证据片段','可回原文的检索命中、带来源候选、问答和同稿修订草稿',
        '新增或修改资料自动索引；用户提问时检索','不把索引、OCR 或摘要升级为全文核查',
        '已接入；历史资料持续处理',['工具/科研流程/tests/test_relation_discovery.py','output/科研工作区重构/界面验收.json'])
    add('rspace','正式实验平台','RSpace','第三批','真实账号、样品、容器、仪器、校准、正式实验和模板',
        '正式 ELN、Inventory、版本、审计；同步必要状态和数据链接','原生事件优先；没有事件时增量 API 轮询',
        '正式实验、签署及见证遵循实际实例权限','RSpace 2.27.0 已部署至 E 盘 Linux 环境，日常账号、五类原生模板、明确字段映射、增量/分页同步和单向关系已接通；原生隔离读写和重复索引通过', ['工具/科研流程/rspace_connector.py','工具/科研流程/tests/test_rspace_connector.py','output/科研工作区重构/RSpace接入验收.json','output/科研工作区重构/RSpace恢复验收.json'],
        '原生数据库/媒体及应用恢复通过；隔离记录的版本递增、CREATE/WRITE/SIGN 审计、自签只读和 API 拒绝修改已原生验收；见证需有共享权限的实际组员，真实实验全链仍待实际记录验收')
    add('git','代码与配置版本','Git','第二批提前建设','代码、配置、流程脚本与环境锁',
        '可追溯 commit/tag、探索快照与正式冻结边界','分析运行自动采集；不会提交用户其他暂存修改',
        '正式方法和成果冻结需审核','仓库、运行快照与版本冻结入口已实现；原生 Git 标签、逐文件核验、清单下载、并发保护和中断接续已隔离实战验证',[science,'工具/科研流程/run_versions.py','output/科研工作区重构/本轮验收汇总.json'], '冻结计算版本不提高科研审核；正式成果尚无本人真实案例')
    add('datasets','原始与处理数据版本','Data Storage / DVC','第二批提前建设',
        '真实输入、数据 ID、版本、URI、checksum','不可变输入、原生 .dvc 指针、Git 版本与依赖；RUN 引用输入',
        '导入真实数据或已批准流程产出时登记','不自动改变原始数据；数据身份冲突需核对',
        '原生 Git/DVC 隔离验收通过；远程入口、中文路径、自动接续及多版本空缓存恢复已实现',
        [science,'工具/科研流程/data_remote.py','工具/科研流程/tests/test_data_remote.py'],
        '用户于 2026-10-14 选择独立备份后续配置，真实连接保持关闭；尚无本人真实数据')
    add('run','分析运行与多分支谱系','Python / Git / DVC / SQLite','第二批',
        '输入版本、参数、代码、严格环境锁与批准方法','RUN、Result、Figure、日志、指标、DVC stage/lock 与保存的代码',
        '每次分析自动登记；相同成功输入复用','探索运行不能冒充正式实验或正式冻结结果',
        '原生 DVC stage、代码复跑和运行登记接续已实现；明确方法/目录/列对应后，RSpace 完成事件自动保存数据版本并接续 QC/RUN，纯说明变更复用结果且绑定版本核对',[science,'工具/科研流程/analysis_automation.py','工具/科研流程/tests/test_analysis_automation.py','output/科研工作区重构/方法与平台界面验收.json'],
        '运行身份与阶段写入持久账本，成功代码和产物复用；机械版本冻结已隔离验收，真实科研成果与跨软件全链仍需本人记录')
    add('analysis','成熟科学计算与验证设计','NumPy / SciPy / scikit-learn','第二批',
        '坐标、单位、独立样品/批次、制样重复、扫描重复、测量日期与样品参考配对',
        '科学计算、训练折内预处理、分组划分、基线、调参过程与验证记录','输入满足批准方法条件后执行',
        '统计单位、方法条件与正式结论需科研审核','界面已接入按独立样品或批次分类；训练折内标准化/调参、逐独立样品计分、原生 SciPy 分层/批次 bootstrap、划分及参数保存已隔离验证',
        ['工具/科研流程/tests/test_scientific_validation.py',science],'类别或分组不足不报告有效结果；批准的 THz 物理方法与本人数据仍待补齐')
    add('thz','THz Domain Layer 与正式 QC','经过验证的 THz 方法 / SciPy','第二批',
        '实际波形单位、参考配对、厚度/环境/校准、验证数据及批准阈值',
        '基线、去噪、对齐、FFT、传输/相位、吸收/折射率、QC PASS/WARNING/FAIL 和异常候选',
        '只在输入完整且方法获准时自动执行','方法、阈值、根因和科学解释需人工审核',
        '已实现明确适用范围的单程弱界面吸收均匀样片模型，保留样品物理时延；方法参数与正文同稿可改，审核绑定版本，RUN 冻结方法；数值正例、条件拒绝、QC 分级与原生 DVC 复跑通过', ['工具/科研流程/thz_domain.py','工具/科研流程/method_registry.py','工具/科研流程/tests/test_thz_domain.py',science],
        '等待本人真实配对波形、实际条件、方法验证与批准阈值；当前未创建或自动批准本人方法。其他几何/多反射/薄膜模型保留为待领域验证能力')
    add('figures','专业科学图与可修改版本','Matplotlib / Plotly / Graphviz','第二批',
        'RUN 的结果、绘图参数和多来源关系','SVG/PNG/PDF、交互图规格、参数修订历史和来源链；每张图关联 RUN',
        '分析产出后自动保存；修改图表生成关联新版本','正式 Figure 的 Claim/适用条件须审核',
        '实际原生文件导出与 DVC 恢复已隔离验收',[science], '真实 Figure 全链需真实科研记录')
    add('environment','严格环境记录与恢复','uv.lock / Git / 实际系统记录','第二批',
        'Python/关键库、OS/Architecture、代码与环境锁；GPU 时另记驱动/CUDA',
        '环境身份、锁文件、运行快照与独立恢复证据','每次 RUN 自动采集；正式冻结时检查',
        '不能把 requirements.txt 当严格锁；未知 GPU 项不补造','实际独立临时环境按 uv.lock 重建并通过原生计算验收',
        [science,'工具/科研流程/uv.lock','output/科研工作区重构/环境恢复验收.json'],
        '首次补齐普通依赖后，本轮已使用现有缓存离线重建并通过 4 项原生测试；真实项目及 GPU 复现另行验收')
    add('radar','全部关注类型与持续发现','WoS / OpenAlex / Crossref / SQLite / n8n','第一批',
        'Topic/Project/Paper/Author/Institution/Lab/Citation/Retraction 规则',
        '重叠窗口、周期回查、长期 Seen、分页游标、首次发现 Inbox 与来源更新',
        '北京时间 08:30；后台开启期间执行；选择后收录','保存到 Zotero 由用户选择；实验室身份不可猜测',
        '真实 WoS Starter 每日雷达已返回 2/19/50 条并通过状态回报；真实接口分页/Seen/重启通过；全部关注类型、重点/补充范围、无 DOI 收录与迟到 DOI 合并已隔离验收；原生模型为五条重点线索生成四条附原文与阅读范围的排序建议、一条因引文不对应而排除。来源变化失效、并发选择保留和不明付费原批次接续通过；长期覆盖继续观察',
        [core,'工具/科研流程/radar_rank.py','工具/科研流程/tests/test_research_radar.py','output/科研工作区重构/本轮验收汇总.json'])
    add('alerts','撤稿、更正与元数据更新','Crossref / OpenAlex','第一批',
        '收藏 DOI、索引更新、update-to/relation 与撤稿标记','Literature Alert、关联论文/项目影响提示与已见状态',
        '每日运行；失败不推进成功游标','重要影响和发布前多源复核由人完成',
        '持久变化、来源前后值和回查已验收；301 条多页通知中断续跑、无提前发布/成功游标、未索引 DOI 周期回查通过；原生公开接口已隔离核验',
        [core,'工具/科研流程/tests/test_research_radar.py','output/科研工作区重构/界面验收.json'],'不宣称任何单源 100% 无漏报')
    add('weekly','每周研究简报','n8n / Bibliometrix / AI 候选','第一批',
        '本周首次发现论文、关注对象变化及可用字段','新论文、新方法/趋势/团队/引用变化/Gap 候选及项目相关证据',
        '北京时间周一自动生成，成功周次去重','方法、热点、Gap 属候选，不能从题名补造',
        '重点论文/关注动态/引用变化及方法、热点、团队、Gap 的候选流程已实现；原生模型形成四条引文通过机械校验的候选，五条草稿被排除，科研解释仍待人工核查；同一正文预览和本机编辑恢复已界面验收',
        ['工具/科研流程/research_radar.py','工具/科研流程/weekly_brief.py','工具/科研流程/tests/test_research_radar.py','output/科研工作区重构/界面验收.json'],
        '真实周报缺少足够研究证据时保留空候选；真实周一自动执行及多个来源下的研究内容需持续验收')
    add('ranks','中科院与 JCR 年度双分区','年度正式/授权来源 / SQLite','第一批',
        '年度、版本、ISSN/eISSN、学科及 CAS/JIF/JCI 指标',
        '各学科分区、年度、来源、歧义/缺失状态；不挑最好分区','年度来源导入一次，文献与雷达自动关联',
        '来源冲突与身份歧义需核对','CSV 适配、审核展示和回归测试通过',
        ['工具/科研流程/tests/test_journal_ranks.py'],'尚未提供实际有权使用的年度来源数据')
    add('automation','持久化自动化与单向同步','n8n / SQLite 业务账本','第一批至第二批',
        '权威事件、游标、稳定身份、任务输入与幂等键','阶段进度、重试、成功复用、审计、最后成功状态、重启恢复',
        'Webhook > API 增量 > 定时；保持单一调度路径','字段 Owner 和冲突策略未明确时不双向覆盖',
        '任务阶段统一进入账本；管理员/关联/同步/雷达/原生实验共用任务；RSpace 完成后自动分析共用事件路径。原始数据先保存、条件不足等待、成功复用、中断接续、版本绑定核对及方法/实现变更暂停均已隔离实战验证',[core,'工具/科研流程/tests/test_research_radar.py','工具/科研流程/tests/test_analysis_automation.py','output/科研工作区重构/方法与平台界面验收.json'],
        'n8n 已实际接续分页；长时间离线的真实停机接管、本人真实 RSpace 实验和专业跨系统全链仍需验收')
    add('model-recovery','结果不明的模型请求恢复','SQLite / DeepSeek Connector','第一批',
        '模型调用指纹、响应状态、审计和用户核查说明','成功响应复用；未知付费请求阻塞且保留；核查后受控释放',
        '超时或响应无效时立即进入待核；不盲目重付费',
        '再次付费调用需用户核查并明确选择','已实现并测试',[core])
    add('review','科研判断审核','SQLite 受控服务 / Markdown','第一批',
        'Candidate、来源定位、适用条件和打开时版本','Human Review → Verified Record；来源变化使旧审核失效',
        '候选生成、正文/证据修改时登记','Claim、关系、Gap、根因、Lesson、Experience、SOP、下一步实验均需确认',
        '已实现；来源版本校验、证据详情、搜索筛选和分页已实际界面验收',[core,interactions,'工具/科研流程/tests/test_relation_discovery.py','output/科研工作区重构/界面验收.json'])
    add('provenance','持久关系与六类回溯','SQLite / Git 只读快照 / Graphviz','第一批至第二批',
        '正式对象、关系类型、证据定位、条件、状态、时间及版本',
        '科研逻辑/实验/数据/计算/决策/经验链；Figure 多来源分支与缺失提示',
        '机械关系自动登记；科研关系确认后持久化','Supports/Contradicts/Inconclusive 必须有证据并审核',
        '六类切换、多分支、原稿跳转与缺失提示已交付并实际界面验收；候选或过期 AI 依据不进入正式路径；不限制固定回溯深度，29 节点与循环关系已验证；当前 Figure 只沿实际生产 RUN 回溯，Graphviz 图可打开对应图表，原生 RSpace 节点直接打开原记录',
        [core,'工具/科研流程/provenance_views.py','工具/科研流程/graph_exports.py','工具/科研流程/tests/test_graph_exports.py','工具/科研流程/tests/test_validation_runs.py','output/科研工作区重构/实战界面验收.json'],
        'RSpace 已接入，实验链仍需真实实验记录；不能自动补造缺失节点')
    add('experience','失败、决策与长期经验复用','Markdown / SQLite / 本地检索','第一批至第二批',
        'Issue→Failure→Solution→Lesson→跨项目验证→Experience→SOP；独立 Decision Log',
        '项目记忆、证据与替代方案、失败尝试、边界和新项目经验推荐','项目积累时登记；新项目启动检索历史',
        '根因、经验和 SOP 更新需审核','打开项目自动检索历史方法/失败/经验；沿原稿展示来源、状态，向量未就绪时明确使用文本匹配；两项目隔离验收通过',[core,'工具/科研流程/project_memory.py','工具/科研流程/tests/test_validation_runs.py'],
        '需要多个真实项目和经验记录验收')
    add('closure','项目关闭完整清单','Markdown / Git / DVC / 原生软件','第二批至第三批',
        '原始 15 项关闭清单、项目记忆及全部产物','冻结数据、Git Tag、环境冻结、复现/恢复、决策失败经验整理与归档',
        '项目关闭时核验全部清单','不能仅勾选清单就宣称实际独立恢复成功',
        '原始十五项与独立恢复集中核对；关联当前依据、变更失效、并发检查、受控关闭及中断接续已隔离验证；本人项目保持 ACTIVE',[core,'工具/科研流程/project_closure.py','工具/科研流程/tests/test_project_closure.py','output/科研工作区重构/实战界面验收.json'], '需真实项目全部证据与可独立恢复验收')
    add('backup','逻辑真源、备份与独立恢复','原生导出 / SQLite 一致快照 / Data Storage','第一批至第三批',
        '统一 ID、版本、checksum、权威正文、原文与软件配置','受保护备份、校验清单、恢复演练和容灾策略',
        '已批准备份操作；关闭项必须检查','同盘副本不算独立容灾；原稿不随意迁移',
        '整套备份与隔离原生恢复已验收；历史报告和专业产物逐文件校验；Zotero 原生在线数据库、库内与外链附件保留稳定 ID、笔记和分类；原生 DVC Remote 接续、旧版本保留、离线退避、配置冲突及空缓存恢复已隔离验证',
        ['工具/科研流程/data_remote.py','工具/科研流程/tests/test_data_remote.py','工具/科研流程/zotero_native_backup.py','工具/科研流程/tests/test_zotero_native_backup.py','工具/日志/科研备份验收.json','output/科研工作区重构/恢复演练验收.json','output/科研工作区重构/资料保留基线.json'],
        '用户选择独立存储后续配置；现有 DPAPI 备份限本机，C/E 为同一物理硬盘；Zotero 完整原生配置及异机恢复仍需验收')
    add('cytoscape','日常交互与专业网络精修','Cytoscape.js / Cytoscape Desktop','第一批基本图；后续专业分析',
        '当前问题的邻近证据、来源和候选状态','交互网络、原生会话、SVG/PNG、筛选/布局与精修；自动版和历史版保留',
        '关系变化自动更新；专业软件按需打开，成功版本复用','AI 只准备关系候选，不能自动变正式事实',
        '桌面完整/问题网络、SVG 缩放和原生去重叠/组件排列通过；Analyzer 在 108 对象/168 关系上保存原生指标；clusterMaker2 2.3.4 的 GLay 在实际 54 对象/120 关系上形成 12 组，原生 fdp 分组排版、局部图和离线复用通过；MCODE 正例隔离验证，当前网络未返回可用结果时如实保留状态',
        [professional,'output/科研工作区重构/专业网络/2f25b6fff3a955e66d84/receipt.json',
         'output/科研工作区重构/专业网络/9bf8e08faf74d2219cae/receipt.json',
         'output/科研工作区重构/专业网络/091b76f518165d055c5e/聚类分析.json',
         'output/科研工作区重构/界面验收.json'])
    add('bibliometrix','完整专业文献计量','Bibliometrix / Biblioshiny','后续专业能力',
        'WoS/Scopus/PubMed 完整记录，或现有 Zotero 可用字段',
        '共引、耦合、共词、合作网络、主题地图/演化、Historiograph、趋势及原生对象',
        '分析区一次运行；按输入与方法版本复用','缺机构/关键词/参考文献时显示缺失，不伪造网络',
        '官方 500 条样例的全部 10 项原生任务通过；实际 Zotero 语料和 Biblioshiny 已运行',
        [professional,'工具/科研流程/r/analyze_bibliography.R',
         'output/科研工作区重构/专业工具验收.json',
         'output/科研工作区重构/文献计量/f07b0f72be8dd1fbeda0/receipt.json'],
        '公开样例未并入本人科研库；当前项目 28 篇语料只有 1 篇含部分题录，真实文献研究需补齐权威字段')
    add('vosviewer','文献网络专业呈现','VOSviewer','后续专业能力','Bibliometrix 原生网络与权重',
        'Paper/Author/Keyword/Institution 网络的原生可编辑 map/network 与图',
        '分析详情按需打开；保留精修与同输入历史版本','不把管理标签当科学关键词',
        '实际作者合作网络已导出；其他网络待完整题录',
        [professional,'output/科研工作区重构/文献计量/8bda75246f79cf193ed1/VOSviewer-author-collaboration/network.svg'])
    add('hyperspy','多维光谱与成像','HyperSpy','真实多维任务启用','X×Y×Frequency 及真实光谱/成像任务',
        '多维查看、PCA/Decomposition/Fitting、版本与产物谱系','真实任务出现后接入批准流程',
        '分解、拟合和科学解释需核查','按批准计划待真实任务启用',(), '没有真实多维数据，不先安装冒充完成')
    add('mlflow','多 Run 模型管理','MLflow','多 Run 管理需求出现时','真实 ML 参数、指标、模型、数据版本',
        'Run/Artifacts/Model Version/Dataset 与模型谱系','实验量达到管理需求后接入',
        '模型正式采用与解释需审核','按批准计划待条件启用')
    add('instrument','仪器自动采集连接器','仪器原生 API / SDK','设备支持后','可用设备、SDK/API 与真实采集条件',
        'Instrument→EXP→Raw Data→QC→Pipeline 的身份和事件','原生采集事件触发',
        '真实实验操作与异常由人负责','等待实际设备与 API 条件',(), '不能根据组内论文推断当前本人可用设备')
    add('roadmap','完整实施批次与验收门槛','各阶段负责软件','全批次','本版批准计划及原始全部需求',
        '第一批/第二批/第三批/条件启用清单与逐项证据','按真实案例交付推进',
        '第一批完成不等于系统完成；安装成功不等于功能成功',
        '持续实施；未通过的项目保留',[ 'tasks/科研工作区实施状态.md'])
    for row in rows:
        row['acceptance']=row['output']+'；检查来源、重复执行、中断恢复与原稿保留；'+(row['remaining'] or '以列出的测试及实际操作证据核对')
    return {row['id']:row for row in rows}


CHAPTER_CAPS={
 '附件':['architecture','roadmap'],'1':['architecture','roadmap'],'2':['architecture','identity','provenance','backup'],
 '3':['architecture'],'4':['workspace','records'],'5':['identity'],'6':['records','run','thz','review','experience','closure'],
 '7':['radar','alerts','weekly','ranks'],'8':['records','experience','review'],'9':['records','experience'],
 '10':['experience','retrieval'],'11':['provenance','run','rspace','experience'],'12':['provenance','figures','run'],
 '13':['environment'],'14':['thz','review'],'15':['review','model-recovery'],'16':['provenance','cytoscape','bibliometrix','vosviewer'],
 '17':['closure'],'18':['architecture','datasets','backup'],'19':['roadmap','workspace','zotero','run','rspace','radar'],
 '20':['automation','run','review','thz','rspace'],'21':['bibliometrix','vosviewer','cytoscape','hyperspy'],
 '22':['mlflow','instrument'],'23':['architecture'],'24':['workspace','automation','thz','retrieval','provenance'],
 '25':['automation','identity','zotero','rspace','run','review','model-recovery'],
 '26':['workspace','automation','review'],'27':['architecture','roadmap','closure','backup']}
TOOLS={'3.1':['workspace','records','experience'],'3.2':['zotero','note-sync'],'3.3':['rspace'],
       '3.4':['git'],'3.5':['datasets','run'],'3.6':['analysis','thz'],'3.7':['hyperspy'],'3.8':['mlflow'],
       '3.9':['radar'],'3.10':['alerts'],'3.11':['bibliometrix'],'3.12':['vosviewer'],'3.13':['cytoscape','provenance'],'3.14':['automation']}


def rebuild():
    path=w.ROOT/'tasks/科研工作区需求对照.json';value=w.read_json(path)
    source=w.ROOT/value['source'];raw=source.read_bytes()
    if w.digest(raw)!=value['source_sha256']:raise ValueError('冻结的原始需求已变化，未重写对照')
    lines=raw.decode('utf-8-sig').splitlines();caps=capabilities();chapter='附件';section='';scope=None
    expected={f'{number}. {title}':str(number) for number,title in enumerate(TITLES,1)}
    original={item['original_line']:item for item in value['items']}
    rows=[]
    for number,line in enumerate(lines,1):
        text=line.strip()
        if not text:continue
        if text in expected:
            chapter=expected[text];section=text;scope=None
        elif chapter=='3' and (match:=re.match(r'^(3\.\d+)\s+',text)):
            scope=match[1];section=text
        elif re.match(r'^[A-J]\.\s|^Phase 1[ABC]：',text):section=text
        item=original[number]
        if item['requirement']!=text:raise ValueError('原始需求行不一致：'+str(number))
        ids=TOOLS.get(scope,CHAPTER_CAPS[chapter]) if chapter=='3' else CHAPTER_CAPS[chapter]
        coverage=[caps[id] for id in ids]
        updated={**item,'chapter':chapter,'section':section,'capability_ids':ids,
                 'status':'按能力项核对工程证据；本人科研与外部条件分别验收'}
        for field in ('owner','batch','input','output','trigger','human_review','acceptance'):
            updated[field]='；'.join(dict.fromkeys(row[field] for row in coverage))
        updated['evidence']=list(dict.fromkeys(proof for row in coverage for proof in row['evidence']))
        rows.append(updated)
    if len(rows)!=len(value['items']):raise ValueError('需求条目数量不一致')
    value.update(schema=2,updated=w.now(),note='原始非空行、ID 与原文逐字保留；27 章按真实标题定位，内部编号不会重置章节。每行关联具体能力、负责软件、输入输出、自动触发、审核和验收证据。状态不等于全部功能完成。',
        implementation_overrides=['用户取消 SiYuan：Markdown 承接知识主稿，看板为日常入口，SQLite 管身份/关系/审核/账本。',
            'RUN 与实际 EXP 分开；Git/DVC/数据结构和科研验证提前；n8n 沿用且不重复调度。',
            '新增年度中科院/JCR 双分区、可修改的图表历史、资料统一编辑与引用影响提示。',
            '用户于 2026-10-15 撤销软件实战演练产品入口：提供的资料仅作内部验收；保留原始数据和工程证据，分析首页统一选择文件。',
            'RSpace 原生平台与连接已部署，真实实验及签署仍需验收；HyperSpy/MLflow/仪器连接器按真实任务条件启用，未删除。'],
        capabilities=list(caps.values()),items=rows)
    w.write_json(path,value)
    return audit()


def audit():
    value=w.read_json(w.ROOT/'tasks/科研工作区需求对照.json')
    source=(w.ROOT/value['source']).read_bytes();lines=source.decode('utf-8-sig').splitlines()
    actual={number:line.strip() for number,line in enumerate(lines,1) if line.strip()}
    ids=[item['id'] for item in value['items']];caps={row['id'] for row in value.get('capabilities',[])}
    valid=(value['source_sha256']==w.digest(source) and len(ids)==len(set(ids))
           and {item['original_line']:item['requirement'] for item in value['items']}==actual
           and all(item.get('capability_ids') and set(item['capability_ids'])<=caps for item in value['items']))
    if not valid:raise ValueError('需求覆盖校验未通过')
    counts=dict(Counter(item['chapter'] for item in value['items']))
    if set(counts)!={'附件',*[str(i) for i in range(1,28)]}:raise ValueError('章节不完整')
    result={'verified':True,'source_sha256':w.digest(source),'original_fragments':len(ids),'chapters':27,
            'capabilities':len(caps),'counts':counts,'complete_system':False,'checked':w.now()}
    w.write_json(w.ROOT/'output/科研工作区重构/需求覆盖验收.json',result)
    return result


if __name__=='__main__':
    import json,sys
    print(json.dumps(rebuild() if '--update' in sys.argv else audit(),ensure_ascii=True))
