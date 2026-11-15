# 测试环境与配置（复现这组数字需要的全部条件）

> 本仓库 `README.md` 里所有性能数字，都是在这套配置下测出来的。
> 换了任何一项（模型、量化、引擎参数、驱动版本），数字都不能直接比。

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
