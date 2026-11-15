# 游戏特化 Q4 量化 —— 操作手册

> 目标：以 Qwen3.8-Flash-Next 为底模，用游戏开发领域语料做 importance matrix，
> 产出一个特化 Q4，与现有的 `UD-IQ4_XS-v31` 做全面对比。
>
> **本目录下的文件全部是准备件，不会自动执行任何重活。**

## 现状（现有模型 UD-IQ4_XS-v31，93.7 GB）

| 组成 | 体积 | 占比 | 当前精度 |
|---|---|---|---|
| 路由专家 ffn_gate/up/down_exps | 59.9 GB | 64% | IQ2_S / IQ3_XXS / IQ4_XS / IQ4_NL / Q5_0 |
| PLE 查表 per_layer_token_embd | 28.8 GB | 31% | IQ4_NL (4.5 bpw) |
| 注意力 + SSM + 路由器 + 共享专家 | 4.98 GB | 5% | Q6_K / Q8_0 / F32 |

**两条结论：**

1. **注意力已经很高了**（Q6_K/Q8_0），只占 5%，再往上加精度是浪费预算。
2. **特化必须作用在专家上**（64%）。但逐张量类型 Unsloth 已经调过了（UD = Dynamic），
   所以你的增量收益主要来自 **imatrix 的领域校准**，不是重排张量类型。

## 所以本方案的打法是

```
保持关键小张量的高精度（路由器 F32、注意力 Q6_K、共享专家 Q8_0）
        ↓
其余交给 Q4_K 基线 + 游戏领域 imatrix 去分配
        ↓
产出体积约 90~95 GB，与你现有模型同量级
```

**不做**：把专家整体降到 Q3 换取速度——那会掉质量，与目标相反。

## 四步流程

| 步骤 | 命令 | 资源 | 能否在服务期间跑 |
|---|---|---|---|
| 0 | 下载 UD-Q5_K_XL 源 | 网络 + HDD | ✅ 可以 |
| 1 | `1-imatrix.cmd` | **整机内存 + 全速跑模型** | ❌ 必须停机 |
| 2 | `2-quantize.cmd` | CPU + 磁盘 200 GB | ⚠️ 限 2 线程可跑，会拖慢 |
| 3 | `3-compare.md` 里的流程 | — | — |

## 为什么源选 UD-Q5_K_XL 而不是 Q8_0

- Q8_0 ≈ 188 GB、Q6_K_XL ≈ 169 GB，都超过本机 125.5 GiB 内存
- Q5_K_XL ≈ 158 GB，且它的**主体权重只比 Q6 低一点**，大部分体积差在 PLE 表
- **重要**：Q5/Q6 里 PLE 表被放在 Q8_0（约 50.7 GiB），而 Q4 文件里是 IQ4_NL（约 26.8 GiB）。
  我们量化时会把 PLE 表**压回 IQ4_NL**，所以输出不会因为源是 Q5 而变大。

## 磁盘规划

| 内容 | 大小 | 放哪 |
|---|---|---|
| UD-Q5_K_XL 源 | ~158 GB | **H:（HDD）** |
| 输出特化 Q4 | ~92 GB | **H:（HDD）** → 再拷到 D: |
| imatrix 文件 | 几十 MB | 本目录 |

⚠️ **不要写 D:** —— 那是正在服务的模型所在的 SSD（只剩 123 GB）。

## 目录约定

```
E:\Strata\quant\
  README.md            ← 本文件
  game-types.txt       ← 张量类型表
  1-imatrix.cmd        ← 生成 imatrix（停机）
  2-quantize.cmd       ← 量化
  3-compare.md         ← 对比方案
  corpus\              ← 你的语料放这里（见下）
```

## 语料怎么准备

