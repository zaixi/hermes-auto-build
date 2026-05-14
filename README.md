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
