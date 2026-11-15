# 开关实录：哪些真有效、哪些是空操作、哪些不能照搬

> 这份文档的存在，是因为**一位第三方用户在 2026-11-16 实测了本分支并提出了逐条质疑**。
> 下面每一条都回到源码或元数据核实过，verdict 是核实结果，不是转述。
>
> 感谢该评测：它抓出了 3 个真实的配置坑，也有一条判断相反。

---

## 一、必须修正的（配置里有坑）

### 1. 上下文长度：模型原生只有 262,144，不是 524,288

```bash
$ python tools/gguf_kv.py model-00001-of-00004.gguf | grep context
qwen4exp.context_length    262144
```

本分支早期示例配置写的是：

```
--max-context 524288 --rope-scaling yarn --rope-scale 2
```

**这是把模型拉到训练长度的 2 倍。** 262,144 以内是原生能力，超出部分靠 YaRN 外推，
长上下文质量会明显下降（位置编码外推不是免费的）。

**正确做法**：

```
--max-context 262144            # 落在训练分布内，不启用 yarn
```

只有在明确需要 >262K 且接受质量损失时才用：

```
--max-context 524288 --rope-scaling yarn --rope-scale 2
```

### 2. `STRATA_HIPBLASLT_TABLE` 在设了 `STRATA_HIPBLASLT_TUNING` 时完全无效

`src/prefill/gemm.cu:272`：

```cpp
const char* path = std::getenv("STRATA_HIPBLASLT_TUNING");
if (!path || !*path) {                      // ← 只有 TUNING 为空时才往下走
    const char* sw = std::getenv("STRATA_HIPBLASLT_TABLE");
    if (sw != nullptr && (... "off" ...)) return nullptr;
    from_package = true;
}
```

两个都设的时候，`TABLE` 那一行永远不会被执行。

- 用**打包调优表** → 只设 `STRATA_HIPBLASLT_TABLE=on`，**不要**设 `TUNING`
- 用**自己的调优文件** → 只设 `STRATA_HIPBLASLT_TUNING=<path>`

同时设两个不影响正确性，但会让人误以为 `TABLE` 在起作用。

### 3. `STRATA_ARENA_PIN_GIB=56` 绑定 125 GiB 内存，不能照搬

本仓库的参考配置面向 **125.5 GiB RAM** 的机器。专家 arena 固定钉 56 GiB。

在一台 **94 GiB** 的机器上照搬的结果（第三方实测）：

```
专家缓存槽位 7368 → 6951   （16.79 → 15.86 GiB 显存）
少掉的槽位直接变成磁盘 IO
```

**这是"照搬配置"最典型的失败模式**：同一条开关，内存多 30 GB 就是增益，少 30 GB 就是拖累。

**取值原则**：`ARENA_PIN_GIB` ≈ 物理内存 − 显存占用 − 系统与其他进程预留。
宁小勿大：钉太多导致换页，比钉少导致少量跑 CPU 更糟。

---

## 二、空操作（设了也没用，本版已失效）

### `STRATA_PF_GROUP_RES`

`src/prefill/prefill.cpp:6177` 的注释原文：

> `resident runs: group_resident above - upstream's form of [claude] STRATA_PF_GROUP_RES, now a no-op`

### `STRATA_PA_KLDS`

`src/kernels/cuda/qsa_prompt_attn.cu:2250` 的注释原文：

> `(the merge with upstream 0.2.4: our STRATA_PA_KLDS kernel variant gave way to upstream's read-ahead ...; STRATA_PA_KLDS is a no-op until re-measured)`

**建议从配置里删掉**。留着无害，但会让后来者以为它们有效。

---

## 三、被误判的一条：`STRATA_SH_STREAM=0` 不是反作用

第三方评测认为：`STRATA_SH_STREAM=0` 关掉了一个"默认开启、decode +1.8% / prefill +6.7%"的开关。

**源码不支持这个结论。** `src/core/verify.cpp:308`：

```cpp
bool sh_stream_on() {
    static const bool on = [] {
        if (const char* v = std::getenv("STRATA_SH_STREAM")) return v[0] != '0';
#if defined(STRATA_USE_HIP)
        return false;          // ← HIP 上默认就是关
#else
        return true;
#endif
    };
}
```

