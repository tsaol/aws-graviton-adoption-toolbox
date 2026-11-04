# AWS Graviton Adoption Toolbox（AWS Graviton 采用工具箱）

大多数工具帮你把代码"迁"到 AWS Graviton；这个工具箱帮一个新业务"放得下、稳得住"。

它是一个 plugin，也就是一组 [Agent Skills](https://agentskills.io) 打包在一起，Claude Code、Kiro、Codex、GitHub Copilot 都能用。它带着 AWS SA 和客户的平台、开发团队走完一个新业务采用 Graviton 的每一个阶段：

```
找场景和团队 -> 收益和容量初判 -> 依赖扫描 -> 压测 -> 灰度 -> 放量 -> 新增容量默认 arm
```

> **状态：开发早期（v0.1 进行中），还不能用于生产。**

## 工具箱里有什么

| 部分 | 做什么 | 来源 |
|---|---|---|
| `graviton-playbook/` | 总入口 skill：先问清现在卡在哪一步，再带到对应阶段的工具；每一步写明这一关客户要做什么决策 | 自研 |
| `integrations/` | 前几个阶段怎么调用现成工具：[Arm MCP Server](https://github.com/arm/mcp) / Kiro Graviton Migration Power、AWS Transform custom（Java）、graviton-readiness、Graviton Savings Dashboard | 现成工具，不重写 |
| `references/` | 性能对比口径检查清单（同可用区、同规格档位、按单位流量归一化、过关线事先定好）、灰度检查表 | 自研 |
| `graviton-rollout-capacity/` | **放量和容量 skill**：从 CloudTrail 请求记录判断开不出机器的原因（容量不足、配额，还是别的）；放量前检查；预留分批推演；每日放量页和每周采用健康度报表 | 自研 |
| `arm-only-failure-triage/` | **arm 上的问题排查 skill**：先逐个排除内存序、编译器 bug、分配器混用、`char` 符号、浮点差异、错误的 native 库，再下根因结论；`harness/` 在 x86 和 Graviton 上编译同一个 commit 来复现 | 自研 |
| `replay-bench/` | **回放考题**：用真实故障（脱敏）和公开的事后复盘做题；每题装工具箱和不装工具箱各跑一遍，按根因对错、用时、错误结论打分 | 自研 |

## 原则

- **脚本出事实，模型做判断**：去重、分类、容量计算用脚本，结果可以复查。
- **诚实条款**：没跑的检查写 `NOT RUN`；没在两种架构上复现，不写根因。
- **默认只读**：碰 AWS 账号的 skill 都附只读 IAM 策略，不会自己开机器或改配额。
- **仓库里不放客户数据**：测试数据和回放题都是脱敏的或构造的。

## 路线图

| 版本 | 范围 |
|---|---|
| v0.1 | `graviton-playbook` + `graviton-rollout-capacity` + 2 道回放题；其他阶段先放一张"该用哪个现成工具"的表 |
| v0.2 | `arm-only-failure-triage` + 复现 harness；5 道回放题 |
| 之后 | 口径检查清单、每周采用报表、20 道以上回放题、Kiro / Claude Code / Codex / Copilot 各自的成绩 |

## Security

见 [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications)。

## License

本项目使用 MIT-0 许可证，见 LICENSE 文件。
