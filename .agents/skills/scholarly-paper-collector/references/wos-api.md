# WoS 官方 API

优先官方 API，机构网页登录不能替代 API Key 和订阅权限，不复用 Cookie、SID 或私有网页接口。

- Starter：GET `https://api.clarivate.com/apis/wos-starter/v1/documents`，请求头 `X-ApiKey`；参数 `q`、`db=WOS`、`page`、`limit`（最多50，每次查询跨页保持相同 limit）。免费试用有请求额度，且不返回引用数；缺失值不能填成0。
- Expanded：GET `https://api.clarivate.com/api/wos/`，请求头 `X-ApiKey`；参数 `usrQuery`、`databaseId=WOS`、`firstRecord`（从1开始）、`count`。本实现每页最多100条，按返回数量继续分页。需单独获准 Expanded API。
- 明确用 `TS=(terahertz AND starch)` 等字段式。时间窗加入 `PY=(2023-2026)`；不要把普通中文问题直接当作有效 WoS 字段式。
- 保存 WoS UID、DOI、查询式、数据库、API 类型及各自引用指标。主题搜索并没有执行完整引文/参考文献检索，相关任务需额外端点与权限。
- 401/403 记录鉴权或权限问题；429 记录限流或额度，不循环撞接口。若无法访问，交付可运行检索式和缺口；需要网页人工补查时通过用户可见的已登录官方页面，不把网页权限说成 API 已通。

官方文档：[Starter](https://developer.clarivate.com/apis/wos-starter)、[Expanded](https://developer.clarivate.com/apis/wos)、[Starter Swagger](https://developer.clarivate.com/apis/wos-starter/swagger)。权限和额度以账号获批方案及最新返回为准。
