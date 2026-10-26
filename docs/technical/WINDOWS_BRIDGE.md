# 微信转发程序（bridge）从 Grok Bot 云端电脑迁到 Windows：实现说明

> 给 WorkBuddy 或其他部署 Agent 的迁移参考。前提：读者已经在 Grok Bot 云端电脑（下称“盒子”）上跑通了 bridge（扫码登录、长轮询、转发到 webhook routine、用 `reply` / `reply-image` 回复）。本文只讲迁移。
> 已脱敏：路径统一写成 `D:\wechat-bridge`、`C:\Python311\`，ID/令牌/密钥/地址均为占位符。

## 1. 为什么要迁
- 盒子重启后 bridge 就停了：没有开机自启，webhook 环境变量也只在新 shell 里可见，每次都要人工 `./start.sh`。停掉期间微信消息没人转发，Grok Bot 也就不回。
- 用户自己的 Windows 电脑可以用“任务计划程序”做到登录自启和掉线自动拉起。整个链路只需要出站 HTTPS，家用网络也能跑，不用开端口。
- 迁移后的分工：**Windows 只负责收消息（轮询 + 转发 webhook）**；**回复仍由盒子发出**（`reply` / `reply-image`），不经过 Windows。

## 2. 前提
- Windows 上装好 Python 3（实测 3.11），带 `pythonw.exe`（官方安装包自带，它运行时不弹控制台窗口）。
- bridge 只用标准库，Windows 端不需要 pip 安装任何东西（segno、cryptography 只有盒子上的 login / reply-image 才用）。

## 3. 拷贝哪些文件、放到哪里
目标目录 `D:\wechat-bridge`：

| 文件 | 来源 | 说明 |
|---|---|---|
| `bridge.py` | 盒子 `bridge`（加 `.py` 后缀以便 import） | 轮询主程序，逻辑不改 |
| `ilink.py` | 盒子 `ilink.py` | 公共函数 |
| `run_bridge.pyw` | 新写 | Windows 启动器（见第 4 节） |
| `config` | 盒子 `config` | `bound_user_id=<BOUND_USER_ID>` |
| `state\credentials.json` | 盒子 `state/credentials.json` | 微信登录凭证（机密） |
| `state\get_updates_buf` | 盒子 `state/get_updates_buf` | getupdates 游标；**停掉盒子轮询后再拷一次**（见第 6 节） |
| `state\context_tokens.json` | 盒子 | 可选，bridge 会自己更新 |
| `secrets.env` | 由环境变量直接生成 | webhook 地址和密钥（机密） |

`secrets.env` 的格式（占位符）：
```
WECHAT_ROUTINE_WEBHOOK_URL=<WEBHOOK_URL>
WECHAT_ROUTINE_WEBHOOK_KEY=<WEBHOOK_KEY>
```
生成方式：在盒子上直接把环境变量写进文件，**全程不 echo、不打印**，然后打包传到 Windows：
```bash
umask 077
printf 'WECHAT_ROUTINE_WEBHOOK_URL=%s\nWECHAT_ROUTINE_WEBHOOK_KEY=%s\n' \
  "$WECHAT_ROUTINE_WEBHOOK_URL" "$WECHAT_ROUTINE_WEBHOOK_KEY" > winpkg/secrets.env
