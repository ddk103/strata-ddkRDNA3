# NOTICE — 来源与署名

这个仓库**不包含任何原创算法或内核**。它做的事情只有一件：
把若干已发表的技术移植到 Strata v0.1.49.1 这一版上，并记录实测结果。

如果下面任何一条归属写错了或漏了，请开 issue 指正，我会改。

---

## 直接基线

**Strata** — MIT
Copyright (c) 2026 Niko1221 and the Strata contributors
https://github.com/Niko1221/Strata

本仓库的补丁以 Strata `v0.1.49.1` 为基线。`LICENSE` 文件原样保留上游版权声明。

---

## 移植的技术来源

### 1. Windows HIP 栈隔离（`STRATA_STACK_ISOLATE`）

来源：Strata 上游 issue **#3431**
"Windows HIP: main() reserves the free address space below 1 TiB and hands the
first thread's stack its own range."

### 2. 延迟 CPU 专家行、池阶段融合、预填拷贝事件去重

来源：**pancake-strata**
https://github.com/rocktboy1982/pancake-strata
（MIT，作者 Dan Iancu）

涉及：
- `STRATA_VERIFY_DEFER_CPU` / `STRATA_VERIFY_DEFER_CPU_BELOW` — 一个解码窗口的 CPU 专家行
  延后一层并入残差。注释里明写"changes the output"，属于 opt-in 的有损优化。
- `STRATA_POOL_FUSE_PHASES` — 池的 mode 7：gate/up 与 down 合并到同一 phase。
  标注为 "pancake-strata item 29"。
- `STRATA_PREFILL_COPY_EVENT_EVERY` / `STRATA_PREFILL_COPY_WAIT_DEDUPE` — 预填拷贝事件去重。

### 3. Tail-4 任务切分、`resample_row` / `logit_bias`

来源：**basalt**
https://github.com/jesdga95/basalt
（MIT，作者 Jesús Gulfo）

涉及：
- `STRATA_POOL_TAIL4` — 一个 phase 末尾的任务切成 1/4，缩短尾巴（basalt `553e9290d`，标注为 exact）。
- `resample_row` / `logit_bias` — 语法约束下对某一行重新抽取（basalt `d64768699` + `02e1006fe`）。

### 4. 语法引擎

`serve/grammar.py` 接入与 `--grammar on` 的语法约束解码路径，属于 Strata 自身的
`serve/` 层；其底层 GBNF 语法引擎由 **llama.cpp** 提供（MIT），
经由 basalt / pancake-strata 的移植链进入本仓库。

---

## 本仓库自身的工作

仅限：

- 把上述技术适配到 0.1.49.1 的接口与内核签名上；
- 解决移植过程中的编译与运行问题；
- 在 RX 7900 XTX + Windows HIP 上的实测数据与调优记录；
- 文档整理。

**没有**新的量化算法、新的内核设计或新的推理架构。

---

## 不含的内容

- 不包含 AMD 的 ROCm 运行时、hipBLASLt 调优表、rocBLAS 库（均为 AMD 专有，
  需从 AMD 官方渠道获取）。
- 不包含模型权重、GGUF 或任何预编译的引擎二进制。
- 不包含任何真实 API key 或个人凭据。

---

## 许可

本仓库以 **MIT** 发布，见 `LICENSE`。

上游 Strata 的版权声明必须保留。如果你的使用场景需要额外的合规审查，
请分别核对：

- Niko1221/Strata — MIT
- rocktboy1982/pancake-strata — MIT
- jesdga95/basalt — MIT
- ggml-org/llama.cpp — MIT
