# 连接 OpenList 挂载的网盘

使用自己控制的 [OpenList](https://github.com/OpenListTeam/OpenList) 实例，先在其管理界面完成网盘挂载，并验证网页中的列表与文件下载。

创建独立只读普通用户，基础路径设为需要访问的挂载或多个挂载的共同目录。插件配置路径遵循该用户可见的根目录，而非管理员看到的物理挂载路径。将用户的登录 Token 安全保存到本机 `0600` 文件；插件的 API 请求使用原始 Authorization Token，不加 Bearer。

启用存储的 Web 代理和下载签名，保持外部下载代理 URL 为空。插件使用 `/api/fs/list` 和 `/api/fs/get`，仅消费同源 `/p/` 地址，加 `d=1` 请求 OpenList 本机中转。下载请求不携带 OpenList Token、不跟随重定向；签名留在服务内部。

插件不依赖单个网盘的接口。OpenList 驱动的认证、账号风控、套餐限速、权限和服务条款仍需用户管理。不同驱动是否能通过 OpenList 代理下载、是否提供可靠的文件大小和文件信息，应由用户实际验证；无法满足要求时插件会拒绝下载，不会改为携带凭据请求未知域名。

文档及源码参考：[OpenList 文档](https://github.com/OpenListTeam/docs)、[文件接口](https://github.com/OpenListTeam/OpenList/blob/ea10624fb6964a795f4ca607491266bb9af937e6/server/handles/fsread.go)、[代理下载](https://github.com/OpenListTeam/OpenList/blob/ea10624fb6964a795f4ca607491266bb9af937e6/server/handles/down.go)。
