# Windows 安装与兼容处理

面向执行 Agent；读者无需手动运行以下命令。部署前先读[执行约定](README.md)。

## 准备环境

需要安装 Git 和 Python 3.10 或更高版本。下面以 Python 3.11 x64 为例；如果使用其他已安装版本，把 `py -3.11` 换成相应命令。Python 版本要求来自[项目依赖声明](https://github.com/huohuoer/wechat-cli/blob/main/pyproject.toml)。

在 PowerShell 检查：

```powershell
git --version
py -0p
py -3.11 --version
```

本教程统一使用 `D:\Tools\WeChatCLI` 作为示例安装目录。可以换成自己的空目录。已有可用安装时，优先验证并复用；不要直接覆盖旧目录或配置。

Windows 上优先采用 Python 源码安装。项目 README 的 npm 安装方式目前主要附带 macOS arm64 二进制，不宜直接当作 Windows 的通用安装路径。[安装说明](https://github.com/huohuoer/wechat-cli#installation-for-humans)

## 下载并安装

```powershell
New-Item -ItemType Directory -Path 'D:\Tools' -Force | Out-Null
git clone https://github.com/kinghuangze-web/wechat-cli.git 'D:\Tools\WeChatCLI'
if ($LASTEXITCODE -ne 0) { throw '克隆失败，请先处理 Git 错误' }

Set-Location -LiteralPath 'D:\Tools\WeChatCLI'
git remote -v
git rev-parse HEAD

py -3.11 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 虚拟环境创建失败' }

& '.\.venv\Scripts\python.exe' -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }

& '.\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw '依赖检查未通过' }
```

`-e .` 表示从当前源码目录安装。后面应用源码兼容补丁后，命令会使用修改后的代码。独立虚拟环境可以避免把项目依赖装进系统 Python。

在项目目录创建一个 UTF-8 启动入口：

```powershell
@'
@echo off
setlocal
set "PYTHONUTF8=1"
"%~dp0.venv\Scripts\wechat-cli.exe" %*
exit /b %errorlevel%
'@ | Set-Content -LiteralPath '.\wechat-cli.cmd' -Encoding ascii

& '.\wechat-cli.cmd' --version
& '.\wechat-cli.cmd' --help
& '.\wechat-cli.cmd' init --help
```

以后可以直接使用完整路径，不必每次激活虚拟环境，也不必修改系统 PATH：

```powershell
& 'D:\Tools\WeChatCLI\wechat-cli.cmd' --version
```

这一步通过，只能说明程序能够运行。是否能读取微信记录，要继续验证。

## 初始化微信数据访问

打开桌面微信，完成登录，并保持程序运行。在部署所用 Windows 用户的终端中执行：

```powershell
Set-Location -LiteralPath 'D:\Tools\WeChatCLI'
& '.\wechat-cli.cmd' init
```

初始化会查找本机数据目录、提取并验证数据库密钥。默认配置目录为：

```text
%USERPROFILE%\.wechat-cli\
├─ config.json
└─ all_keys.json
```

`config.json` 记录数据位置；`all_keys.json` 保存数据库密钥。查询过程中还可能产生解密缓存，因此这个目录不适合打包分享。[配置实现](https://github.com/huohuoer/wechat-cli/blob/main/wechat_cli/core/config.py)

如果有多个微信账号，明确选择当前准备查询的账号。非交互调用可能自动取第一个候选，不能把默认选择当成账号已确认。自动检测失败时，使用实际账号的 `db_storage` 目录：

```powershell
& '.\wechat-cli.cmd' init --db-dir 'D:\WeChatData\xwechat_files\ACCOUNT_DIR\db_storage'
```

上面的路径是示例，`ACCOUNT_DIR` 需要替换。实际目录可从微信的数据存储设置中确认，再找到该账号下面的 `db_storage`。

如果提示无法打开或读取微信进程，检查终端权限；需要时以管理员身份运行同一个 Windows 账号的终端。能读取内存但没有有效密钥，则继续检查客户端与扫描器的兼容性。

已有配置和密钥时，`init` 默认会报告“已初始化”并直接返回。这不代表它重新验证了密钥；下一节的真实查询才是检查。不要为此习惯性加 `--force`，该选项会重新提取。[初始化实现](https://github.com/huohuoer/wechat-cli/blob/main/wechat_cli/commands/init.py)

初始化输出可能包含敏感字段。保持输出在本机，分享错误时只保留错误类型、退出码和数量，先遮掉密钥与个人目录。

## 遇到 Windows 4.1.x 扫描不到密钥

一次实际部署曾遇到这种现象：微信已经登录，进程内存可以读取，但旧扫描器始终找不到有效密钥。继续登录和重复执行同一命令没有解决问题。

可检查上游的 [PR #22：支持微信 4.1.x 版本密钥提取](https://github.com/huohuoer/wechat-cli/pull/22)。它增加了 `Config.Cipher` 结构定位与 XOR 解码，再用数据库首页校验候选密钥。截至本文核对日期，该 PR 仍未合并，普通更新主分支不一定包含修复。

本教程附有一个可选的 `windows-config-cipher.patch`，从历史上通过实际查询验证的本地修复中提取，**只修改 `wechat_cli/keys/scanner_windows.py`**：

- 参考 PR #22 的提交 `acfcd609c1d2fb75c67a0f13339eb3eb1810d55e`。
- 加入 Config.Cipher 扫描，并保留旧扫描回退。
- 沿用原项目 SQLCipher 4 的 HMAC-SHA512 校验。
- 进程句柄在 `finally` 中关闭，避免成功路径重复关闭。

补丁基于上游提交 `a3789232d4f79bf0b30634d9dadbce71e4acd601`。这是社区方案的局部适配，不代表上游正式发布了新的兼容版本，也不能保证所有后续微信版本适用。

### 应用随附补丁

如果常规初始化和查询已成功，跳过本节。若需要补丁，本配套仓库的 `docs/technical` 目录已经包含补丁与测试。以下在示例克隆目录内操作；已有其他安装时，把 `$guideDir` 改为这份技术附件的实际目录。

```powershell
$guideDir = 'D:\Tools\WeChatCLI\docs\technical'
Set-Location -LiteralPath 'D:\Tools\WeChatCLI'

git status --short
git apply --check (Join-Path $guideDir 'windows-config-cipher.patch')
if ($LASTEXITCODE -ne 0) { throw '补丁与源码不匹配，停止应用并核对版本' }

$backupDir = Join-Path (Get-Location).Path ('backup-before-config-cipher-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath '.\wechat_cli\keys\scanner_windows.py' -Destination $backupDir

git apply (Join-Path $guideDir 'windows-config-cipher.patch')
if ($LASTEXITCODE -ne 0) { throw '应用补丁失败' }
```

检查 `git status` 中是否有自己的扫描器改动。如果有，先核对差异，不要用教程覆盖已有修复。补丁检查不通过时，不要使用忽略上下文或强制覆盖的方式套入新版本。

若需要完全复现补丁基线，可在**另一个新目录**克隆仓库并检出上述固定提交，按安装章节重新创建虚拟环境。不要在有个人改动的现有目录里强制切换版本。

运行随附的合成检查：

```powershell
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest discover -s $guideDir -p 'test_windows_config_cipher.py' -v
if ($LASTEXITCODE -ne 0) { throw '补丁检查未通过，先处理失败项' }

git diff --check
& '.\wechat-cli.cmd' init
```

四项检查覆盖 XOR 解码、异常 blob 拒绝、HMAC 损坏拒绝，以及合成指针结构的解析。检查使用人工构造的数据，不会读取微信进程；检查通过后仍需进行真实初始化和查询。若已有失效配置导致 `init` 跳过扫描，先在本机备份原配置和密钥，再根据明确原因决定是否用 `init --force` 重新提取。

回退时，用本机备份的 `scanner_windows.py` 恢复原文件；或在没有后续扫描器改动时，用 `git apply -R --check` 检查反向补丁，再用 `git apply -R` 撤销。保留已有有效配置及密钥，不要删除微信原始数据。

## 用真实查询验收

先检查最近会话，再查少量联系人，最后读取一个目标会话的历史消息：

```powershell
$cli = 'D:\Tools\WeChatCLI\wechat-cli.cmd'

& $cli sessions --limit 3 --format json
& $cli contacts --query '示例联系人' --limit 3 --format json
& $cli history '示例群聊' --limit 1 --format json
```

`示例联系人` 和 `示例群聊` 都要换成自己的查询对象。如果名称重复，先搜索联系人，再用实际返回的 `username` 定位会话。真实标识只在本机使用。

验收时逐个检查命令，保存该次调用的退出码，并解析 JSON：

| 检查 | 通过条件 |
| --- | --- |
| 程序运行 | `--version` 正常，依赖检查通过 |
| 会话查询 | 退出码为 0，JSON 可解析，已有会话账号返回记录 |
| 联系人查询 | 退出码为 0，能找到一个确定存在的联系人 |
| 历史消息 | 对确定有本地消息的目标，返回至少一条记录，`failures` 为 `null` 或空列表 |

`history.count` 表示本次返回数量。即使退出码为 0，仍须检查 `failures`；部分数据库查询失败时，不能把返回内容当成完整历史。[历史查询输出结构](https://github.com/huohuoer/wechat-cli/blob/main/wechat_cli/commands/history.py)

只想查看验收数量而不在终端显示正文，可以这样执行历史查询：

```powershell
$raw = & $cli history '示例群聊' --limit 1 --format json
$queryExitCode = $LASTEXITCODE
if ($queryExitCode -ne 0) { throw "查询失败，退出码：$queryExitCode" }
$result = ($raw -join "`n") | ConvertFrom-Json
if ($result.failures) { throw '存在查询失败项，尚未通过验收' }
if ($result.count -lt 1) { throw '该目标未返回消息，请检查对象与本地记录' }
[pscustomobject]@{ exit_code = $queryExitCode; records = $result.count; failures = 0 }
```

这段只减少终端展示，原始结果仍进入当前 PowerShell 进程内存；不要把它理解成已经对消息做了匿名化。



手机任务入口见 [Grok Bot 接入说明](GROK_WECHAT.md)。本目录中的测试数据全部人工构造；密钥、配置和聊天记录不在仓库中。
