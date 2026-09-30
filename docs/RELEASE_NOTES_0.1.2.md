# OpenList Codex Plugin v0.1.2

新增 OpenList 网页登录关联：双击 `关联OpenList.cmd`，在打开的 OpenList 窗口登录，验证后自动启动 Codex 并测试连接。无需手工获取 Token，密码在 OpenList 网页输入。

- 支持 Windows Microsoft Edge 和 Google Chrome 的专用持久化关联窗口。
- 关联窗口打开时同步登录、换账号和退出；使用 `/api/me` 验证登录状态。
- 连接器会话在 Windows 使用当前用户 DPAPI 保护；Linux 使用用户文件权限。
- 保留原有账号密码与 Token 配置方式，继续提供连接检查、目录列表、文件名搜索和下载工具。
- GitHub Actions 可从版本号自动测试、构建 ZIP、wheel、源码包及 SHA256SUMS，并创建预发布版本。

首次下载请使用附件 `openlist-codex-plugin-0.1.2.zip`，解压后运行 `关联OpenList.cmd`。需要 Codex CLI、Edge 或 Chrome，以及 uv 或可用于安装 uv 的 Python。

关联窗口与普通浏览器配置分开。已经在普通浏览器登录的用户，首次需在关联窗口再登录一次。关闭窗口后停止观察登录变化，重新运行启动器可恢复；登录过期、修改密码或 OpenList 重启后可能需要重新登录。

此版本通过社区插件源分发，不代表已经上架 Codex 官方目录。