`corpus\` 下放**纯文本**（.txt / .md），按优先级：

1. `01-code.txt` —— GDScript、C++、HLSL/GLSL shader、构建脚本（越多越好）
2. `02-math.txt` —— 图形学推导、矩阵/四元数、光照方程、物理公式
3. `03-agent.txt` —— 你 DSH 的真实工具调用日志（**这是公开语料没有的，最值钱**）
4. `04-art.txt` —— 美术 prompt、资产规格、色板/图集规范（少量即可）

**不要放**：小说、散文、闲聊、新闻。领域越纯，imatrix 越偏向你要的能力。

建议总量 5~20 MB 纯文本（imatrix 用不了更多）。

## 验收标准

产出的新模型必须同时满足：

- 体积 ≤ 100 GB（能装进 125.5 GiB 内存并留出缓存空间）
- 你的游戏开发任务盲评 **不劣于** UD-IQ4_XS-v31
- 解码速度下降 **不超过 10%**

任何一条不满足，就保留现有 IQ4_XS，不替换。

---

## 已完成的准备（2026-11-15）

### 工具

llama.cpp **b12407 CPU 版**已下载解压到 `E:\Strata\tools\llama.cpp\`（24 MB）。

选 CPU 版是故意的：**完全不碰显卡**，不会和正在服务的引擎抢 VRAM。
已确认含 `llama-quantize.exe` 与 `llama-imatrix.exe`。

### 参数格式已实测校验

`--tensor-type-file` 的正确格式是 **`张量名=类型`**（等号），不是空格：

```
attn_qkv.weight=Q6_K
```

类型表**不支持注释行**，`#` 开头会导致解析失败。

### 实测踩到并修掉的坑

| 问题 | 现象 | 修复 |
|---|---|---|
| `ffn_down_exps` 全部 fallback | `q5_0 → q8_0`，文件反而涨到 108,560 MiB | 该张量 `ne0=640`，`640/256=2.5`，K-quant 除不尽。改用 32 块类型 `IQ4_NL` |
| 从已量化源降精度 | 不加 `--allow-requantize` 会拒绝 | 已加进 `2-quantize.cmd` |
| 名字撞车 | `per_layer_token_embd` 包含 `token_embd` | 用 `--token-embedding-type` 专用参数处理 token_embd，避免子串误匹配 |

### dry-run 结果（用现有 IQ4_XS 当占位源验证类型表）

```
model size = 89,322 MiB (4.23 BPW)
quant size = 94,161 MiB (4.46 BPW)     ← 92 GiB，在 100 GB 判定线内
fallback   = 0 个张量
```

张量分配确认命中：路由器 F32、注意力 Q6_K、共享专家 Q8_0、专家 gate/up IQ4_XS、
专家 down IQ4_NL、PLE 查表 IQ4_NL、output Q6_K、token_embd IQ4_XS。

### 语料

`corpus\03-agent.txt` 已从 DSH 会话日志自动抽取：**2.95 MB / 8,257 条**
（702 用户 / 903 助手 / 3,288 工具调用 / 3,364 工具返回）。

这是真实的工具调用轨迹，公开语料里没有。另外三类（代码/数学/美术）需要你自己补。

## 还差什么

| 项 | 状态 |
|---|---|
| llama.cpp 工具 | ✅ 已就位（b12407 CPU 版） |
| 类型表 | ✅ 已 dry-run 验证，0 fallback |
| **语料 12.98 MB** | ✅ 已在 5~20 MB 目标区间内 |
| **UD-Q5_K_XL 源（158 GB）** | ⬜ 未下载，放 H: |

语料构成：Godot 文档 9.17 MB + agent 轨迹 2.95 MB + Unity 开源工程 0.74 MB + 技能文档 0.13 MB。
详见 `corpus\README.txt`。

**Unreal Engine 5 收不了**：Epic 的源码仓库需要绑定账号才能访问，文档有版权，
无法合规自动获取。要加只能由你提供自己工程里的 C++ 模块和 `.usf/.ush` 着色器。


