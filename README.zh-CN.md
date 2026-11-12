# claude-worklog-dida

面向 [Claude Code](https://claude.com/claude-code) 的**证据驱动工作日志**：把「你实际做了什么」自动变成**滴答清单里的已完成任务**和 **Obsidian 日记块**，每小时跑一次。

> 状态：实验性项目，从个人日常流程中抽离。Windows 优先、滴答优先、提示词为中文。安装前请先看[已知局限](#已知局限)。

```
~/.claude/projects/**/*.jsonl ──┐
                                ├──> 滴答已完成任务 ──> Obsidian 日记块
全机文件 mtime / 创建时间 ──────┘          ^
                                          │
Obsidian 手写行 ───────────────────────────┘  （反向补录）
一周日记块 ──> 结构化周总结（<vault>/07-日记/<YYYY>-W<NN>_周总结.md）
```

与「只读转录」的日志工具不同，本项目还会扫描**全盘文件改动时间**并标注 `[人为]` / `[疑似自动]`。在 Word、Origin、MATLAB、SolidWorks 里干的活，即使没经过 Claude，也会成为证据——这通常是研究者一天里最主要的部分。

## 工作方式

1. `daily_worklog.ps1`（每小时计划任务）抽取当天 Claude Code 转录里的用户输入。
2. `fs_evidence.py` 扫描配置的根目录（全盘约 1.38M 文件 / 约 70 秒，之后自适应到常用目录）。
3. 一次 `claude -p` 调用读取 `worklog_prompt.md` 与证据文件，完成：新建带真实起止时间的**已完成任务**、从日记手写行**反向补录**、写当天日记的 `## 滴答清单` 块。
4. `weekly_summary.ps1` 把一周的日记块压成七节总结；**数字全部由 `weekly_extract.py` 算**，模型只负责写。

设计原则：**编排脚本不做判断，全部判断交给一次 `claude -p`，规则集中在 `worklog_prompt.md`**。改规则不改代码。

## 前置条件

- Windows 10/11 + PowerShell 5.1
- Python 3.8+（纯标准库，不需要 pip）
- 已登录的 [Claude Code](https://claude.com/claude-code) CLI
- 在 Claude Code 里授权过滴答清单 MCP（项目级 `mcpServers`），存在 `mcp__dida365__*` 工具
- Obsidian vault，日记命名为 `YYYY-MM-DD.md`

## 快速开始

```bash
git clone <this repo> claude-worklog-dida
cd claude-worklog-dida
cp config.example.json config.json
# 编辑 config.json：vault 路径与 dida.mcp_key
```

找 MCP key：在 `~/.claude/.credentials.json` 的 `mcpOAuth` 下，键形如 `dida365|<id>`，整串填进 `config.json` 的 `dida.mcp_key`（或设环境变量 `WORKLOG_DIDA_MCP_KEY`）。

验证桥接：

```bash
python3 scripts/tools/dida_mcp_http.py list_projects '{}'
```

先干跑（不调模型、不写任务）：

```powershell
powershell.exe -NoProfile -File scripts/daily_worklog.ps1 -DryRun
powershell.exe -NoProfile -File scripts/weekly_summary.ps1 -WeekEnd <该周任意一天> -DryRun
```

注册计划任务（幂等）：

```powershell
powershell.exe -NoProfile -File scripts/register_worklog_task.ps1
powershell.exe -NoProfile -File scripts/register_weekly_task.ps1
```

## 配置

所有路径支持 `~` 与环境变量，见 `config.example.json`。

| 键 | 含义 |
|:---|:---|
| `vault` | Obsidian vault 根目录 |
| `daily_note_dir` | 日记目录（建议根目录；`legacy_daily_dir` 只读回退） |
| `weekly_dir` | 周总结输出目录 |
| `claude_projects` | Claude Code 转录目录（默认 `~/.claude/projects`） |
| `scan_roots` | 文件证据扫描盘符；留空 = 存在的 `C:`/`D:`/`E:` |
| `scan_skip` | 额外跳过的绝对路径前缀 |
| `tz_offset` | 任务时间戳时区偏移（DeepSeek 计费为北京时间：`+0800`） |
| `dida.credentials` / `dida.mcp_key` | MCP OAuth token 的读取位置 |
| `claude.command` | `claude` 可执行文件 |
| `claude.cost_script` | 可选的人民币花费统计脚本；留空则不记花费 |
| `schedule.task_folder` | 计划任务所在文件夹（默认 `\个人自动化\`） |

## 花费

有新增活动时每轮调用一次模型：DeepSeek 上约 ¥0.15–0.5，周总结约 ¥0.23。空闲轮在调模型前就退出（但文件扫描已跑完）。**没有每日次数上限**——重跑幂等，但活动多就花得多。

## 隐私

发给模型的证据包含你的输入、文件名/路径和日记文字；除此之外没有任何数据离开本机，项目不含遥测。`data/`、`logs/`、`config.json` 已被 git 忽略。建议先 `-DryRun` 看清到底会发什么。

## 已知局限

- **编排层仅 Windows**（PowerShell + 任务计划）；Python 部分可移植。
- 默认只接**滴答清单**；MCP 工具白名单写死在 `daily_worklog.ps1`。
- 提示词为中文，类目/emoji 规则按中文工作流设计。
- 只覆盖有本地痕迹的工作（Claude 会话或文件改动）；开会、阅读、电话除非写进日记，否则抓不到。
- Claude Code 转录只保留约 30 天，超过一个月的空档补不回来。

## 目录

```
scripts/
  daily_worklog.ps1      每小时编排
  weekly_summary.ps1     每周编排
  worklog_extract.py     转录 -> 证据
  fs_evidence.py         全机文件改动 -> 证据
  worklog_prompt.md      全部判断规则（真正的核心资产）
  weekly_prompt.md       周总结写作规则
  dida_to_obsidian.py    任务 -> 日记块
  obsidian_to_dida.py    日记手写行 -> 任务（反向）
  weekly_extract.py      周证据 + 程序统计
  register_*.ps1         计划任务注册
  wl_config.py/.ps1      共享配置加载
  tools/                 MCP HTTP 桥、任务审计、BOM 工具
```

## 许可证

MIT，见 [LICENSE](LICENSE)。
