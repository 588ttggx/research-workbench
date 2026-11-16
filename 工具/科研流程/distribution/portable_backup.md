# 在 Windows 电脑之间迁移工作区资料

迁移工具用近期本机备份生成一份口令加密的 `.research-backup`。两个电脑都需要包含本指南中迁移命令的工作台源码及 Python 环境。此前发布的 `v0.1.0-preview.1` 安装包没有这两个命令。

1. 在旧电脑先完成一次工作台的普通备份。选择带逐文件校验清单的 `.zip.dpapi`，在工作区根目录打开 PowerShell，替换示例中的输入和输出路径。输出路径的父目录须已存在。

   ```powershell
   & '.\工具\科研流程\.venv\Scripts\python.exe' '.\工具\科研流程\maintenance.py' portable-export '.\备份\已有备份.zip.dpapi' '.\备份\工作区迁移.research-backup'
   ```

   终端会隐藏输入并要求确认至少 16 个字符的迁移口令。迁移包内含私人资料和恢复配置，搬运时分别保存迁移包和口令。导出与恢复均在当前 Windows 用户的本机临时目录暂存解密数据，需要预留至少一个未解包备份大小的空间，单包的内部 ZIP 须小于 64 GiB。命令完成或正常失败后清理中间文件。导出目标盘只接收加密文件。

2. 在新电脑将迁移包放到私人目录。打开新工作区根目录的 PowerShell，用相同口令恢复到一个尚不存在的目录。父目录须已存在。恢复出的文件已经解密，请选择只有自己能访问的位置。

   ```powershell
   & '.\工具\科研流程\.venv\Scripts\python.exe' '.\工具\科研流程\maintenance.py' portable-restore '.\工作区迁移.research-backup' '.\恢复资料'
   ```

   工具验证封包认证和逐文件哈希。工作副本的 `科研知识库/文献/library.json` 按备份中的稳定文献 ID 和附件序号重新指向已经恢复的 PDF/XML。备份缺少的附件继续显示缺失，计数见 `missing_artifacts`。原路径留在 `迁移记录/原文献登记.json` 中供核对。保留迁移包和原电脑资料，直到新机验收完成。

3. 在恢复目录先抽查项目、笔记和原文。要接入一套新装的空白工作台，停止这套安装的受管服务并保留其空白知识库、账本副本，再复制恢复的 `科研知识库` 到新工作区同名目录，把 `数据库/research.sqlite3` 放到 `工具/科研流程/数据/research.sqlite3`。恢复出来的 `原文` 目录应留在原位置，工作副本中的新附件路径指向这里。在新工作台按项目和文献 ID 抽查原页与记录。若新机也有既有项目，应先按项目核对再合并资料。

需要继续用外部服务时，分别将原生数据恢复到独立目标并验证，再接到新工作台。软件运行时、路径及本机凭据按新机重新登记。

- Zotero：关闭程序，在独立数据目录放入已恢复的 `Zotero/zotero.sqlite` 和 `Zotero/storage`，在 Zotero 设置中选择该数据目录。按 `数据库/zotero-native-backup.json` 的附件键和位置重新连接 `Zotero/linked` 中的文件，检查条目、笔记、批注和附件后再启用同步。 [Zotero 数据目录说明](https://www.zotero.org/support/zotero_data)
- Open Notebook：使用匹配版本的 SurrealDB，将 `迁移记录/open-notebook.restore.surql` 导入新的命名空间和数据库。连接参数使用新机登记，原 `数据库/open-notebook.surql` 仍在恢复目录。核对来源和笔记后，将新机的 Open Notebook 接到恢复库，并在本机设置重新登记服务凭据。 [SurrealDB 导入说明](https://surrealdb.com/docs/reference/cli/db/commands/import)
- n8n：关闭新机的独立 n8n 实例，把 `数据库/n8n.sqlite` 和备份的 n8n 加密配置放入该实例规定的数据位置。使用新机设置登记 Windows 本机登录凭据。先检查原生流程和凭据，再启用计划任务。
- RSpace：将 `数据库` 中的 SQL 和媒体归档导入匹配版本的独立 MariaDB 和媒体卷。若由工作台启动 RSpace，将已核对的新机 Compose 配置放在新工作区的 `runtime/RSpace/compose.yaml`，在 `工具/科研流程/数据/RSpace部署.json` 将 `runtime` 登记为 `runtime/RSpace`，并登记新机的实际版本与本地地址。登录检查记录和附件后再接到看板。
