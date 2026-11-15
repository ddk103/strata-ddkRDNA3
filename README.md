# strata-ddkRDN3

**Strata 在 AMD RX 7900 XTX（RDNA3 / gfx1100）+ Windows HIP 下的补丁集与实测调优记录。**

A patch set and tuning record for [Strata](https://github.com/Niko1221/Strata) on RDNA3
(gfx1100) under Windows HIP. Chinese-first; English summary at the bottom.

---

## ⚠️ 这不是一个引擎

**这是补丁，不是引擎。** 仓库里没有引擎源码，只有 14 个文件的 unified diff 和实测记录。
要跑起来，你需要自己准备上游 Strata v0.1.49.1 的源码。

**基线版本：`v0.1.49.1`**（`CMakeLists.txt` 里 `project(strata VERSION 0.1.49.1)`）。

> 注意：上游**没有为这个版本发布 git tag**，所以补丁大概率对不上其他版本。
> 打之前先看 `git apply --check`。

---

## 包含什么

```
patches/strata-0.1.49.1-gfx1100.patch   14 个文件，+676 / −42 行
configs/fork-8090.example.json          脱敏后的引擎配置（47 个环境变量、队列与会话缓存参数）
configs/glm-3.0bit.example.json         GLM-5.3-Flash 在 PolyStrata 上的启动配置
configs/game-types.txt                  llama-quantize 的逐张量精度表（游戏开发特化量化用）
bench/bench.py                          解码速度 A/B 基准脚本
bench/bench-*.json                      原始测量数据（基线 / 加开关）
docs/TUNING-LOG.md                      调优台账：每项改动的原值、新值、验证、回滚
docs/gfx1100-findings.md                哪些开关实测有用、哪些没用
docs/quantization-plan.md               领域特化量化的完整方案
docs/comparison-protocol.md             两个模型/配置的对比协议
docs/corpus-notes.txt                   构建校准语料的说明
```

---

## 补丁内容（全部是从别处移植，非原创）

这个补丁把散落在几个项目里的技术移植到了 0.1.49.1 这一版上：

| 开关 / 改动 | 作用 | 原始出处 |
|---|---|---|
| `STRATA_STACK_ISOLATE` | Windows HIP 下预留 1 TiB 以下地址空间、隔离首线程栈 | 上游 issue **#3431** |
| `STRATA_VERIFY_DEFER_CPU` | 把 CPU 专家行延后一层并入残差（**会改变输出**，opt-in） | pancake-strata |
| `STRATA_POOL_FUSE_PHASES` | mode 7：把 gate/up 与 down 合并进同一 phase | pancake-strata item 29 |
| `STRATA_POOL_TAIL4` | 一个 phase 末尾的任务切成 1/4 大小以减少尾巴 | basalt `553e9290d` |
| `resample_row` / `logit_bias` | 语法约束下对某一行重新抽取 | basalt `d64768699` / `02e1006fe` |
| `STRATA_PREFILL_COPY_EVENT_EVERY`、`_WAIT_DEDUPE` | 预填阶段拷贝事件去重 | pancake-strata |
| `serve/grammar.py` 接入 | `--grammar on` 让工具调用与 JSON 输出受语法约束 | 见 [NOTICE.md](NOTICE.md) |

**移植工作本身是我的；算法和内核不是。** 完整的署名链在 [NOTICE.md](NOTICE.md)，
如果哪一处的归属写错了，请开 issue 指正。

---

## ⚠️ 注意事项（务必读）

### 兼容性

1. **基线是 v0.1.49.1，上游没有该版本的 tag。** 补丁对不上 0.2.x。
2. **只在一种配置上验证过**：RX 7900 XTX 24 GB + Windows 10 19045 + HIP（`amdhip64_7`）。
   Linux、ROCm 官方栈、其他 RDNA3 卡（7800 XT / 7700 XT）**都没测过**。
3. 补丁涉及 CUDA/HIP 内核与构建脚本，**换编译器版本可能编不过**。

### 不含的东西

4. **不含任何 AMD 专有二进制**：ROCm 运行时（`amdhip64_7.dll`、`amd_comgr.dll`）、
   hipBLASLt 调优表、rocBLAS 库，都需要你自己装 ROCm / 从官方包获取。
5. **不含模型权重**，也不含任何 GGUF。
6. 不含 `strata.exe` 或其他预编译引擎。

### 关于性能数字

7. 仓库里的性能数字是**单机、单次会话、3~5% 噪声**下的测量，不是权威基准。
   同一台机器上重复测，波动范围可能超过被测差异本身。
8. 短上下文和长上下文的解码速度差很多（本例：1.5K 上下文约 88 tok/s，
   10 万 token 上下文约 68 tok/s，因为长上下文有 KV streaming）。
   跨上下文长度比较数字没有意义。

### 关于输出质量

9. **部分改动会改变输出**，尤其是 `STRATA_VERIFY_DEFER_CPU`（注释里明写 "changes the output"）。
   做逐位对比（bit-identical A/B）之前必须把这些开关关掉。
10. `STRATA_RDNA_Q6K`、`STRATA_TSUM` 这类求和顺序优化理论上等价，但**不保证逐位一致**。

### 安全

11. 配置样例里的 `api_key` 已替换为占位符。**部署前改成你自己的强随机值**，
    并且不要把真实 key 提交回仓库。
12. 样例配置默认监听 `0.0.0.0`。如果你不需要局域网访问，改回 `127.0.0.1`。

### 法律

13. **MIT 许可，无任何担保**。见 [LICENSE](LICENSE)。
14. 上游版权归 **Niko1221 and the Strata contributors**；移植的算法版权归各自作者。
    本仓库只覆盖"把这些东西移植到 0.1.49.1"这层工作。

---

## 怎么打补丁

```bash
# 1. 准备上游源码（v0.1.49.1）
#    上游没发 tag，只能靠 commit 或发行包里的源码

# 2. 试打，不写入
git apply --check patches/strata-0.1.49.1-gfx1100.patch

# 3. 正式打
git apply patches/strata-0.1.49.1-gfx1100.patch

# 4. 构建（Windows + HIP 示例）
```

> 如果 `--check` 报冲突，说明你的基线和 0.1.49.1 不一致，**不要强行打**。

---

## 实测：两个解码开关的效果

`bench/bench.py` 固定提示词（约 1.5K token）+ 固定输出 256 token + `temperature 0`，
预热 2 次后连续取样，从 `/metrics` 按请求时间戳取对应的 `decode_tok_s`。

| | 基线 | `STRATA_TSUM=1` + `STRATA_RDNA_Q6K=1` |
|---|---|---|
| 样本 | 16 | 32 |
| 均值 | 88.23 tok/s | 89.60 tok/s（**+1.5%**） |
| 中位数 | 88.15 tok/s | 90.10 tok/s（**+2.2%**） |
| 标准差 | 2.67 | 3.84 |
| Welch t | — | 1.43（**未达显著**） |
| 95% 置信区间 | — | −0.50 … +3.23 tok/s |

**结论**：方向上为正，但统计上无法证明。两个开关都不改变模型体积与显存占用，
最坏情况是"没有收益"，所以保留了。

**诚实的保留意见**：这台机器测量时背景有别的负载，噪声偏大。
要严格证明 1.5% 的提升，需要每边 60 个以上的样本、且机器完全空闲。

---

## 英文摘要

A patch set (14 files, +676/−42) that ports several published optimisation techniques
onto Strata v0.1.49.1 for AMD RDNA3 (gfx1100) on Windows HIP. It contains **no engine
source and no model weights** — you must supply upstream Strata yourself.

Ported from: Strata issue #3431 (Windows HIP stack isolation), pancake-strata
(deferred CPU expert rows, pool phase fusion, prefill copy dedupe), and basalt
(tail-4 tasks, `resample_row` / `logit_bias`). All techniques are MIT; see NOTICE.md
for the full attribution chain.

Verified only on RX 7900 XTX 24 GB / Windows 10 / HIP. Benchmark figures are single-run
measurements with 3–5% noise, not authoritative.

MIT licensed, no warranty.

---

## 许可

MIT。见 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md)。
