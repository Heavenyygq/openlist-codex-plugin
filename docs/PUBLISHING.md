# 发行与官方精选收录

目标公开仓库为 `Heavenyygq/openlist-codex-plugin`，版本为 `v0.1.2` 社区预发布版。仓库和标签实际发布成功后，用户可执行：

```bash
codex plugin marketplace add Heavenyygq/openlist-codex-plugin --ref v0.1.2
codex plugin add openlist@heavenyygq-openlist
```

通用版使用独立 marketplace 名 `heavenyygq-openlist`，与夸克专用版 `heavenyygq` 避免注册冲突，两个插件可以同时安装。每个插件包含自己的锁定运行环境，不依赖另一个插件的缓存目录。

本项目采用 [OpenAI 官方插件仓库](https://github.com/openai/plugins) 的原生插件结构：`.codex-plugin/plugin.json`、`.mcp.json`、`skills/`，以及独立 marketplace 的 `.agents/plugins/marketplace.json`。相对 `cwd` 解析为插件目录，不依赖未验证的环境变量替换。

GitHub 公开仓库和独立 marketplace 发布不等于进入 Codex 官方精选库。官方公共目录提交与独立 GitHub marketplace 分发是不同流程；本地 stdio MCP 不能直接视为公共目录上架就绪。当前没有获得官方收录或任何网盘服务商背书。

发行前检查锁定安装、测试、清单识别、源码包完整性及凭据排除。发行包为完整插件 ZIP、源码 tar.gz、Python wheel 和 SHA256SUMS；wheel 本身不注册 Codex 插件。预发布版应明确记录已验证的 OpenList 版本和存储类型，不能把统一 API 支持写成每个网盘均已实测。
