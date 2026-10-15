# hermes-auto-build

自动构建 Hermes Agent 自定义镜像，基于官方 [`nousresearch/hermes-agent`](https://hub.docker.com/r/nousresearch/hermes-agent) 上游版本。

## 功能

- 定时检测 Hermes 上游更新，自动构建并推送
- 内置常用 apt 包（`jq unzip diffutils socat zip`）
- 支持手动触发构建

## 使用方法

### 1. Fork 本仓库

### 2. 配置 Secrets

在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：

| Name | 说明 |
|------|------|
| `DOCKERHUB_USERNAME` | Docker Hub 用户名 |
| `DOCKERHUB_TOKEN` | Docker Hub Access Token（不是密码） |

### 3. 修改预装包

编辑 [`Dockerfile`](./Dockerfile) 中的 `apt-get install` 行，按需增删包名。

Python 自定义包维护在 [`requirements-custom.txt`](./requirements-custom.txt)：默认不锁定版本，仅保留插件要求的兼容范围。飞书、Edge TTS、Silk 的必要版本约束直接读取对应上游版本的声明，不在本仓库重复写死。

PM 管理的新镜像会保留原有功能选择，重新解析依赖、构建环境并恢复官方源码绑定和命令入口；旧镜像继续使用其原有安装器。构建时会以普通用户、在源码目录之外检查包导入、Hermes CLI、XLSX 读写、Silk 编解码及中文字体，失败不会发布镜像。

### 4. 启用 Actions

在仓库 Actions 页面启用 Workflow，然后手动触发一次构建。

## 定时任务

每 1 小时自动检查上游更新，有新版本自动构建并推送。

## 输出镜像

```
docker.io/<你的用户名>/hermes-agent:latest
docker.io/<你的用户名>/hermes-agent:<upstream-sha>
```

## 本地测试构建

```bash
docker build -t hermes-agent:custom .
docker run --rm -it \
    -v /home/agent/.hermes:/opt/data \
    hermes-agent:custom chat
```
