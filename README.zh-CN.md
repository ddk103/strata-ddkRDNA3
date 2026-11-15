# strata-ddkRDNA3

[English](README.md) · [简体中文](README.zh-CN.md)

**Strata 的 RDNA3（gfx1100）优化分支 —— 面向 AMD RX 7900 XTX + Windows HIP。**

基于 [Niko1221/Strata](https://github.com/Niko1221/Strata) **v0.1.49.1**，在其上做了
14 个文件的移植修改（+663 / −29 行），并附上完整的实测调优记录。

---

## 这个分支为什么存在

gfx1100 在 Strata 里处境特殊。`src/core/arch_defaults.cpp` 里那张 21 项默认开关表
**只对 gfx1151（Strix Halo）生效**：

```cpp
if (!strata::kernels::gfx_arch_is_gfx1151(gcn_arch)) return t;
```

所以 7900 XTX 上那些开关**全部默认关闭**，每个用户都得自己手工回移——这正是 RDNA3
分支生态存在的原因。

这个分支把散落在几个项目里的技术移植到了 0.1.49.1 上：

| 开关 / 改动 | 作用 | 原始出处 |
|---|---|---|
| `STRATA_STACK_ISOLATE` | 预留 1 TiB 以下地址空间、隔离首线程栈（Windows HIP） | 上游 issue **#3431** |
| `STRATA_VERIFY_DEFER_CPU` | CPU 专家行延后一层并入残差（**改变输出**，opt-in） | pancake-strata |
| `STRATA_POOL_FUSE_PHASES` | mode 7：gate/up 与 down 合并进同一 phase | pancake-strata item 29 |
| `STRATA_POOL_TAIL4` | phase 末尾任务切 1/4，缩短尾巴 | basalt `553e9290d` |
| `resample_row` / `logit_bias` | 语法约束下对某一行重新抽取 | basalt `d64768699` / `02e1006fe` |
| `STRATA_PREFILL_COPY_EVENT_EVERY`、`_WAIT_DEDUPE` | 预填阶段拷贝事件去重 | pancake-strata |
| `serve/grammar.py` 接入 | `--grammar on` 让工具调用与 JSON 输出受语法约束 | 见 [NOTICE.md](NOTICE.md) |

改动清单（完整 diff 见 `gfx1100/patches/strata-0.1.49.1-gfx1100.patch`）：

```
src/program/generate.cpp          +169      src/kernels/cuda/gr.cu            +45
src/core/pinned.cu                +119      src/kernels/cuda/elementwise.cu   +35
src/prefill/prefill.cpp            +99      CMakeLists.txt                    +17
src/kernels/cpu/pool.cpp           +86      serve/server.py                   +17
src/core/verify.cpp                +66      + 5 个头文件
```

**这些技术没有一项是我原创的。** 算法和内核属于各自的作者，本分支只负责把它们移植到
0.1.49.1 上。完整署名链见 [NOTICE.md](NOTICE.md)。

---

## `gfx1100/` —— 调优记录

```
gfx1100/
├── docs/
│   ├── gfx1100-findings.md      gfx1100 上哪些开关真有用、哪些没用
│   ├── TUNING-LOG.md            每项改动的原值、新值、验证和回滚
│   ├── quantization-plan.md     领域特化量化：imatrix + 逐张量精度
│   ├── comparison-protocol.md   两个配置/模型的对比协议
│   └── corpus-notes.txt         校准语料的构建说明
├── configs/
│   ├── fork-8090.example.json   引擎配置样例（47 个环境变量、队列与会话缓存）
│   ├── glm-3.0bit.example.json  GLM-5.3-Flash 在 PolyStrata 上的启动配置
│   └── game-types.txt           llama-quantize 逐张量精度表
├── bench/
│   ├── bench.py                 解码速度 A/B 基准脚本
│   └── bench-*.json             原始测量数据
└── patches/
    └── strata-0.1.49.1-gfx1100.patch    14 文件，+663/−29
```

---

## 实测结果

### 1. 会话缓存 —— 本次最大收益

默认 `--conversation-cache-mib auto` 封顶 8 GiB，只放得下 3 个约 96K token 的会话。
多个 agent 会话交替时互相挤掉，每一轮都要全量重读提示词。

| 参数 | 改前 | 改后 |
|---|---|---|
| `--conversation-cache-mib` | auto（8192） | **16384** |
| `--conversation-cache-slots` | 4 | **8** |

```
改前：淘汰 142 次，最近一次只复用 21,357 / 96,075 token → 冷预填 25~40 秒
改后：淘汰   0 次，驻留 5~6 个会话，复用率 97~100%      → 预填 1~3 秒
```

会话缓存走**主机内存**，不占显存——这是它性价比这么高的原因。

### 2. 两个解码开关

`bench/bench.py`：固定约 1.5K 提示词、固定 256 token 输出、`temperature 0`，预热两次后
从 `/metrics` 按请求时间戳取对应的 `decode_tok_s`。

| | 基线 | `STRATA_TSUM=1` + `STRATA_RDNA_Q6K=1` |
|---|---|---|
| 样本 | 16 | 32 |
| 均值 | 88.23 tok/s | 89.60 tok/s（**+1.5%**） |
| 中位数 | 88.15 tok/s | 90.10 tok/s（**+2.2%**） |
| Welch t | — | 1.43（**未达显著**） |
| 95% 置信区间 | — | −0.50 … +3.23 tok/s |

方向上为正，但统计上无法证明。两个开关都不改变模型体积与显存，最坏情况是零收益，
所以保留。

### 3. 队列模型

| 参数 | 值 | 作用 |
|---|---|---|
| `max_queue` | 5 | 准入上限 = `max(1, batch) + max_queue` = 6 |
| `queue_timeout` | 270 | 排队超过 270 秒回 `429 queue_wait_timeout`，早于客户端 300 秒空闲超时 |

教训：`max_queue: 0`（准入 1）会让客户端 5 次重试全部吃 429；完全不设上限则队列无限
增长，请求排过 300 秒后客户端主动断开，GPU 白烧。

---

## ⚠️ 使用前请读

### 兼容性

1. **基线是 v0.1.49.1**。上游从未为这个版本发过 git tag，所以本分支不宜与 `main` 合并。
2. **只在一种配置上验证过**：RX 7900 XTX 24 GB + Windows 10 19045 + HIP（`amdhip64_7`）。
   Linux、官方 ROCm 栈、其他 RDNA3 卡（7800 XT / 7700 XT / 7600）**都没测过**。
3. 改动涉及 CUDA/HIP 内核与 CMake，**换编译器版本可能编不过**。

### 不包含的东西

4. **不含任何 AMD 专有二进制**：ROCm 运行时（`amdhip64_7.dll`、`amd_comgr.dll`）、
   hipBLASLt 调优表、rocBLAS 库，都需要自行安装。
5. **不含模型权重**，也不含任何 GGUF。
6. 不含预编译的 `strata.exe`。

### 关于性能数字

7. 所有数字都是**单机、单次会话、3~5% 噪声**下的测量，不是权威基准。同机重复测的波动
   可能超过被测差异本身。
8. **短上下文和长上下文差很多**：1.5K 上下文约 88 tok/s，10 万 token 约 68 tok/s
   （长上下文有 KV streaming）。跨长度比较没有意义。

### 输出质量

9. **部分改动会改变输出**，尤其 `STRATA_VERIFY_DEFER_CPU`（代码注释里明写
   "changes the output"）。做逐位对比前必须关掉。
10. `STRATA_RDNA_Q6K`、`STRATA_TSUM` 属于求和顺序优化，数学上等价，但**不保证逐位一致**。

### 安全

11. 配置样例里的 `api_key` 是占位符。部署前换成你自己的强随机值，不要把真实 key 提交回仓库。
12. 样例配置默认监听 `0.0.0.0`。不需要局域网访问就改回 `127.0.0.1`。

---

## 构建

步骤与上游一致，见 [README.upstream.md](README.upstream.md) 以及上游的
`docs/INSTALL.md`、`docs/AMD_HIP.md`。

Windows + HIP 的关键点：

- 需要 ROCm 或 AMD HIP SDK（提供 `amdhip64_7.dll`）
- 需要 CMake ≥ 3.24 和支持 HIP 的 MSVC / clang
- `-DCMAKE_HIP_ARCHITECTURES=gfx1100`
- 首次编译 10~20 分钟

---

## 许可

**MIT**。见 [LICENSE](LICENSE) —— 上游版权声明原样保留。

上游版权：Copyright (c) 2026 **Niko1221 and the Strata contributors**。
移植技术的版权归各自作者所有（pancake-strata、basalt、llama.cpp）。
本分支仅覆盖"把这些技术移植到 0.1.49.1"这层工作及调优记录。

完整署名链：[NOTICE.md](NOTICE.md)
