# 0.1.1 验证记录

2026-09-30，在 Windows、Python 3.12.9 下运行：145 项通过，5 项平台相关测试跳过；ruff 检查通过。新增模拟 HTTP 认证测试覆盖密码哈希、并发登录缓存、失败不重试、过期后重新登录、凭据互斥与错误脱敏。Codex CLI 已成功安装 0.1.1。

尚未使用真实账号密码验证本机 OpenList；需要用户在本机输入凭据。以下为原版附带的历史记录，不能视为本次新版的真实网盘测试。

# 验证记录

2026-09-30，使用 Python 3.12.14、MCP SDK 1.30.0、httpx 0.28.1、Codex CLI 0.159.0-alpha.3 和真实 OpenList v4.2.6。

## 已验证

- 锁定依赖安装成功。
- 通用版具有 136 项模拟 HTTP 单元测试，覆盖路径、权限受限凭据文件、错误和字段过滤、目录分页、搜索预算、跨挂载路径及代理下载保护。
- 当前 CLI 成功识别 `openlist@heavenyygq-openlist` 的原生插件和独立 marketplace 清单。
- `scripts/smoke_openlist.py` 通过 11 项 stdio MCP 检查，包括中文目录、文件名搜索、按字节下载一致、防止覆盖与错误传播。
- `scripts/smoke_multimount.py` 通过 5 项实际跨存储检查：同一受限账号浏览两个挂载、搜索跨挂载文件名，以及 Local 与 WebDav 两种驱动的代理下载按字节一致。

实际服务包含 Local 驱动的测试挂载 `/Quark` 和 WebDav 驱动的 `/WebDAV`。前者只是本地测试目录的名字，不是真实夸克账号。WebDAV 测试使用本机 WsgiDAV 服务，身份验证由 OpenList 驱动处理；插件只持有普通 OpenList 用户的 Token。

结果记录在 `artifacts/openlist-mcp-smoke.json` 和 `artifacts/openlist-multimount-smoke.json`，不包含凭据、签名 URL 或私密网盘资料。

## 复现

配置自己的 Local 专用测试挂载、WebDAV 测试挂载及受限只读用户。Local 包含 `你好 世界.txt` 和 `中文资料/会议纪要.md`；WebDAV 包含 `跨网盘说明.txt`。只将本机测试 Token 保存在 `0600` 文件中，不把凭据写入命令。

```bash
export OPENLIST_URL="http://127.0.0.1:5244"
export OPENLIST_TOKEN_FILE="$HOME/.config/openlist-codex/openlist-token"
export OPENLIST_ROOT="/"
uv run --no-cache --locked python scripts/smoke_multimount.py \
  --local-fixtures /absolute/path/to/local-fixtures \
  --webdav-fixtures /absolute/path/to/webdav-fixtures \
  --report artifacts/openlist-multimount-smoke.json
```

脚本用于上述指定测试挂载，并把下载写入自动清理的临时目录。它不配置真实网盘、不登录网盘、不代表所有驱动都兼容。

## 限制

尚未对每个 OpenList 网盘驱动进行真实账号测试。网盘会话、套餐、限速、大小元数据和代理能力可能不同。本次未发布到公共 GitHub，也未进入 Codex 官方精选插件库；公开发布状态应以实际仓库和 Release 为准。
