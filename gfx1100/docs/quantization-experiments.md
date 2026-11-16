# 量化实验记录：七次尝试与最终结论

> 全部在同一台机器、同一语料、同一参数下测得，可直接横向对比。
> 判据：**perplexity 越低越好**。原版 `UD-IQ4_XS` 是本仓库一切对比的基线。
>
> **一句话结论**：用**已量化的模型**做源，无论怎么调类型表和 imatrix，
> 都追不上用 **BF16 源**量化出来的原版。差 8.7%（K-quant 路线）。

---

## 测试方法

```bash
llama-perplexity.exe -m <模型> -f game-corpus-mixed.txt -c 512 --chunks 50 -t 8
```

- 语料：13.13 MB，Godot/Unity 代码 + agent 轨迹 + 技能文档，按 50 行分块轮转
- 上下文 512，50 个 chunk
- 同一语料既用于我们自己的 imatrix 校准，也用于 PPL 评估——**这会让结果偏向我们的模型，
  而它仍然更差**
- 硬件：RX 7900 XTX + Ryzen 7 9700X + 125.5 GiB，Windows 11 26200（详见 `test-environment.md`）

---

## 全部七组结果

| # | 源 | imatrix | 类型表 | 位宽 | 体积 | **PPL** | vs 原版 |
|---|---|---|---|---|---|---|---|
| — | **BF16** | Unsloth 官方 | Unsloth 混合 | 4.23 BPW | 87.24 GB | **6.2488** | 基线 |
| 1 | Q5_K_XL | 游戏语料 | 专家全钉 IQ4_XS/IQ4_NL | 4.46 | 91.96 GiB | 6.9164 | +10.7% |
| 2 | Q5_K_XL | 游戏语料 | 交给 imatrix | 4.58 | 94.31 GiB | 6.9292 | +10.9% |
| 3 | Q8_0 | 游戏语料 | 交给 imatrix | 4.58 | 94.31 GiB | 6.8483 | +9.6% |
| 4 | Q8_0 | **无** | 交给 imatrix | 4.58 | 94.31 GiB | **6.7897** | **+8.7%** |
| 5 | Q8_0 | Unsloth 官方 | 交给 imatrix | 4.58 | 94.31 GiB | 6.8183 | +9.1% |
| 6 | Q8_0 | 无 | down=Q5_0, gate/up=IQ3_S | 4.32 | 89.03 GiB | 7.3604 | +17.8% |
| 7 | Q8_0 | Unsloth 官方 | **逐张量精确复刻原版（1224 条）** | 4.23 | 87.24 GB | **7.2377** | **+15.8%** |

**第 7 组是最关键的一次**：类型分配与原版**逐个张量相同**、体积相同（87.24 GB）、
imatrix 相同（Unsloth 官方），唯一区别是**源不是 BF16**。结果还是差 15.8%。

---

## 被证伪的三个假设

| 假设 | 实验 | 结果 |
|---|---|---|
| 「二代量化误差是主因，用 Q8 就够」 | 第 2 vs 3 组 | 只回收 1.2% → **证伪** |
| 「位宽不够」 | 第 1 vs 2 组（多 0.12 BPW） | 无变化 → **证伪** |
| 「imatrix 来源是关键」 | 第 4 vs 5 组（无 vs 官方） | 官方 imatrix 反而差 0.4% → **证伪** |
| 「位宽分配反了（down 该更高）」 | 第 6 组 | 差 8.4% → **证伪** |

---

## 真正的规律：i-quant 对源精度敏感，K-quant 不敏感

把实验按「源精度 × 类型族」重排，规律立刻显现：

| 类型族 | 源 | PPL 区间 |
|---|---|---|
| **i-quant**（IQ3_XXS / IQ2_S / IQ3_S） | Q8_0 | **7.24 ~ 7.36** |
| **K-quant**（Q4_K） | Q8_0 | **6.79 ~ 6.85** |
| **i-quant** | **BF16** | **6.25**（原版） |

**同一份 Q8 源，i-quant 比 K-quant 差 8%。**

### 原因在 `llama-quantize` 自己的警告里

```
--allow-requantize
allow requantizing tensors that have already been quantized
WARNING: this can severely reduce quality compared to quantizing
from 16bit or 32bit!
```

- **K-quant** 用简单的 min/max 缩放 + 分块量化，对输入的小扰动**鲁棒**
- **i-quant** 做重要性加权的**网格/码本搜索**，对输入数值敏感；从 Q8_0 反量化回来的值
  与原始 BF16 有微小差异，足以让搜索落到次优的格点分配上

原版是用 BF16 直接量化的，完全避开这个问题。

---

## 结论

**从已量化的模型做源，追不上原版。** 两条路：

| 路线 | 可达 PPL | 相对原版 | 成本 |
|---|---|---|---|
| K-quant + 现有 Q8 源 | **6.79** | +8.7% | 已完成（约 1 小时） |
| **i-quant + BF16 源** | 预期 ≈6.25 或更好 | 待测 | 下载 330 GB（10~16 h）+ 量化 1 h |

**要真正达到或超过原版，必须从 BF16 开始。** 这不是调参问题，是量化器对输入精度的
硬性要求。

### 如果只想比原版小、接受略差

第 4 组（Q8 源 + 无 imatrix + K-quant）是这条路的终点：**6.7897，91.96 GiB**。
比原版小 5%、慢 9%，换来的是自己完全掌控的量化流程。

---

## 复现步骤