```
（webhook 地址和密钥最初是通过 Grok Bot 的加密输入框录入为环境变量的，从未在聊天里出现过。）

## 4. 启动器 run_bridge.pyw
作用：① 日志用 UTF-8 写入 `logs\bridge.log`（pythonw 没有控制台，stdout/stderr 必须重定向）；② 用 `msvcrt.locking` 加锁保证单实例，并写 PID 文件；③ 读取 `secrets.env` 放进环境变量；④ 调用 `bridge.main()`。

```python
"""Windows launcher: loads secrets.env, single-instance lock, logs to logs\bridge.log, runs bridge.main()."""
import os, sys, msvcrt
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT); sys.path.insert(0, ROOT)
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
log = open(os.path.join(ROOT, "logs", "bridge.log"), "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log
lockf = open(os.path.join(ROOT, "state", "bridge.lock"), "a+")
try:
    lockf.seek(0); msvcrt.locking(lockf.fileno(), msvcrt.LK_NBLCK, 1)
except OSError:
    sys.exit(0)  # another instance is running
with open(os.path.join(ROOT, "state", "bridge.pid"), "w") as f: f.write(str(os.getpid()))
try:
    for line in open(os.path.join(ROOT, "secrets.env"), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
except FileNotFoundError:
    print("FATAL: secrets.env missing", flush=True)
import bridge
sys.exit(bridge.main())
```
要点：
- 锁是 OS 级文件锁，进程退出（包括崩溃）后自动释放，不会因为残留的 PID 文件“假占用”。PID 文件只用于查看。
- 第二个实例拿不到锁就静默 `exit(0)`，所以计划任务可以放心地反复触发。
- `bridge.main()` 遇到 `-14` 会写 `state\expired` 并返回 2；之后有 `expired` 文件时启动会直接退出，不会反复撞服务端。

## 5. 计划任务 WeChatBridge
从 Windows 只读查询到的实际定义：
- 动作：`C:\Python311\pythonw.exe "D:\wechat-bridge\run_bridge.pyw"`，工作目录 `D:\wechat-bridge`
- 触发器 1：用户登录时（At logon，当前用户）
- 触发器 2：一次性时间触发器，从创建时刻起**每 10 分钟重复、无限期**，充当看门狗
- 设置：`MultipleInstances = IgnoreNew`（已在运行就忽略新实例）；`RestartCount = 999`，`RestartInterval = 1 分钟`（异常退出后重试）；`ExecutionTimeLimit = 0`（不限时长）；用电池时也启动、不停止；`StartWhenAvailable = True`（错过的触发补跑）
- 身份：当前用户，交互式登录（Interactive），普通权限（Limited），不需要管理员、不存密码

与之等价的 PowerShell 注册命令（按上述定义整理，用户名、路径为占位符）：
```powershell
$py  = "C:\Python311\pythonw.exe"
$dir = "D:\wechat-bridge"
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$dir\run_bridge.pyw`"" -WorkingDirectory $dir
$tLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName WeChatBridge -Action $action -Trigger $tLogon,$tRepeat -Settings $settings -Principal $principal
```
说明：
- 看门狗靠两层去重：计划任务的 `IgnoreNew`，加上启动器的文件锁。
- 任务的“上次运行结果”曾显示 `0x800710E0`。不要仅凭这个状态码认定正常或故障；结合是否已有目标进程、当前日志、任务实例与真实消息结果判断。当前部署使用 IgnoreNew，重复触发可能被忽略。
- 先手动跑一次 `pythonw run_bridge.pyw`，确认日志出现 `bridge started` 再注册任务。

## 6. 切换顺序（不能两边同时轮询）
两个 bridge 同时长轮询会互相抢消息、抢游标，导致漏消息或重复转发。顺序：
1. 盒子：`./stop.sh`，再 `./status.sh` 确认 `bridge: STOPPED`。
2. 盒子：把最新的 `state/get_updates_buf` **再拷一次**到 Windows 的 `state\`（停机前后游标可能又前进了，用旧游标会重复收消息）。
3. Windows：`Start-ScheduledTask WeChatBridge`，确认日志出现 `bridge started`。
4. 盒子 README 顶部写明：bridge 已迁到 Windows，**盒子上不要再执行 ./start.sh**；盒子只负责 `reply` / `reply-image`。

## 7. context_token 的变化
问题：sendmessage 必须带绑定用户最新的 `context_token`。以前盒子上的 bridge 收消息时顺手写进盒子的 `state/context_tokens.json`，`reply` 从那里读。迁移后 Windows 轮询写的是 Windows 本地文件，盒子上的文件不再更新，于是用旧 token 回复失败（`-2`，“prepare failed”）。

解决：bridge 本来就把 `context_token` 放进 webhook 载荷：
```json
{"from_user_id":"<BOUND_USER_ID>","text":"...","context_token":"<CONTEXT_TOKEN>","message_id":"<MSG_ID>"}
```
盒子这边的改动：
1. `ilink.py` 新增 `current_ctx()`，`reply` 和 `reply-image` 都改成用它取 token：
   ```python
   def current_ctx(bound):
       """If env WECHAT_CONTEXT_TOKEN is set (taken from the webhook payload's
       context_token), save it to CTX_FILE first."""
       ctx = load_json(CTX_FILE, {})
       t = (os.environ.get("WECHAT_CONTEXT_TOKEN") or "").strip()
       if t and bound and ctx.get(bound) != t:
           ctx[bound] = t; write_private(CTX_FILE, json.dumps(ctx))
       return ctx.get(bound)
   ```
   在 `reply` / `reply-image` 中：`ctx = I.current_ctx(bound)`；拿不到就报错 `no context_token for bound user (user must message the bot first)`。
2. 新增 `set-context` 脚本，单独保存 token：
   ```python
   b = I.bound_user(); c = I.load_json(I.CTX_FILE, {}); c[b] = sys.argv[1].strip()
   I.write_private(I.CTX_FILE, json.dumps(c)); print("OK context_token saved")
   ```
   token 写入后会持久化，所以同一轮里后续的 `reply-image` 不用再传。

routine 提示词改动的那几行（脱敏）：
```text
- 回复：cd /workspace/wechat-bridge && WECHAT_CONTEXT_TOKEN='<payload.context_token>' ./reply "纯文本回复"
  （或先执行 ./set-context '<payload.context_token>'，再 ./reply / ./reply-image）
- 收消息的 bridge 运行在用户的 Windows 电脑上，不要在盒子上执行 ./start.sh。
- 如果出现 -14：告诉用户要重新扫码，按“重新登录”流程把新凭证放到 Windows。
```

## 8. 验证
```powershell
Get-ScheduledTask WeChatBridge | Select TaskName,State           # 应为 Running
Get-Content D:\wechat-bridge\state\bridge.pid                     # PID
Get-Process -Id (Get-Content D:\wechat-bridge\state\bridge.pid)   # 应为 pythonw
Get-Content D:\wechat-bridge\logs\bridge.log -Tail 20 -Encoding UTF8
```
- 日志应有 `bridge started base=...`。
- 锁测试：运行中再手动执行一次 `pythonw run_bridge.pyw`（或 `Start-ScheduledTask`），应当只有一个 bridge 进程，日志里没有第二条 `bridge started`。
- 真实消息测试：在微信里给 ClawBot 发一句话，日志出现 `FORWARDED message_id=... http=200`，几秒内收到 Grok Bot 的微信回复（同时验证了 context_token 的传递）。
- 盒子：`./status.sh` 应为 `bridge: STOPPED`。

## 9. 日常运维
```powershell
# 状态 / 日志
Get-ScheduledTask WeChatBridge | Select TaskName,State
Get-Process pythonw -ErrorAction SilentlyContinue
Get-Content D:\wechat-bridge\logs\bridge.log -Tail 20 -Encoding UTF8
# 停止
Stop-ScheduledTask WeChatBridge
# 如仍有本任务进程，仅在核对其命令行属于 run_bridge.pyw 后，按本任务 PID 停止；不要结束所有 pythonw 进程。
# 启动 / 重启
Start-ScheduledTask WeChatBridge
# 长期停用 / 恢复（只 Stop 的话看门狗 10 分钟内会再拉起）
Disable-ScheduledTask WeChatBridge
Enable-ScheduledTask WeChatBridge
```
- 没消息时日志不刷新，属于正常。
- 手动结束进程前，先用 PID 查询命令行并确认属于本部署的 run_bridge.pyw，防止 PID 文件残留或 PID 已被其他进程复用。不要批量结束 pythonw。长期停用必须禁用本计划任务，否则重复触发会重新启动。
- **睡眠 / 关机**：期间本地接收程序无法轮询，不能保证微信收到回复。当前任务在用户登录后启动；唤醒后的恢复还取决于网络、登录会话、凭证和计划任务。每 10 分钟重复触发是检查间隔，不是无条件的最长恢复时间。离线消息可能凭游标补收，但不承诺完整补齐；必要时让用户发送新消息。电源设置由用户按需要决定，Agent 不擅自更改。
- **-14 重新登录**：日志出现 `CREDENTIAL_EXPIRED: rescan needed (errcode -14)`，程序停止并生成 `state\expired`。
  1. 在盒子上执行 `nohup ./login > logs/login.log 2>&1 &`，把二维码发给用户扫码（需要时写入验证码），等到 `LOGIN_OK`。
  2. 把盒子上新的 `state/credentials.json` 安全地复制到 Windows 的 `D:\wechat-bridge\state\`。
  3. 删除 Windows 的 `state\expired`：`Remove-Item D:\wechat-bridge\state\expired`。
  4. `Start-ScheduledTask WeChatBridge`，确认 `bridge started`。
  注意：盒子上跑 login 不会启动盒子上的 bridge，不要接着执行 `./start.sh`。

## 10. 坑：Windows 中文乱码
- PowerShell 5 的 `Get-Content` 默认按系统 ANSI 代码页（GBK）读文件，UTF-8 的日志和说明文档会显示成乱码。读取时一律加 `-Encoding UTF8`。
- 启动器里日志文件以 `encoding="utf-8"` 打开，避免 pythonw 写中文时用错编码或报错。
- 在控制台里直接跑 Python 时，可以先 `chcp 65001`，或设置 `PYTHONIOENCODING=utf-8`。
- 说明文档、`secrets.env`、`config` 都保存为 UTF-8。

## 11. 安全
- `secrets.env` 和 `state\credentials.json` 是机密：不要发给别人、上传网盘或提交 Git。
- 迁移用的临时打包文件（含 secrets.env）用完就删。
- 怀疑泄露：在 Grok Bot 里更换 webhook 密钥（重写 secrets.env 后重启任务），并重新扫码换凭证。


## 文档与验证范围

本说明由用户提供的脱敏迁移实现整理。它只迁移接收与转发：Windows 轮询并转发到既有 Grok Bot routine，回复仍由原 Grok Bot 执行环境发送。不要把它称为全部本地化，也不要把 bridge 与 wechat-cli 当成同一个程序。迁移不会自动赋予 Grok Bot 调用本机 wechat-cli 的能力，需保留并验证原有本机执行工具。

这是迁移已有部署的说明，不包含 bridge、ilink 和 reply 的完整程序包。需要从用户自己的既有部署准备文件；不能假设新读者仅复制此文就有可运行的收发系统。

接收程序的状态与微信凭证、webhook 密钥属于私有运行数据。程序包与私密状态分别交接；私密状态通过已有受控方式直接传至目标，不进入公开仓库、聊天明文或公开下载链接。用完清理本次含凭据的临时迁移包，保留约定回退备份。

启动器应先确认 state 目录存在；单实例检查不能只相信 PID 文件。回复上下文要按消息携带的 context_token 传递，避免多条任务并行时串用。新的凭证未准备好前，不删除 expired 标记反复尝试。

切换后重新检查云端接收已停止、本地只有一份接收进程、文本回复与图片回复能实际收到、wechat-cli 仍可通过本机执行工具调用。任务注册成功或 webhook HTTP 200 均不能单独当作收发验收。

本次只更新教程及技术说明，没有执行迁移、修改计划任务、传输凭据或重新测试微信。文中任务配置来自用户提供的实现记录，读者需在自己的环境逐项验证。
