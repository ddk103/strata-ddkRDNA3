# 测试环境与配置（复现这组数字需要的全部条件）

> 本仓库 `README.md` 里所有性能数字，都是在这套配置下测出来的。
> 换了任何一项（模型、量化、引擎参数、驱动版本），数字都不能直接比。

> **⚠️ 与 `configs/fork-8090.example.json` 的差异（2026-11-16 更新）**
>
> 测量时用的是 **47 个环境变量 + `--max-context 524288 --rope-scaling yarn --rope-scale 2`**。
> 后来一位第三方使用者实测指出，并回到源码核实确认了三个问题：
>
> 1. 模型原生上下文只有 **262,144**（GGUF 元数据 `qwen4exp.context_length`），
>    `524288 + yarn 2` 是外推，长上下文质量会掉
> 2. `STRATA_HIPBLASLT_TABLE` 在设了 `STRATA_HIPBLASLT_TUNING` 时**完全不生效**
> 3. `STRATA_PF_GROUP_RES`、`STRATA_PA_KLDS` 在本版本是 **no-op**
>
> 示例配置已改为修正后的 **44 项、`--max-context 262144`、不启用 yarn**。
> **本文的性能数字不受影响**：基准用的是约 1.5K token 的提示词，
> `--max-context` 和 rope 设置在这个长度上不参与计算。
> 逐条核实记录见 [tuning-verdicts.md](tuning-verdicts.md)。


---

## 1. 硬件

| 项 | 值 |
|---|---|
| GPU | **AMD Radeon RX 7900 XTX 24 GB**（gfx1100，RDNA3） |
| GPU 驱动 | `32.0.21030.2001` |
| CPU | **AMD Ryzen 7 9700X**，8 核 / 16 线程 |
| 内存 | **125.5 GiB**（约 135 GB） |
| 存储 | 模型在 SSD（WD_BLACK SN750 SE 1TB）上，NVMe |

## 2. 系统与运行时

| 项 | 值 |
|---|---|
| 操作系统 | **Windows 11 专业版** `10.0.26200` |
| GPU 后端 | HIP |
| HIP 运行时 | `amdhip64_7.dll`（由 AMD HIP SDK 提供，本仓库不包含） |
| 编译器 | 与上游 0.1.49.1 一致的 MSVC + HIP 工具链 |

## 3. 引擎

| 项 | 值 |
|---|---|
| 版本 | **Strata `0.1.49.1`**（`CMakeLists.txt` 里 `project(strata VERSION 0.1.49.1)`） |
| 二进制 | 由本仓库源码构建 |
| 推理服务 | `serve/server.py`，监听 8090 |

## 4. 被测模型

| 项 | 值 |
|---|---|
| 名称 | **Qwen3.8-Flash-Next** |
| 量化 | **Unsloth Dynamic `UD-IQ4_XS`**（文件名里的 "v31" 是打包版本号，不是量化格式） |
| 平均位宽 | **4.23 BPW** |
| 总体积 | **87.24 GB**（4 个 GGUF 分片） |
| 架构 | 176.9B 总参数（125B MoE 主体 + 51B n-gram 表 + ~4B MTP），512 专家 / top-10，48 层 |

分片构成（**注意：这不是均匀拆分**）：

```
00001  0.01 GB   元数据
00002 46.20 GB   稠密张量 + 36 层专家
00003 14.21 GB   12 层专家
00004 26.82 GB   per_layer_token_embd（n-gram 表，IQ4_NL）
```

**这个模型的张量并非统一 IQ4_XS**，是 Unsloth Dynamic 的逐张量混合：

| 张量 | 实际类型 |
|---|---|
| 路由专家 gate/up | IQ2_S / IQ3_XXS / IQ4_XS |
| 路由专家 down | IQ4_NL / Q5_0 |
| 注意力 q/k/v/gate/output | Q6_K，部分 Q8_0 |
| 路由器 `ffn_gate_inp` | **F32** |
| 共享专家 | Q6_K / Q8_0 |
| `per_layer_token_embd` | IQ4_NL |

## 5. 启动参数（完整）

```jsonc
"--expert-profile", "…\\fork-1010\\data\\expert-profile.bin",
"--expert-cache",   "auto",
"--spec",           "4",
"--spec-min-p",     "0.5",
"--mtp-window",     "4096",
"--kv",             "int8",
"--pcie-frac",      "0",
"--adapt-every",    "1",
"--adapt-swaps",    "32",
"--adapt-decay",    "0.97",
"--pool-workers",   "8",
"--grammar",        "on",
"--pack",           "…\\packs\\unsloth-ud-iq4_xs-v31",
"--native",         "…\\Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00004.gguf",
"--ple-gguf",       "…\\Qwen3.8-Flash-Next-UD-IQ4_XS-00004-of-00004.gguf",
"--max-context",    "524288",
"--rope-scaling",   "yarn",
"--rope-scale",     "2",
"--prefill",        "auto",
"--kv-resident",    "32768",
"--conversation-cache-mib",   "16384",
"--conversation-cache-slots", "8",
"--vram-reserve-mib",         "1900",
"--mtp",            "…\\mtp\\rt2"
```

