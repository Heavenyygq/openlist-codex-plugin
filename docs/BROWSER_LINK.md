# OpenList 网页登录关联

双击项目根目录的 **关联OpenList.cmd**，在打开的 OpenList 网页登录。连接器会自动取得该窗口的登录状态，验证后启动 Codex。无需复制 Token，也无需在脚本里输入密码。

## 首次使用

1. 电脑上先安装 Codex CLI 和 Microsoft Edge。Chrome 也可使用。
2. 双击 `关联OpenList.cmd`。OpenList 地址直接按回车会使用 `http://127.0.0.1:5244`；也可输入自己的 OpenList 地址。
3. 在打开的 **OpenList 关联窗口** 登录自己的账号。用户名、密码及两步验证码都在 OpenList 网页中输入。
4. 登录有效后，启动的 Codex 会检查连接并列出根目录。

启动器会注册此目录中的插件源并安装 OpenList 插件。若电脑没有 uv、但已有 Python，则会通过 `python -m pip install --user uv` 安装 uv。首次运行还会下载项目依赖，需要网络。没有 Python 或 uv 时会提示安装，不会静默安装系统 Python。

## 使用 Chrome 或远程地址

在项目根目录的 PowerShell 中运行：

```powershell
& .\scripts\start-browser-link.ps1 -Browser chrome -Url 'https://你的OpenList地址'
```

只打开关联窗口、暂不启动 Codex：

```powershell
& .\scripts\start-browser-link.ps1 -NoLaunchCodex
```

安装依赖后，也可以直接运行：

```powershell
uv run --group browser --locked openlist-codex-link --url http://127.0.0.1:5244 --browser msedge --launch-codex
```

直接运行 Python 入口不会替你注册插件源；首次使用请先运行启动器。连接器还支持 `--session-file` 和 `--profile-dir`，用于自定义关联状态及专用浏览器目录。

## 关联窗口与原有浏览器的关系

关联窗口使用专门的持久化浏览器目录，和日常 Edge/Chrome 的登录状态分开。它不会读取你平时浏览器的个人配置或其他网站的登录凭据。

如果你已经在普通浏览器打开 OpenList，首次仍需在关联窗口登录一次。以后再次使用同一关联目录，在 OpenList 登录状态仍有效时可直接连接。插件不能直接继承任意已打开网页的登录；浏览器隔离了这些存储。

保留关联窗口可以同步换账号、重新登录和退出。退出 OpenList 后，该关联凭据会清除；关闭窗口后不会再观察网页变化，重新运行启动器即可恢复关联。凭据过期、OpenList 重启或修改密码时，可能需要重新登录。

## 保存了什么

连接器只从配置的 OpenList 页面读取 `localStorage` 中的 `token`，并调用 OpenList 的 `/api/me` 验证有效登录。不会读取浏览器保存的密码。

连接器保存的会话文件在 Windows 使用当前用户的 DPAPI 保护；Linux 使用仅当前用户可读写的权限。专用浏览器目录仍会像正常 OpenList 网页一样保留站点存储。因此，请妥善保管关联目录，也不要上传会话文件或浏览器目录到 GitHub。

OpenList 自己的“记住密码”选项会把登录信息保留在浏览器中；不希望网页记住密码时请不要勾选。插件提供的工具仍按 OpenList 中该账号的权限访问目录，建议使用日常读取文件所需的账号和基础路径。

这是社区插件的本地连接方式。GitHub Release 和自定义插件源发布不会自动上架 Codex 官方插件目录。
