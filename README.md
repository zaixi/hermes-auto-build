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

### Sealed PM 启动诊断回归

`pm.build_env --record-selection` 为镜像记录的是 `plugin_dirs=[]` 的基础环境。
v0.22.1 的被动启动检查却默认把各 profile 的插件目录加入 stamp，导致仅挂载
运行期插件就报告 `install out of sync`，即使镜像的锁文件、extras、Python 均未改变。

构建时的 `patches/apply_sealed_runtime_drift.py` 仅调整 `pm.install.drift`：
有效 sealed 镜像且没有已提交的运行期 venv selection 时，检查插件为空的基础 stamp；
一旦存在运行期 selection，仍检查完整插件集合。显式 `venv_is_current`、插件准入、
sync/repair 不改；真实锁文件、extras、环境缺失及工具漂移仍报错。
这不是“插件依赖已满足”的保证：插件必须经过 PM 准入，不能靠消除基础镜像告警代替。

这是本仓库的下游兼容修复，不宣称已有官方补丁。仅识别已审计的上游代码，重复执行幂等；
遇到未知上游实现会中止构建，需人工复核。旧版无 PM 镜像跳过。
构建中会执行行为回归，最终普通用户 smoke 也会调用真正的 `check_runtime`，不再仅检查 `--version`。

在已有完整 Hermes 源码及运行依赖的环境中运行（源码只读，补丁先在内存或临时目录应用）：

```bash
HERMES_SOURCE_ROOT=/opt/hermes PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s tests -p test_sealed_runtime_drift.py -v
```

只修改仓库并运行测试不会修复当前容器；必须另行批准构建和部署新镜像。

## 本地测试构建

```bash
docker build -t hermes-agent:custom .
docker run --rm -it \
    -v /home/agent/.hermes:/opt/data \
    hermes-agent:custom chat
```
