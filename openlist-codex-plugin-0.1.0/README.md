# OpenList Codex 插件

通过用户自己的 [OpenList](https://github.com/OpenListTeam/OpenList) 访问已挂载的各种网盘和文件存储。支持连接检查、目录列表、文件名搜索和下载文件到本机。

插件使用 OpenList 的统一文件 API，不绑定夸克等某个网盘，也不直接收集网盘 Cookie。具体驱动的登录、会话维护、套餐限制和代理能力由用户的 OpenList 管理。能在 OpenList 中正常浏览并通过本机 Web 代理下载的挂载可以使用本插件；不保证每个存储驱动或每种下载模式均兼容。

这是 `0.1.0` 社区预发布版，非 OpenList 或 OpenAI 官方产品，尚未进入 Codex 官方精选库。单个网盘需要用户自行验证；已执行检查记录见 [验证说明](docs/VALIDATION.md)。

## 准备与配置

- Python 3.11+、uv，以及支持 `codex plugin` 的 Codex。
- 自己控制的 OpenList，已配置所需网盘。
- 限制到所需目录的只读普通用户；启用存储的 `Web 代理` 和下载签名，保持外部下载代理 URL 为空。
- 将该用户的 OpenList 登录 Token 保存到权限 `0600` 的本机文件；不要使用管理员 Token，也不要把凭据放进聊天、Git 或命令历史。

| 配置 | 默认或说明 |
| --- | --- |
| `OPENLIST_URL` | `http://127.0.0.1:5244`；远程实例必须使用 HTTPS |
| `OPENLIST_ROOT` | `/`，即受限用户可见根目录；可配置为某个网盘或子目录 |
| `OPENLIST_TOKEN_FILE` | `~/.config/openlist-codex/openlist-token`，文件内容仅为 Token |
| `OPENLIST_TOKEN` | 可选安全环境注入，与显式 `_FILE` 二选一 |
| `OPENLIST_PATH_PASSWORD_FILE` | 可选的锁定目录密码文件 |
| `OPENLIST_PATH_PASSWORD` | 可选安全环境注入，与对应 `_FILE` 二选一 |
| `OPENLIST_DOWNLOAD_DIR` | 工作目录下 `openlist-downloads`；插件安装后应设置为用户项目内的绝对目录 |
| `OPENLIST_MAX_DOWNLOAD_BYTES` | `104857600`，即 100 MiB；允许 1 字节至 10 GiB |

路径始终相对于 `OPENLIST_ROOT`，使用该用户在 OpenList 中可见的路径。如果用户基础路径已经限定到某个网盘，该网盘通常就是 `/`。要访问多个挂载，应在服务端为账号设置合适的共同基础路径及只读权限。

```bash
export OPENLIST_URL="http://127.0.0.1:5244"
export OPENLIST_ROOT="/"
export OPENLIST_TOKEN_FILE="$HOME/.config/openlist-codex/openlist-token"
export OPENLIST_DOWNLOAD_DIR="$HOME/projects/openlist-downloads"
```

以上示例不包含凭据。Codex 插件以插件目录启动 MCP，必须让 Codex 继承配置并显式设置用户下载目录。云端的回环地址指云机器，而非自己的电脑。

## 安装

本地源码安装：

```bash
uv sync --no-cache --locked
uv run --no-cache --locked openlist-codex --check-config
codex plugin marketplace add .
codex plugin add openlist@heavenyygq-openlist
```

公开仓库和版本标签发布成功后，可使用：

```bash
codex plugin marketplace add Heavenyygq/openlist-codex-plugin --ref v0.1.0
codex plugin add openlist@heavenyygq-openlist
```

这是独立 marketplace 安装，不表示已获官方精选收录。`--check-config` 只验证本机配置；`openlist_status` 才会实际请求 OpenList。启动新的 Codex 会话以加载安装的插件。

## 使用

| MCP 工具 | 功能 |
| --- | --- |
| `openlist_status()` | 检查配置及目录读取权限 |
| `openlist_list(path="", page=1, per_page=100)` | 列出相对目录、分页返回文件信息 |
| `openlist_search(query, path="", recursive=True, limit=100, max_entries=2000)` | 有预算限制的文件名匹配，无需 OpenList 搜索索引 |
| `openlist_download(path, filename=None)` | 保存单个文件；拒绝已有目标，返回路径、字节数与 SHA-256 |

例如：“列出 OpenList 的挂载目录”“在 `工作网盘/资料` 中搜索文件名包含 `需求` 的文件”“把 `工作网盘/资料/说明.pdf` 下载到配置的本机目录”。

搜索不是全文搜索，预算用完会返回 `truncated=true`，此时缩小目录或调整预算。下载只接受配置的 OpenList 同源 `/p/` 代理地址，不跟随外部直链或重定向。无法代理、文件大小未知或驱动异常时会明确报错。

本版没有上传、移动、删除、重命名或共享功能。网盘可读，但下载会在用户本机写入新文件。

## 开发与发行

```bash
uv run --no-cache --locked pytest -q
uv run --no-cache --locked ruff check src tests scripts
uv build --no-cache --out-dir dist
```

见 [接入说明](docs/ACCESS.md)、[隐私说明](docs/PRIVACY.md)、[发行说明](docs/PUBLISHING.md) 和 [MIT 许可证](LICENSE)。插件通过 REST 调用独立 OpenList，不复制或分发其驱动代码。
