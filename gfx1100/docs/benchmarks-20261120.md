# Qwen3.8-Flash-Next 实测基准 — 2026-11-20

> 这台机器的真实水平，以及**测速度必须同时交代的三个条件**。

---

## 0. 为什么这份文档要写这么细

这次测量里同一个模型报出过 **57 / 78 / 90 / 108 / 121 tok/s** 五种数字，全部都是真的。
差别的来源不是噪声，是**条件**：

| 条件 | 影响 |
|---|---|
| **输出长度** | 首 token 延迟是固定成本。输出 16 token 时占主导，600 token 时摊薄 |
| **内容可预测性** | MTP 草稿接受率。列内置函数远高于解释概念 |
| **专家缓存预热** | 冷机 72% → 热机 82%，decode 差 10%+ |
| **提示长度** | 影响最小。300 → 50K 只掉约 4% |

**所以任何"XX tok/s"不带这三个条件，都是无意义的数字。**

---

## 1. 测试环境

| 项 | 值 |
|---|---|
| GPU | AMD Radeon RX 7900 XTX，24 GB，gfx1100 |
| CPU | （本机） |
| 内存 | 125.5 GiB |
| 引擎 | Strata fork（`fork-1010-fuse/strata.exe`，0.1.49.1） |
| 模型 | Unsloth `UD-IQ4_XS`，**87.24 GB**，4 个分片 |
| 上下文 | 524,288 token（`--rope-scaling yarn --rope-scale 2`） |
| KV | **int8**（basalt 实测：int8 相对 fp16 的 KLD +0.0000，无损） |
| 专家缓存 | `--expert-cache auto` + `--adapt-every 1 --adapt-swaps 32` |
| 草稿 | `--spec 4 --spec-min-p 0.5 --mtp-window 4096` |
| PLE | `--ple-io ram`（28.8 GB 锁内存） |
| 采样 | `temperature=0`、`reasoning_effort=none`、**`presence_penalty=0`** |

---

## 2. 预热后的稳态 decode（最可引用的数字）

**条件**：预热 4 次请求之后，短提示（约 50 token），`max_tokens=600`，7 个不同的代码题轮换。

| 序号 | 输出 token | 耗时 | decode | 专家缓存 |
|---|---|---|---|---|
| 1 | 166 | 1.9 s | 108.0 | 81.6% |
| 2 | 600 | 5.9 s | 106.4 | 81.2% |
| 3 | 373 | 3.8 s | 108.3 | 80.2% |
| 4 | 448 | 4.8 s | 96.5 | 78.2% |
| 5 | 600 | 5.6 s | 109.3 | 82.1% |
| **中位数** | | | **108.0 tok/s** | |
| **范围** | | | 96.5 ~ 109.3 | |

**长提示（21,864 token）**：decode **93.8 tok/s**，prefill **2,733 tok/s**

---

## 3. 长度梯度（随机内容，避免前缀缓存）

用随机单词生成提示，确保不被 `--conversation-cache-mib 16384` 复用。

| 提示 token | prefill | decode（输出 236~324 token） | 专家缓存 |
|---|---|---|---|
| 325 | **325** tok/s | 90.5 | 76.5% |
| 1,111 | **1,111** tok/s | 95.4 | 86.2% |
| 5,426 | **1,809** tok/s | 99.6 | 86.5% |
| 21,722 | **2,715** tok/s | 87.8 | 85.6% |
| 50,628 | **2,531** tok/s | 95.0 | 85.7% |

**规律：**

- **Prefill 随长度上升**：325 → 2,715 tok/s（**8.4 倍**），约 5K 后进入稳态，50K 时因注意力开销回落到 2,531
- **Decode 与长度基本无关**：88 ~ 100，波动 ±6%，**没有随上下文衰减的趋势**

---

## 4. 输出长度对速度的影响（同一模型、同一配置）

| 输出 token | decode | 说明 |
|---|---|---|
| 16 | **57 ~ 78** tok/s | 首 token 延迟占主导，**不能当速度指标** |
| 236 ~ 324 | **88 ~ 100** tok/s | 常规情况 |
| 600 | **106 ~ 121** tok/s | 缓存最热时 |
| 预热后 600（中位数） | **108** tok/s | **推荐引用的稳态值** |

---

## 5. 一次测量陷阱（记录下来，别再踩）

第一版测长度梯度时，填充内容是**结构完全相同的代码**（`def handler_N(request, context):`）。
结果 26K 和 54K 的 prefill 报出 **8,979 / 13,580 tok/s** —— 比 5K 时的 1,566 还高，不合理。

**原因：前缀缓存命中了。** 同样的结构 → 同样的 token 前缀 → `--conversation-cache-mib` 直接复用。

换成随机单词后，22K 报出 **2,715 tok/s**，这才是真的。

**教训：测 prefill 必须保证每次提示内容不重复。**

---

## 6. 引擎日志字段的含义（容易误读）

```
[strata] done: 600 tokens in 7 s (111.1 tok/s)
```

- **"in 7 s" = 总墙钟时间**（prefill + decode）
- **"(111.1 tok/s)" = 纯 decode 速率**

验证：600 / 111.1 = 5.4 s 解码 + 1.6 s prefill = 7 s ✓

**不要用 "600 tokens in 7 s" 自己算 85.7 tok/s —— 那是错的。**

生成过程中速度还会爬升（缓存变热）：

```
answering: 399 of max 600 tokens, 101.4 tok/s, 5 s
answering: 531 of max 600 tokens, 107.6 tok/s, 6 s
done:      600 tokens             111.1 tok/s
```

---

## 7. 与社区的其他数字为什么不可比

| 来源 | 模型大小 | decode | 为什么不能直接比 |
|---|---|---|---|
| **本机** | IQ4_XS **87.2 GB** | 108 | — |
| pancake-strata（RX 7900 XT） | IQ2_XS 约 40 GB | 102 ~ 178 | 模型只有一半，显存装得下更多 |
| basalt（RTX 5090 + 5060 Ti） | NVFP4 + 双卡 | 213 ~ 484 | 双卡 + FP4 硬件 |

**同一张卡、同样的引擎优化，差别主要在"多少参数能装进显存"。**

---

## 8. 复现方法

```powershell
# 引擎
E:\Strata\data\terminal\current\python\python.exe `
  E:\Strata\src\Strata-rdna3-main\serve\server.py `
  --engine strata --config E:\Strata\fork-8090.json --port 8090

# 测一次（600 token 输出）
#   请求体: max_tokens=600, temperature=0, reasoning_effort=none
#   读引擎日志的 "done: N tokens in X s (R tok/s)" 里的 R
```

**测速度前先预热 4 次**，否则读到的是冷机数字，比稳态低 10~20%。

---

## 9. 结论

```
24 GB 显存跑 87 GB 模型（IQ4_XS），这套配置的水平是：

  decode   108 tok/s（短提示，预热后）
  decode    94 tok/s（22K 上下文）
  prefill 2,700 tok/s（5K 以上饱和）
  专家缓存 78 ~ 82%

并且 decode 几乎不随上下文长度衰减 —— 这是 KV int8 + 93% 显存命中 +
专家缓存自适应共同作用的结果。
```
