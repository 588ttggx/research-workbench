# 来源与本地改动

基础采集器来自 [shirasufeld/scholarly-paper-collector](https://github.com/shirasufeld/scholarly-paper-collector)，固定版本 `806739290923e870be828c01aee15f8236a16c71`，MIT License；本地保留 LICENSE。

本地改动包括 WoS 官方 API 独立适配、分页和部分失败记录、跨来源身份与引用指标保留、Windows 文本提取、密钥脱敏，以及共用工作区入口说明。WoS 代码根据 Clarivate 官方文档独立实现，没有复制另一个 GPL Skill 的文本或代码。任务中试装的独立 `wos-search` 已由本统一 Skill 替代。

更新上游时先审查差异，保留本地配置连接、凭证边界、来源稳定 ID 和测试，不能直接用上游覆盖本机版本。