## 6. 环境变量（47 项，全部非默认值）

```ini
GPU_MAX_HW_QUEUES=6
HIPBLASLT_TENSILE_LIBPATH=…\fork-1010\hipblaslt\library\gfx1100
ROCBLAS_TENSILE_LIBPATH=…\fork-1010\rocblas\library
STRATA_ARENA_PIN_GIB=56
STRATA_COMBINE_CPU=1
STRATA_GDN_CHUNK_GDV=0
STRATA_GDN_CHUNKED=1
STRATA_GDN_CONVL2=1
STRATA_GDN_HEAD=1
STRATA_GDN_NOY=1
STRATA_GDN_PP=1
STRATA_GR_FUSED=1
STRATA_GR_INJ_UP=1
STRATA_GR_RDNA=1
STRATA_GR_RDNA_A8=1
STRATA_GR_RDNA_Q8=1
STRATA_HC_UPMIX=1
STRATA_HEAD_MIX_MULTI=1
STRATA_HIPBLASLT_TABLE=on
STRATA_HIPBLASLT_TUNING=…\fork-1010\tuning\gfx1100-hipblaslt-100401.txt
STRATA_HIP_WMMA=1
STRATA_KV_HOST_DMA=1
STRATA_PA_FAST=1
STRATA_PA_KLDS=1
STRATA_PEER_TRANSPORT=host
STRATA_PF_F16=2
STRATA_PF_FUSED=1
STRATA_PF_GEMM=1
STRATA_PF_GROUP_RES=1
STRATA_PF_HCDOWN=1
STRATA_PF_PAD=1
STRATA_POOL_FUSE_PHASES=1
STRATA_PREFILL_AUTO_MAX=32768
STRATA_PREFILL_CPU_SHARE=auto
STRATA_PREFILL_CPU_SHARE_MAX=6144
STRATA_PREFILL_MMQ_TILE_ROWS=32
STRATA_PREFILL_RING=512
STRATA_QFUSE=1
STRATA_RDNA_MMVQ_WAVE=3
STRATA_RDNA_Q6K=1
STRATA_ROUTE_PUBLISH=1
STRATA_SELECT_WMMA=1
STRATA_SH_STREAM=0
STRATA_STAGER_RING=64
STRATA_TSUM=1
STRATA_VERIFY_QDEDUP=1
STRATA_WAIT_FUSE=1
```

> **重要**：这些开关**没有写进代码默认值**（`arch_defaults.cpp` 只有 gfx12 / gfx1151 / iGPU 三个分支，
> 没有 gfx1100）。也就是说，直接用上游默认配置编译运行，跑的是**未调优状态**，
> 复现不出这里的数字。完整列表见 `configs/fork-8090.example.json`。

## 7. 基准方法

`bench/bench.py`：

| 参数 | 值 |
|---|---|
| 提示词 | 固定，约 **1.5K token**（GPU 内存层级的技术说明请求） |
| 输出上限 | **256 token** |
| 采样 | `temperature 0`（greedy），结果确定 |
| 预热 | **2 次**（不计入统计） |
| 采样数 | 基线 16 次 / 加开关 32 次 |
| 数据来源 | `/metrics` 返回的 `decode_tok_s`，**按请求时间戳匹配**（不能取 `requests[-1]`，环形缓冲不保证顺序） |
| 统计量 | 均值、中位数、标准差、Welch t、95% 置信区间 |

## 8. 关键差异提醒

| 项目 | 本测试 | 常见误用 |
|---|---|---|
| 上下文长度 | 1.5K | 88 tok/s（短）与 68 tok/s（10 万 token）差 23% |
| 量化 | UD-IQ4_XS 4.23 BPW | Q5/Q6 会慢很多；Q2 会快很多 |
| 环境变量 | 47 项全开 | 默认编译 = 一项不设 |
| 引擎版本 | 0.1.49.1 | 0.2.x 的默认行为不同 |

## 9. 已知的局限

1. **只有一个模型、一种量化**的测试数据。没有跨量化对比。
2. **Windows 11 + HIP** 环境；Linux + 官方 ROCm 栈未测。
3. 各次测量之间隔了数小时，机器状态（GPU 温度、后台负载）不完全一致。
4. 噪声约 3~5%，小于这个幅度的差异不应被当作真实提升。

---

## 2026-11-18：`STRATA_ARENA_PIN_GIB` 从 `56` 改为 `auto`

原来示例配置里写死 `STRATA_ARENA_PIN_GIB=56`，这是按本机 125.5 GiB 调出来的。
第三方评测者在 94 GiB 的机器上照搬，专家槽位从 7368 掉到 6951（见
`community-status-20261116.md` 的评测核实）——**写死的值不可移植**。

