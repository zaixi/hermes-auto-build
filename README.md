# hermes-auto-build

自动构建 Hermes Agent 自定义镜像，基于官方 [`nousresearch/hermes-agent`](https://hub.docker.com/r/nousresearch/hermes-agent) 上游版本。

## 功能

- 定时检测 Hermes 最新稳定版，自动构建并推送（最低基座 v0.23.2）
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

只支持 v0.23.2 及后续稳定版的 PM 构建协议；不再自动补建历史 release 或日期版本。已有旧版镜像保留，不删除。`documents`、`feishu`、`edge-tts`、`silk` 均采用对应上游版本的 extra 声明；`openpyxl` 不重复列入自定义 extra。PATH 和登录 shell 完全沿用官方设置，不把 baked venv 放到 Hermes 启动 shim 前面。构建会同时检查普通 shell、登录 shell 的命令顺序和 pandas/openpyxl 导入。

镜像保留原有功能选择，通过官方 PM 重新解析依赖、构建环境并恢复官方源码绑定和命令入口；不再维护旧 uv 安装器或读取旧 lazy-deps allowlist。缺失的锁定运行工具使用官方 `pm.prepare_tools(..., out=/opt/hermes/tools)` 写入镜像 store；不能使用 sealed payload 的运行期 `ensure()` 替代，因为它可能把工具安装到构建用户的数据目录，换 profile 或挂载数据卷后就不可见。

构建时会以普通用户、在源码目录之外检查包导入、Hermes CLI、XLSX 读写、Silk 编解码、中文字体和完整运行时 drift，失败不会发布镜像。另有强制真实工具回归：复制隔离 payload、仅准备已有 node、执行真实的 pnpm 构建期安装，然后让构建数据目录不可见，在全新 HOME 下验证锁定 entry 和实际版本；物理移走 entry 的负对照仍必须被拒绝。这项回归只替代耗时的应用环境构建/组装，不 mock PM 工具安装；实际完整环境仍由前一项镜像 smoke 验收。

### 4. 启用 Actions

在仓库 Actions 页面启用 Workflow，然后手动触发一次构建。

## 定时任务

每 1 小时自动检查最新稳定版，仅当该版本尚未发布自定义镜像时构建；手动 `force=true` 可重建最新实际版本。无更新时不运行构建相关测试。构建串行执行，不取消已经开始的发布；只有完整构建及验收成功后才同时发布版本 tag 和 `latest`。

## 输出镜像

```
docker.io/<你的用户名>/hermes-agent:latest
docker.io/<你的用户名>/hermes-agent:vX.Y.Z
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

这是本仓库的下游兼容修复，不宣称已有官方补丁。构建入口
`scripts/ensure_sealed_runtime_drift.py` 先对官方原样源码执行行为回归，**不先套文本补丁**：
- 行为全部通过：不修改源码，即使官方修复方式与本仓库补丁文本不同。
- 行为断言失败：仅对已审计的实现应用补丁，再跑同一套行为回归；失败则恢复源码并中止构建。
- 测试导入/API 报错、跳过、空测试集、超时或未知且行为不正确的实现：中止构建，不当成可修复缺陷放行。

补丁适配器本身仍精确识别已审计代码、重复执行幂等；旧版无 PM 镜像不在支持范围。
行为回归继续验证真实锁文件、extras、环境缺失、运行期插件变更及工具漂移不被隐藏。
最终普通用户 smoke 也会调用真正的 `check_runtime`，不再仅检查 `--version`。

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
