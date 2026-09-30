# OpenList Codex 插件 0.1.0 — 社区预发布

通过用户自己的 OpenList 统一浏览、搜索和下载已挂载的网盘或文件存储，不限夸克网盘。

仓库和标签发布成功后安装：

```bash
codex plugin marketplace add Heavenyygq/openlist-codex-plugin --ref v0.1.0
codex plugin add openlist@heavenyygq-openlist
```

需要 Python 3.11+、uv，以及自己的 OpenList 只读账号 Token。参见 README 配置 HTTPS 地址、用户可见根路径与本机下载目录。不要提交真实凭据或私密资料。

插件通过统一文件 API 工作；不同网盘的登录、套餐限制、会话和 Web 代理下载由 OpenList 管理。已验证的存储类型见 `docs/VALIDATION.md`，不能视为所有网盘均已实测。本项目非 OpenList 或 OpenAI 官方产品，尚未进入 Codex 官方精选库。

附件包含完整插件 ZIP、源码发行包、Python wheel 和 SHA256SUMS。单独安装 wheel 不会注册 Codex 插件。