同一处的注释解释了原因：

> On HIP a cross-stream event dependency costs more than the shared expert takes to run,
> so there the fork starts off: ... the fork off decodes at **62.9 t/s against 43.4 t/s**
> with it on. ... **Strix Halo (gfx1151, unified memory) is the exception**: the fork pays
> there (+1.8% UD-IQ4_XS, +6.7% UD-Q4_K_XL decode at 8K), so the **gfx1151 arch table** sets
> `STRATA_SH_STREAM=1`.

所以：

- `+1.8% / +6.7%` 是 **gfx1151 统一内存**的数据
- **gfx1100（7900 XTX）在 HIP 下的默认就是关闭**
- `STRATA_SH_STREAM=0` 只是把默认值显式写出来，**冗余但完全正确**

这条建议保留 `=0`，或者直接删掉（删掉等于默认，也是关）。**不要设成 `=1`。**

---

## 四、机器相关的值（换机器必须重调）

| 开关 | 本仓库参考值 | 依赖什么 | 换机器怎么办 |
|---|---|---|---|
| `STRATA_ARENA_PIN_GIB` | 56 | 物理内存 | 按内存等比例缩放 |
| `--vram-reserve-mib` | 1900 | 桌面占用 | 24 GB 卡在纯桌面环境可降到 896 |
| `--conversation-cache-mib` | 16384 | 物理内存 | 每 96K token 会话约 2.4 GB，按内存给 |
| `--max-context` | ~~524288~~ → **262144** | 模型训练长度 | 固定，不要超过 262144 |
| `STRATA_PREFILL_MMQ_TILE_ROWS` | 32 | 上下文长度分布 | 长提示词调优；短提示词会让 MMQ 效率变差 |

### 关于 `STRATA_PREFILL_MMQ_TILE_ROWS=32`

第三方指出：它是**长提示词专用**，在 2~3K 提示词上会把 prefill 从 ~900 压到 ~550-690。

源码 `src/prefill/moe_mmq.cu:544` 显示它被当作上限使用
（`opt_rows = min(tile_cap, max_rows)`），几十万 token 的 chunk 里每个专家几百行会被压到 32 行，
GEMM 效率掉得快。

**本分支没有在本机验证过短提示词的代价。** 如果你的用法是短提示词 + 长输出，
建议先设为 `0` 或不设，A/B 之后再决定。

---

## 五、本分支到底改善了什么

诚实结论（来自本仓库自己的测量 + 第三方复核，两者一致）：

| 指标 | 效果 | 证据强度 |
|---|---|---|
| **prefill（长上下文）** | **+9% ~ +44%**，上下文越长优势越大 | 强（第三方 0→128K 全区间，本仓库也测到） |
| decode（短上下文） | **无显著变化**（+1.5%，Welch t=1.43 不显著） | 弱 |
| decode（长上下文） | 无改善 | — |
| decode 对比其他引擎 | 仍落后（第三方测 Avalon 快 15~20%） | 强 |

**为什么 prefill 涨而 decode 不涨**：本分支移植的多数优化（stager ring、prefill ring、
专家在长提示词上的复用）作用于**批量处理提示词**的阶段；decode 是逐 token 的，
瓶颈在专家路由与 KV 读取，这些改动帮不上忙。

**所以本分支的适用场景是**：长上下文、一次性读几万 token 的文档/代码库。
**不适合**：短对话、追求交互手感（每 token 延迟）的场景——那里换引擎比调参有用。

---

## 六、如果你要复现这些结论

```bash
# 1. 确认模型的原生上下文
python gfx1100/tools/gguf_kv.py <model-00001.gguf> | grep context_length

# 2. 确认某个开关是否 no-op
grep -rn "STRATA_XXX" src/ | grep -i "no-op\|noop"

# 3. 自己的机器上重调 arena pin
#    先设小一点，看日志里的专家缓存槽位和命中率
grep "expert cache\|hit rate" <engine log>
```

**不要照搬任何人的 47 个环境变量。** 每一项都依赖你的内存、显存、卡型和负载。
