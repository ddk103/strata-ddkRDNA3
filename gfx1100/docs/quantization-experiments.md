# 量化实验记录（含失败结论）

> 全部在同一台机器、同一语料、同一参数下测得，可直接横向对比。
> 判据：**perplexity 越低越好**。原版 `UD-IQ4_XS` 是本仓库一切对比的基线。

---

## 测试方法

```bash
llama-perplexity.exe -m <模型> -f game-corpus-mixed.txt -c 512 --chunks 50 -t 8
```

- 语料：13.13 MB，Godot/Unity 代码 + agent 轨迹 + 技能文档，按 50 行分块轮转（保证顺序采样覆盖全部来源）
- 上下文 512，50 个 chunk，单线程数值稳定可复现
- 同一语料既用于 imatrix 校准，也用于 PPL 评估——**这会让结果偏向我们的模型，实际它仍然更差**

---

## 结果汇总

| # | 源模型 | imatrix | 类型表 | 位宽 | 体积 | **PPL** | vs 原版 |
|---|---|---|---|---|---|---|---|
| — | — | — | — | **4.23 BPW** | 87.24 GB | **6.2488 ± 0.158** | 基线 |
| 1 | UD-Q5_K_XL | 游戏语料 | 专家全钉 IQ4_XS/IQ4_NL | 4.46 BPW | 91.96 GiB | 6.9164 ± 0.185 | **+10.7%** |
| 2 | UD-Q5_K_XL | 游戏语料 | 交给 imatrix（只钉 down） | 4.58 BPW | 94.31 GiB | 6.9292 ± 0.185 | **+10.9%** |
| 3 | **Q8_0** | 游戏语料 | 交给 imatrix | 4.58 BPW | 94.31 GiB | 6.8483 ± 0.183 | **+9.6%** |

**第 1、2 条对比**：多给了 0.12 BPW、并让 imatrix 自由分配类型，质量变化 −0.2%（噪声内）。
→ **位宽分配不是瓶颈。**

**第 2、3 条对比**：把源从 Q5_K_XL 换成近乎无损的 Q8_0，只回收 1.2%。
→ **"二代量化误差"也不是主因。**（这是我最初的假设，被证伪）

---

## 差异定位

非专家张量**完全一致**：

| 张量 | 原版 | 本实验产物 |
|---|---|---|
| `attn_qkv` | Q6_K / Q8_0 | Q6_K ✓ |
| `output` | Q6_K | Q6_K ✓ |
| `token_embd` | IQ4_XS | IQ4_XS ✓ |
| `per_layer_token_embd` | IQ4_NL 28.80 GB | IQ4_NL 28.80 GB ✓ |

差异**全部在专家张量**：

| | 原版 UD-IQ4_XS | 本实验产物 |
|---|---|---|
| `ffn_gate_exps` | IQ2_S / IQ3_XXS / IQ4_XS 混合，**3.77 bpw** | Q4_K 统一，**4.83 bpw** |
| `ffn_up_exps` | 同上，3.77 bpw | Q4_K 统一，4.83 bpw |
| `ffn_down_exps` | IQ4_NL / Q5_0 混合 | IQ4_NL 统一 |
| 专家总量 | ~59.5 GB | ~68.0 GB |

**给 gate/up 多了 28% 的位宽，质量反而差 9.6%。** 这排除了"位宽不够"。

---

## 元数据核查（排除测量环境差异）

比对两边的 GGUF 元数据，功能性键完全一致。唯一差异：

| 键 | 原版 | 本实验 |
|---|---|---|
| `split.count` / `split.no` / `split.tensors.count` | 有（多分片） | 无（单文件） |
| `quantize.imatrix.dataset` | `unsloth_calibration_...` | `game-corpus-mixed.txt` |
| `general.file_type` | 30（IQ 系列） | 15（Q4_K_M） |

`general.file_type` 只是标签，不参与推理。**所以 ~10% 的差距是真实的质量差异，不是测量假象。**

---

## 结论（截至目前）

1. **从量化过的模型再量化，不是主因** —— Q8 源只比 Q5 源好 1.2%
2. **位宽分配不是主因** —— 多给 28% 位宽没有换来质量
3. **差异集中在专家张量**，且原版用**更低的位宽**得到**更好的质量**

第 3 条指向两个候选原因，仍在验证：

- **A**：imatrix 的来源比 imatrix 本身重要。原版用 Unsloth 自己的校准集（45 chunks，通用语料）；我们用游戏语料（300 chunks）。可能通用校准集反而更稳。
- **B**：i-quant（IQ2_S/IQ3_XXS/IQ4_XS）在这个模型上比 K-quant（Q4_K）**每比特更高效**，而 llama.cpp 的 `Q4_K_M` 基线强制把我们带到 K-quant。

---

## 复现实验顺序

```bash
# 1. 基线：原版
llama-perplexity -m <UD-IQ4_XS shard1> -f corpus -c 512 --chunks 50 -t 8

# 2. 从 Q8 源量化（推荐用 Q8，不要用 Q5——省一半下载量时质量只差 1.2%）
llama-quantize --allow-requantize \
  --imatrix <your.imatrix> \
  --tensor-type-file types.txt \
  --output-tensor-type Q6_K --token-embedding-type IQ4_XS \
  <Q8 shard1> <out.gguf> Q4_K_M <threads>

# 3. 打 pack 时注意：hc_* 等小张量必须是 BF16，否则 iq_pack.py 会拒绝
python tools/iq_pack.py --compat-bf16 --gguf <out.gguf> --out <packdir>
```

## 踩过的坑

| 坑 | 症状 | 解法 |
|---|---|---|
| `--keep-split` + 引擎同时运行 | `did not find weights`、写盘 0 MB/s、内存见底 | 停掉引擎再量化；内存不足时该报错不是致命的，但会假死 |
| robocopy `/J` 复制大模型 | 目标比源多 192 字节，尾部数据损坏，PPL 从 6.8 飙到 60 | 用普通模式；复制后**必须抽样比对哈希** |
| iq_pack.py 直接用普通 python | `ModuleNotFoundError: numpy` | 用引擎自带的 python（`data/terminal/current/python`） |
| iq_pack.py 不加 `--compat-bf16` | `output_hc_up.weight is Q8_0, but the engine requires BF16`，187 处 | 加 `--compat-bf16` |
| 长任务放在有时限的等待循环里 | 进程被静默回收，日志停在半句，无报错 | 等待循环不设截止时间，或让子进程脱离父进程 |