源码 `include/strata/core/pinned.hpp` 给出了四个可选值：

| 取值 | 行为 |
|---|---|
| 不设置 | -1，引擎自己决定（0.1.30 的行为） |
| `auto` | -2，Windows 下按 GPU 共享内存预算切片 |
| `0` | 不设上限，整个专家 arena 都注册 |
| `N` | 最多 N GiB |

`pinned.cu` 里 `sliced_pin_limit()` 的注释说明了 `auto` 的算法：

```
4 GiB of the budget stay free for what the engine allocates after the arena;
without the DXGI numbers, RAM/2 - 8 GiB (the budget is about half the RAM).
```

**在本机（125.5 GiB）auto ≈ 125.5 / 2 - 8 ≈ 54.8 GiB**，与原来的 56 只差 1.2 GiB，
所以性能和槽位不会有可察觉的变化；换到 94 GiB 的机器上则自动算成约 39 GiB，
不会再挤压系统内存。

同一段注释还记录了一个真实事故，说明上限为什么必须存在：

> pinned slice by slice until the driver refused one (28 GiB of a 63 GB PC), that
> segment was left full and every later cudaMalloc failed "out of memory".

**结论：示例配置改用 `auto`，删掉机器相关的魔数。**
---

## 2026-11-18：`--ple-io ram` 实测 +5.7% prefill，`ARENA_PIN_GIB=auto` 多给 104 槽位

### 测量方法

引擎的 bench 走 HTTP，而 HTTP 服务在启动器那一层。为了不依赖客户端，直接用引擎自带的
生成模式测：

```
llama-tokenize -m <shard1> -f <14 KB 语料片段> --ids     → 6683 个 token
strata.exe --gpu 1 --tokens-file <ids> --max-new 8 <site args>
```

引擎自己打印计时，取 `prefill` / `decode` 两行。环境变量必须从配置的 `env` 段设置——
不设 `ROCBLAS_TENSILE_LIBPATH` 会得到 `hipErrorInvalidDeviceFunction:98`。

### `--ple-io` 六次测量

| 组 | 模式 | prefill | decode | 首个 token |
|---|---|---|---|---|
| A1 | ram | 1109.47 tok/s | 39.02 tok/s | 6297 ms |
| A2 | ram | 1091.52 | 42.07 | 6373 |
| A3 | ram | 1108.38 | 44.52 | 6281 |
| B1 | direct | 1047.09 | 41.27 | 6652 |
| B2 | direct | 1047.57 | 42.56 | 6637 |
| B3 | direct | 1035.64 | 42.64 | 6712 |

```
ram 平均    1103.1 tok/s   (1091.5 ~ 1109.5)
direct 平均  1043.4 tok/s  (1035.6 ~ 1047.6)
提升         +5.7%
```

**两组完全不重叠**：最慢的 ram（1091.5）仍快于最快的 direct（1047.6）。

**decode 无差异**（41.9 vs 42.2 tok/s，8 token 样本不足以分辨）。首个 token 延迟从
6667 ms 降到 6317 ms（−5.2%）。

### 代价

```
PLE 表锁进内存（VirtualLock）:  28.8 GB
启动时间:                       +8 ~ 25 秒
专家文件可用页缓存:              48.7 GiB → 23.9 GiB
```

启动日志会显示 `PLE table locked in RAM (--ple-io ram) in 8.4 s`。

**交易是划算的**：prefill 快 5.7%，decode 不受影响；代价是 RAM 占用和启动延迟。

### `STRATA_ARENA_PIN_GIB=auto`

| 取值 | 专家槽位 | VRAM |
|---|---|---|
| `56`（写死） | 5826 | 13.31 GiB |
| **`auto`** | **5930** | **13.53 GiB** |

**`auto` 比写死的 56 还多 104 个槽位**（+1.8%）。`sliced_pin_limit()` 用
`RAM/2 − 8 GiB ≈ 54.8 GiB`，比硬编码的 56 更贴合实际，留出了更多 VRAM 给专家缓存。
并且它是可移植的：94 GiB 的机器上会算成约 39 GiB。

### 顺带记录：引擎自带的一条警告

```
strata: WARNING --prefill auto: prompt chunks of 8192 tokens or more crashed
the engine on Windows HIP (RX 7900 XTX: the commit charge jumped ~70 GB, exit code ...)
```

`--prefill auto` 在 Windows HIP 上，8192 token 以上的 chunk 会让提交内存跳涨约 70 GB 并
崩溃。当前的 `STRATA_PREFILL_AUTO_MAX=32768` 需要留意这条。

### 已固化到配置的三项

| 项 | 旧值 | 新值 | 依据 |
|---|---|---|---|
| `STRATA_ARENA_PIN_GIB` | `56` | `auto` | 多 104 槽位且可移植 |
| `--ple-io` | 未设（direct） | `ram` | prefill +5.7% |
| `STRATA_PF_FUSED` | `1` | 移除 | PR #999：gfx1100 上 parity within noise |