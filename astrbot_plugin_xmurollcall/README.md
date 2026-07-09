# XMU Rollcall Bot — AstrBot Plugin

厦门大学 TronClass 自动签到监控插件。通过聊天命令管理监控、WebUI 配置参数、后台轮询签到，检测到新签到时自动应答并发送通知。

## 功能

- **自动签到**：支持数字签到（API 获取 / 暴力破解 0000-9999）、雷达签到（GPS 三角定位）
- **后台监控**：持续轮询 TronClass API，检测新签到并即时响应
- **聊天通知**：检测到签到 / 签到成功时推送消息到指定会话
- **时间窗口**：可配置监控时段，在非上课时间自动休眠
- **Session 管理**：自动恢复缓存会话，过期自动重登
- **WebUI 配置**：所有参数均可在 AstrBot 管理面板中配置

## 安装

通过 WebUI 安装

依赖会自动安装：`requests`, `pycryptodome`, `aiohttp`

## 配置

在 AstrBot WebUI 插件管理面板中配置：

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `username` | string | — | 学号/工号 |
| `password` | string | — | 统一身份认证密码 |
| `enabled` | bool | false | 加载插件后自动开始监控 |
| `interval` | int | 3 | 轮询间隔（秒） |
| `random_delay_max` | float | 5.0 | 签到前随机延迟上限（秒），0=不延迟 |
| `number_code_method` | int | 1 | 1=API获取数字码，2=暴力破解(0000-9999) |
| `monitor_start_hour` | int | 0 | （默认）每天监控开始时间。若已配置 schedule 则忽略 |
| `monitor_end_hour` | int | 23 | （默认）每天监控结束时间。若已配置 schedule 则忽略 |
| `schedule` | text | "" | 按周几的监控时间表 (JSON数组)。配置后忽略上方 start_hour/end_hour |
| `notify_chats` | list | [] | 通知目标会话 ID 列表，留空则通知到触发启动命令的会话 |

### schedule 格式

```json
[
  {"days": [0,1,2,3,4], "start": 8, "end": 12},
  {"days": [0,1,2,3,4], "start": 14, "end": 18},
  {"days": [5], "start": 9, "end": 11}
]
```

- `days`: 星期几，`0`=周一 … `6`=周日
- `start` / `end`: 小时 (0-23)，支持跨夜如 `{"start":22, "end":2}`
- 留空则使用 `monitor_start_hour` / `monitor_end_hour`（全天统一）

## 命令

| 命令 | 说明 |
|---|---|
| `/rollcall-start` | 启动签到监控 |
| `/rollcall-stop` | 停止签到监控 |
| `/rollcall-status` | 查看运行状态 |
| `/rollcall-config` | 查看当前配置 |
| `/rollcall-test` | 测试登录 |

## 使用示例

```
# 1. 测试登录
/rollcall-test
→ Login successful! Welcome, ***.

# 2. 启动监控
/rollcall-start
→ Monitoring started.
  Account: ******
  Interval: 3s

# 3. 查看状态
/rollcall-status
→ Status: RUNNING
  Running time: 2h 15m 30s
  Query count: 2706
  Time window: 08:00 - 22:00
  In window: Yes

# 4. 查看配置
/rollcall-config
→ Username: ******
  Interval: 3s
  Number code method: API
  Time window: 08:00 - 22:00

# 5. 停止监控
/rollcall-stop
→ Monitoring stopped.
  Total queries: 5412
  Running time: 6h 0m 0s
```

## 通知示例

当检测到新签到时，插件会自动推送：

```
🔔 New rollcall!
Course: 数据结构
Teacher: 信息学院 张老师
Type: Number

API number code answering for '数据结构'
```

## 工作原理

```
OIDC 登录 (xmulogin)
  └→ c-identity.xmu.edu.cn (Keycloak)
      └→ ids.xmu.edu.cn (统一身份认证)
          └→ lnt.xmu.edu.cn (TronClass session)

后台监控循环
  └→ GET /api/radar/rollcalls (每 N 秒)
      ├→ 对比上次数据，检测新签到
      ├→ 数字签到 → /api/rollcall/{id}/answer_number_rollcall
      └→ 雷达签到 → /api/rollcall/{id}/answer (GPS定位)
```

## License

[MIT](../LICENSE)