```bash
# 1. 基线
llama-perplexity -m <UD-IQ4_XS shard1> -f corpus -c 512 --chunks 50 -t 8

# 2. 从 Q8 量化（K-quant，不要用 i-quant）
llama-quantize --allow-requantize \
  --output-tensor-type Q6_K --token-embedding-type IQ4_XS \
  <Q8 shard1> <out.gguf> Q4_K_M <threads>

# 3. 从 BF16 量化（i-quant，需要 BF16 源）
llama-quantize --imatrix <unsloth.imatrix> --tensor-type-file <types> \
  <BF16 shard1> <out.gguf> Q4_K_M <threads>

# 4. 打 pack：hc_* 等小张量必须是 BF16，否则 iq_pack.py 拒绝
python tools/iq_pack.py --compat-bf16 --gguf <out.gguf> --out <packdir>
```

---

## 踩过的坑（每一个都浪费过时间）

| 坑 | 症状 | 解法 |
|---|---|---|
| `--keep-split` + 引擎同时运行 | `did not find weights`、写盘 0 MB/s、内存见底 | 停引擎再量化。那条报错**不是致命的**，是分片搜索的正常提示 |
| robocopy `/J` 复制大模型 | **目标比源多 192 字节，尾部数据损坏，PPL 从 6.8 飙到 60** | 用普通模式（不加 `/J`）；复制后**必须抽样比对首尾哈希** |
| `iq_pack.py` 用普通 python | `ModuleNotFoundError: numpy` | 用引擎自带的 python（`data/terminal/current/python`） |
| `iq_pack.py` 不加 `--compat-bf16` | `output_hc_up.weight is Q8_0, but the engine requires BF16`，187 处 | 加 `--compat-bf16` |
| 长任务放在有时限的等待循环里 | 进程被静默回收，日志停在半句，无任何报错 | 等待循环**不设截止时间**；或让子进程脱离父进程 |
| 后台任务里 `-RedirectStandardOutput` 同名 | 两个进程抢同一日志，先写的被截断 | 每个实验用独立日志名 |
| `--tensor-type-file` 里混进非 `name=TYPE` 的行 | `parse_tensor_type: malformed tensor type 'python.exe'` | 写文件前用正则 `^[\w.]+=[A-Za-z0-9_]+$` 过滤 |
| 类型表只改了路由专家、忘了共享专家 | 以为在"精确复刻"，实际 `ffn_*_shexp` 还是 Q8_0 | 从原模型**逐张量**导出全部 1224 条，不要手工挑 |

---

## 追加：BF16 源实验（2026-11-16 晚）

假设「i-quant 必须从 BF16 量化」。下载了 329.72 GB 的 BF16 权重，用**原版逐个张量完全
相同的类型表**（`tools/` 脚本从原版导出的 1224 条，经 `type_diff.py` 校验 **0 处差异**）
量化了两次，唯一区别是 imatrix：

| 版本 | 源 | imatrix | 体积 | **PPL** | vs 原版 |
|---|---|---|---|---|---|
| 原版 UD-IQ4_XS | BF16 | Unsloth 官方 | 87.24 GB | **6.2488** | 基线 |
| A | BF16 | Unsloth 官方 | 87.24 GB | 7.1432 | +14.3% |
| B | BF16 | 游戏语料 | 87.24 GB | 7.0679 | +12.5% |

**假设被证伪**：从 Q8 换到 BF16 只回收 **1.3%**（7.2377 → 7.1432），不是预期的 15%。

### 但游戏 imatrix 第一次赢了

A 与 B 之间唯一的变量是 imatrix，**B 好 1.1%**。前七次实验要么源精度不对、要么类型
没对齐，这是第一次公平对照——**领域语料确实有效，只是幅度（1%）被工具链差异（13%）
完全淹没**。

### 真正的差异来源

把九次实验按「类型族」重排：

| 类型族 | 我们的最好成绩 | 原版 |
|---|---|---|
| **i-quant**（IQ2_S / IQ3_XXS / IQ4_XS / Q5_0） | 7.07 | **6.25** |
| **K-quant**（Q4_K） | **6.79** | — |

同一个源、同样的类型、同样的 imatrix，llama.cpp **b12407** 做不出 6.2488。

差异不在源精度、不在 imatrix、不在类型分配——**只剩量化器实现本身**。

### 可疑线索

llama.cpp 在 2026-10-28 合入 `Speed up IQ4 quant creation with pre-computed halfway
points (#31201)`。提速类改动若引入舍入差异，会让 i-quant 落到次优格点——**而 i-quant
恰恰对这类差异最敏感，K-quant 的 min/max 缩放则不受影响**。

这与观察到的现象吻合：i-quant 全线落后 13~18%，K-quant 只落后 8.7%。

**验证方法**（未执行，成本约 2 小时）：用 10-28 之前的 llama.cpp 构建重新量化一次，
看 i-quant 的 PPL 是否回落。若回落，说明是 b12407 的回归，可以向上游报告。

### 九次实验的结论

**用 llama.cpp 复现 Unsloth 的 UD-IQ4_XS 做不到，最好差 8.7%。**

- 想要**更好**：直接用 Unsloth 原版，或者等这个工具链问题查清
- 想要**更小**：K-quant + Q8 源，6.7897 / 91.96 GiB，比原版小 5%、差 9%，可控
- 想要**领域特化**：方向对（游戏 imatrix 赢 1.1%），但需要先解决工具链差异，否则
  1% 的收益看不见