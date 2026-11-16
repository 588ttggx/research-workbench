"""One vocabulary for persistence, menus, graph labels and direction help."""

GROUPS = ['资料与项目','研究问题与证据','实验与质量','数据与计算','决策与经验','成果与版本']
_ROWS = [
 ('About','涉及概念',0,'论断或知识内容 → 其实际涉及的概念；不表示科学支持。'),
 ('AssociatedWith','主题相关',0,'两个概念在给定原文范围内存在可定位的主题联系；不表示因果或支持。'),
 ('RelatedTo','内容相关',0,'起点与目标内容相关；不表示支持结论。'),
 ('Documents','记录',0,'笔记或报告 → 被记录的对象、过程或事件。'),
 ('BelongsTo','属于',0,'资料、样品或数据 → 所属项目或批次。'),
 ('Cites','引用论文',0,'引用者 → 被引用论文；不表示已核查或支持。'),
 ('MethodSimilar','方法相近',1,'起点与目标的方法存在可定位的相似处。'),
 ('Supports','支持',1,'证据 → 得到支持的假设或论断；须说明适用条件。'),
 ('Contradicts','反驳',1,'证据 → 受到反驳的假设或论断。'),
 ('Inconclusive','证据未定',1,'证据 → 尚不能确定的假设或论断。'),
 ('Addresses','回应问题',1,'项目、研究或方法 → 所回应的问题或缺口。'),
 ('Tests','检验',1,'实验或分析 → 被检验的假设或问题。'),
 ('Motivates','促成研究',1,'文献、缺口或问题 → 由此提出的研究。'),
 ('Formulates','提出问题',1,'研究缺口 → 从中提出的研究问题。'),
 ('Validates','验证方法',1,'验证记录或数据 → 被验证的方法或模型；注明验证范围。'),
 ('PreparedFrom','制备自',2,'样品或制样 → 原材料、批次或独立样品。'),
 ('TreatedBy','经过处理',2,'样品 → 采用的处理记录。'),
 ('MeasuredWith','使用仪器测量',2,'实验或测量记录 → 实际使用的仪器。'),
 ('CalibratedBy','依据校准',2,'仪器或测量记录 → 有效校准记录。'),
 ('FollowsSOP','遵循规程',2,'实验或处理 → 实际执行的 SOP 版本。'),
 ('MeasuredUnder','测量条件',2,'实验或测量 → 温湿度等环境记录。'),
 ('CheckedBy','接受质量检查',2,'数据或实验 → 对应 QC 记录；不自动表示通过。'),
 ('HasReference','采用参考记录',2,'信号或数据集 → 实际配对的参考记录；未知时不能猜配。'),
 ('Uses','使用／方法参考',3,'起点 → 所使用或参考的方法、数据、工具；在依据中区分使用与参考。'),
 ('DerivedFrom','来源于',3,'派生数据或结果 → 原始输入。'),
 ('ProducedBy','生成于',3,'数据、结果或图 → 生成它的实验、RUN 或流程。'),
 ('InputTo','作为输入',3,'数据或参数 → 接收它的 RUN 或流程。'),
 ('AnalyzedBy','由流程分析',3,'数据 → 执行分析的流程或 RUN。'),
 ('ParameterizedBy','采用参数',3,'RUN 或模型 → 参数记录及版本。'),
 ('ExecutedIn','运行环境',3,'RUN → 实际环境记录。'),
 ('UsesVersion','使用版本',3,'RUN 或产物 → 数据、代码或流程的明确版本。'),
 ('Reproduces','复现',3,'复跑记录 → 被复现的运行或结果；注明一致性检查。'),
 ('Resolves','解决',4,'解决方案 → 所解决的问题或失败。'),
 ('LearnsFrom','从中总结',4,'教训或经验 → 实际经历、失败或结果。'),
 ('Reuses','复用',4,'新项目或运行 → 复用的经验、方法或数据。'),
 ('BasedOn','决策依据',4,'决策 → 当时使用的证据。'),
 ('HasOutcome','实施结果',4,'决策或变更 → 实际实施结果。'),
 ('Generalizes','归纳经验',4,'长期经验 → 支持归纳的多个教训或项目。'),
 ('Updates','促成规程更新',4,'已核实的经验或教训 → 更新后的 SOP 版本。'),
 ('Visualizes','展示结果',5,'图或表 → 展示的一个或多个结果。'),
 ('PublishedAs','形成成果',5,'结果或论断 → 形成的论文、数据集等成果。'),
 ('Supersedes','替代旧版',5,'新版 → 被替代的旧版；历史保留，不删除对象。'),
 ('FrozenAs','冻结为版本',5,'项目或数据 → 已冻结的版本记录。'),
 ('ArchivedAt','归档位置',5,'成果或数据 → 已核验的归档记录。'),
]
RELATIONS = {key:dict(id=key,label=label,group=GROUPS[group],description=description)
             for key,label,group,description in _ROWS}
MECHANICAL = {'DerivedFrom','Uses','ProducedBy','Documents','BelongsTo','CheckedBy'}


def definitions():
    return list(RELATIONS.values())
