# 社区分支与上游进展（2026-11-16 调研）

> 记录这份调研时各项目的状态，供后来者判断"该跟哪条线"。
> 所有结论都注明来源，未经验证的推断会标出来。

---

## 1. 上游 Niko1221/Strata

**最新：v0.2.14 / v0.2.14.1（2026-11-15）**，引擎 0.1.60 / 0.1.60.1。

### 核心变化：提示词读取改用自研内核

之前 prefill（提示词处理）用的是从 llama.cpp 拿来的代码，0.2.14 起换成 Strata 自己的内核，
NVIDIA 和 AMD、Windows 和 Linux 都换。`-DSTRATA_MMQ=ON` 仍可回退旧路径。

实测提升（**全部是 NVIDIA 和 Strix Halo**）：

| 机器 | 提示词 | 变化 |
|---|---|---|
| RTX 5090 32 GB | 32,000 tokens | 7,870 tok/s（旧 6,851）**+15%** |
| RTX 4090 24 GB | 20,000 tokens | 5,656 ms（旧 6,110）**−7.4%** |
| Strix Halo (Windows) | 4,096 tokens | 2,621 ms（旧 2,689） |

**AMD 唯一的数字是 Radeon R9700（Linux, gfx1201），而且是变差的**：

```
256 tokens:   255 tok/s（旧 396）
2,048 tokens: 889（旧 1,231）
20,000 tokens: 5,841（旧 5,800）持平
```

**没有任何 gfx1100 / RX 7900 的分级数据。** 所以"升到 0.2.14 能提升 RDNA3 性能"这个
结论目前**没有证据支持**。

### 输出会变

发布说明原文："Answers can differ from 0.2.13 in some words"。质量以 KL 散度衡量
（对 FP16 提示词路径，越低越接近）：RTX 5070 Ti + IQ3_S 是 0.00744，用 llama.cpp 内核是 0.0078
——**新内核略好**。

### 这一版已知的 Radeon 问题

- Radeon（Linux, R9700）：驱动会在引擎启动时暂停显卡 115~810 ms
- Radeon R9700（Linux）：某次启动首个提示词卡住，驱动重置显卡
- Radeon 780M（Linux）：首个请求可能触发 GPU reset（`MES failed to respond`）
- Radeon gfx1201：手工选 DFlash2 可能在提示词上卡住（0.2.11 起 50 个引擎里 11 个）

### 资产

有 `strata-engine-0.1.60-windows-x86_64-hip-rdna3.tar.gz`（262 MB）——**RDNA3 + Windows 的预编译包**。
但 release 里**没有源码包**；源码要从仓库 `main` 分支取（调研时为 `0.1.60.1`）。

---

## 2. rocktboy1982/pancake-strata

**5 star / 1 fork**，2026-11-16 仍有推送。

2026-11-13 合并了一批"优化分析"分支，根目录留下多份报告：

```
HIP_OPTIMIZATION_REPORT.md      ← 目标硬件写的是 RX 7900 XT（gfx1100）
CORE_OPTIMIZATION_REPORT.md
CPU_OPTIMIZATION_REPORT.md
PREFILL_OPTIMIZATION_REPORT.md
QWEN35_OPTIMIZATION_REPORT.md
POLY_OPTIMIZATION_REPORT.md
DSV41_OPTIMIZATION_REPORT.md
REMAINING_ANALYSIS.md
```

> **这些报告是 AI 生成的**（内容结构、措辞、以及"Already optimized ✅"这类判断都是典型特征），
> 里面大量是**未经验证的假设**，不是实测结论。当作检查清单用可以，当数据用不行。

### HIP 报告里值得注意的两条

**① `STRATA_HIP_WMMA=1`** —— gfx11 的 WMMA 注意力路径，报告建议开启。

**② `STRATA_RDNA_MMVQ_WAVE`** —— wave32 MMVQ 路径。**这条报告写错了取值**：

报告说"`NATIVE_WAVE = 32`，用 `STRATA_RDNA_MMVQ_WAVE` 开启"，暗示这是个开关。实际源码
（`native_mmvq.cu`）接受 **1 / 2 / 3** 三个值，含义不同：

```cpp
const bool g_wave_exact  = env == "3";                 // 把四个 warp 的部分和塞进单 wave 寄存器
const bool g_wave_shapes = g_wave_exact || env == "2"; // 只对实测过的小格式形状
bool g_wave_off = !(g_wave_exact || g_wave_shapes || env == "1");
```

源码原文："**Mode 3 is experimental until bitwise and timing checks pass.**"

所以 `=3` **不是"开启"，是打开实验模式**——逐位一致性尚未验证。追求可靠性的配置应该用
`=1` 或 `=2`，或者干脆不设。

### 报告里其余建议的可行性

| 建议 | 实际门槛 |
|---|---|
| 给热点内核加 `amdgpu_waves_per_eu` | 要重编译，且要逐个调参数并测量 |
| 检查 `__shared__` bank conflict | 要 `rocprof` / uProf，**Windows 上没有等价工具** |
| 验证 `__builtin_amdgcn_perm` 的代码生成 | 要 `hipcc -arch=gfx1100` 看汇编 |

报告自己在结尾也承认："All verification requires the Linux ROCm box"。

---

## 3. jesdga95/basalt

**1,095 star / 153 fork** —— 社区分支里体量最大的，每天都有提交。

但方向**不是 RDNA3**，近期全部围绕：

- 多卡（两卡）按层拆分：`the layer split runs a 27B that does not fit its main card across two cards`
- 每张卡只保留自己那些层的稠密权重
- 驱动挂起/恢复（SLEEP / WAKE）
- qwen35 支持、dense 模型支持

如果你只有一张卡，这些改动对你**没有直接收益**。

---

## 4. 结论：该跟哪条线

| 你的情况 | 建议 |
|---|---|
| 单卡 gfx1100 + Windows | **留在当前主线**，先修 #3431（见 `tuning-verdicts.md`） |
| 想要 0.2.14 的 prefill 提升 | **先用预编译 rdna3 包在独立端口实测**，别直接移植源码 |
| 两张卡 | basalt 值得看，它的层拆分是真做了工程 |
| 愿意重编译调参 | pancake 的报告能当清单，但每条都要自己测 |

**不要相信任何没有 gfx1100 实测数据的性能结论**——包括本仓库自己的，全部标注了测量条件。
