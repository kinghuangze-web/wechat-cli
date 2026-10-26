# 直接交给 Grok Bot 的 Windows 接收端迁移提示词

适用前提：Grok Bot 已有可用的本机执行能力，原微信接收与回复已经跑通。`ListMachines`、`CopyFromBox` 是原 Grok Bot 环境中的工具名；没有这些工具或等价能力时，应报告缺项，不能声称已经执行。

用户只需复制下面整段，回到原来配置微信助手的 Grok Bot 聊天发送。部署、文件交接和切换均交给 Grok Bot 执行，必要的扫码或授权由用户配合。WorkBuddy 仍可作为正文 wechat-cli 的部署示例，但迁移不要求用户在两个 Agent 之间中转。

```text
请把你的微信 ClawBot 收消息程序（轮询 getupdates 并转发到你 webhook routine 的那个 bridge）从你自己的电脑搬到我的 Windows 电脑上跑，回复仍由你那边发。原因：你的电脑一重启 bridge 就停，而且没人重启它。

要求：
1. 先读你自己的 bridge 代码、配置和状态文件，弄清依赖、环境变量、游标文件（get_updates_buf）、context_token 存在哪、日志在哪。用 ListMachines 找到我的 Windows 电脑，在那上面确认 Python 3 和 pythonw 可用。
2. 在我电脑上建一个目录（比如 D:\wechat-bridge），用 CopyFromBox 放进 bridge 脚本、依赖模块、配置和状态文件。webhook 地址和 key 直接从你的环境变量写进那个目录下的 secrets.env，任何输出、日志、回复里都不能出现它们的值，只能核对长度。不要打开或输出任何与微信本地数据库密钥有关的文件。
3. 写一个 run_bridge.pyw 启动器：用 pythonw 无窗口运行，日志用 UTF-8 写到 logs\bridge.log，用文件锁加 PID 文件保证只跑一份，启动时读取 secrets.env。能不改原 bridge 就不改，Windows 不兼容的地方做最小改动。
4. 用任务计划程序建一个计划任务：用户登录时启动、每 10 分钟重复一次当看门狗、已在运行就跳过、失败自动重试、不限运行时长、用电池也照常运行。
5. 切换顺序：先停掉你电脑上的 bridge，再把游标文件重新复制一遍，然后马上启动我电脑上的任务。两边绝不能同时轮询。你电脑上不要留任何会自动拉起旧 bridge 的东西，旧代码保留备用。
6. context_token：我电脑上的 bridge 没法再写你那边的 context_tokens.json，所以每次回复都改为使用 webhook 载荷里带来的 context_token（比如让回复脚本读取环境变量 WECHAT_CONTEXT_TOKEN，有值就先存再发）。同时更新你的 webhook routine 提示词：回复时必须传入本次载荷里的 context_token；不要再在你电脑上启动 bridge。
7. 验证：计划任务状态是 Running，PID 和锁文件对得上，日志里有 bridge started 而且没有报错；再手动启动一次第二份，确认它会被锁挡住直接退出。最后等我发一条微信，确认收到并且回复成功。
8. 任何一步连续失败两次就停下来告诉我卡在哪。如果此时已经停掉了你那边的 bridge，需要回滚时，必须先停止 Windows 接收端并确认已停止，再恢复你那边的旧 bridge，尽量恢复原连接。如果不能确认 Windows 端已经停止，不要贸然启动旧端，说明当前状态；两边绝不能同时轮询。
9. 做完用中文告诉我：做了哪些事、计划任务名、验证结果、怎么查看运行状态、怎么重启或停止、电脑睡眠或关机时会怎样，以及出现 -14 需要重新扫码时，登录后要把新的 credentials.json 复制到我电脑的 state 目录、并删掉其中的 expired 文件。所有输出里都不能带任何 ID、token、key 或聊天内容。
```

本提示词来自用户提供的 Grok Bot 返回内容。第 8 条补充了“先确认 Windows 接收端停止，再恢复旧端”的回滚条件，避免恢复时出现两个接收端同时轮询。详细实现见 [WINDOWS_BRIDGE.md](WINDOWS_BRIDGE.md)。技术步骤由具备权限的 Grok Bot 执行，本次仅整理文档，没有执行迁移或读取任何凭据。
