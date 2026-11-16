> 这些类型用于理解具体审稿意见，不预测个人结果；缺少原始语料时不将历史效果作为策略权重。

# 审稿人心态识别启发式规则

对 Review 文本逐项打分（1=低，5=高），再对照心态簇特征匹配。

## 行为信号评分表

| 信号 | 高（5）典型表述 | 低（1）典型表述 |
|------|----------------|----------------|
| **Openness** | "willing to raise", "if addressed", "open to" | "reject", "not convincing", "final decision" |
| **Severity** | "fundamental flaw", "fatal issue", "strong reject" | "minor concern", "small issue" |
| **Constructiveness** | "I suggest", "would strengthen if", "recommend adding" | 纯否定，无改进路径 |
| **Specificity** | 引用 Table 2、Sec 3、方程编号 | "overall not convincing"，无具体指向 |
| **Skepticism** | "not convinced", "insufficient evidence", "doubtful" | 中性措辞，未表达怀疑 |
| **Harshness** | "reject", "misleading", "wrong", "unacceptable" | 礼貌委婉 |
| **Actionability** | "add experiment", "compare to X", "ablation needed" | 无可执行建议 |

## 六类心态速查（定性启发式，统计来源待核）

| 心态 | 典型信号组合 | 上分率参考 | 核心应对策略 |
|------|-------------|-----------|-------------|
| **精准建设型** | 高 constructiveness + 高 specificity + 高 actionability | 不可估计（缺可核验样本） | 逐条结构化回应，引用论文具体位置 |
| **温和质疑型** | 低 severity + 低 actionability，措辞模糊 | 不可估计（缺可核验样本） | 直接消除困惑，自信但不过度解释 |
| **实验导向型** | 高 evidence_gap 质疑，多次要求对比 | 见 mindset-library | 补实验或解释为何现有结果充分 |
| **高怀疑严厉型** | 高 skepticism + 高 severity + 打分低 | 不可估计（缺可核验样本） | 硬证据优先，收窄 claim，接受局限 |
| **强硬多质疑型** | 高 harshness + 多条 concerns + 篇幅长 | 不可估计（缺可核验样本） | 新实验 + 直接引用论文 + 明确承诺 |
| **其他** | 不明显匹配 | - | 优先识别最突出的单一信号 |

详细统计（涨分率、Cohen's d 效应）见 [mindset-library.md](mindset-library.md)。

## 匹配流程

1. 对 5–7 个信号打分，记录触发该分数的具体原文短语。
2. 将信号组合与上表对照，选最接近的心态。
3. 若两个心态接近，标注 **primary + secondary**。
4. 置信度：3 个以上信号对齐 → **高**；Review 过短/通用 → **低**。

## 置信度对输出的影响

| 置信度 | 操作 |
|--------|------|
| 高 | 直接使用该心态的 success_patterns 指导策略 |
| 中 | 列出 primary + secondary，分别给出策略差异说明 |
| 低 | 以通用策略为主，说明心态判断不确定 |
