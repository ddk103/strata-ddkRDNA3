# gfx1100（RX 7900 XTX）实测结论

所有数字来自同一台机器：RX 7900 XTX 24 GB、Ryzen 7 9700X（8C/16T）、125.5 GiB 内存、
Windows 11、HIP（`amdhip64_7`）、Strata 0.1.49.1、Qwen3.8-Flash-Next UD-IQ4_XS。

---

## 1. gfx1100 没有默认开关行

`src/core/arch_defaults.cpp` 里那张 21 项开关表只在 `gfx_arch_is_gfx1151`（Strix Halo）时生效：

```cpp
if (!strata::kernels::gfx_arch_is_gfx1151(gcn_arch)) return t;
```

**后果**：7900 XTX 上 `STRATA_TSUM`、`STRATA_Q8_PACKED`、`STRATA_Q6_PACKED`、
`STRATA_MMVF_ROWS`、`STRATA_EXPERT_V2`、`STRATA_LFUSE`、`STRATA_GDN_*` 全部默认关闭，
每个用户都得自己手工回移。

这解释了社区里为什么有那么多 RDNA3 fork。

---

## 2. 实测有效的开关

| 开关 | 效果 | 是否改变输出 | 依据 |
|---|---|---|---|
| `STRATA_TSUM=1` | 解码 −0.9% 耗时 | **否**（求和顺序，逐位等价） | 上游 issue #5459 + 本仓库 A/B |
| `STRATA_RDNA_Q6K=1` | +3.5% tok/s、−4.1% ms/forward | 否（求和顺序） | 上游 PR #4859 |
| `STRATA_HIPBLASLT_TABLE=on` | 预填更好，解码略差 | 否 | 见下 |

### 本仓库的 A/B（两者同时开）

| | 基线 | 两者同开 |
|---|---|---|
| 均值 | 88.23 tok/s | 89.60 tok/s（+1.5%） |
| 中位数 | 88.15 | 90.10（+2.2%） |
| Welch t | — | 1.43（未达显著） |

噪声 3%，所以 1.5% 的提升**统计上无法确认**。但两个开关都不改变体积和显存，
最坏情况是零收益，因此保留。

---

## 3. 一个容易踩的版本坑

`STRATA_HIPBLASLT_TABLE`（gfx1100 的打包调优表）在 **0.2.13 的 Docker 镜像里默认关闭**，
即使用的是 Linux。实测代价：16K 提示词从 1,186 tok/s 掉到 769 tok/s（**−35%**）。

显式设置 `STRATA_HIPBLASLT_TABLE=on` 可以完全恢复。

> 来源：上游 issue #5666。

---

## 4. `STRATA_SELECT_WMMA` 不是逐位等价

官方声明里它会在约 5K 上下文之后出现少量 cell 翻转。
需要严格复现（bit-identical A/B）时必须关掉。

---

## 5. 会话缓存：最大的一次收益

这是本次调优里收益最大的一项，远超过任何微基准开关。

| 参数 | 改前 | 改后 |
|---|---|---|
| `--conversation-cache-mib` | auto（封顶 8192） | **16384** |
| `--conversation-cache-slots` | 4 | **8** |

结果：

```
改前：淘汰 142 次，最近一次只复用 21,357 / 96,075 token → 冷预填 25~40 秒
改后：淘汰 0 次，驻留 5~6 个会话，复用率 97~100%   → 预填 1~3 秒
```

**原因**：默认 8 GiB 只放得下 3 个约 96K token 的会话（每个约 2.4 GB）。
多个 agent 会话交替时互相挤掉，每次都要全量重读提示词。

会话缓存走的是**主机内存**，不占显存——这是它性价比高的原因。

---

## 6. 队列与超时

当客户端并发数超过单卡处理能力时，队列会无限增长：

| 参数 | 值 | 作用 |
|---|---|---|
| `max_queue` | 5 | 准入上限 = `max(1, batch) + max_queue` = 6 |
| `queue_timeout` | 270 | 排队超过 270 秒回 `429 queue_wait_timeout`，早于客户端 300 秒的 stream idle timeout |

**教训**：
- `max_queue: 0`（准入 1）会让客户端 5 次重试全部吃 429 而失败
- 不设上限则队列无限增长，请求排队超过 300 秒后客户端主动断开，白烧 GPU
- 合适的值取决于**客户端实际并发数**，不是越大越好也不是越小越好

---

## 7. 预填是 agent 场景的真瓶颈

同一张卡上的对比：

| | Qwen3.8-FN IQ4_XS | GLM-5.3-Flash 3.0bit |
|---|---|---|
| 预填 | 2,600~2,900 tok/s | **194~200 tok/s** |
| 解码 | 68~77 tok/s | 19~20 tok/s |
| 上下文上限 | 524,288 | 65,536 |
| 专家驻留显存 | 6,059 槽 | 1,701 / 12,384（**13.7%**） |

GLM 慢的根因不是量化格式，是 **86% 的专家要 CPU 现算**。
按每 GiB 显存约 129 个专家推算：48 GB 显存 → 约 27% 驻留，72 GB → 约 41%。

**结论**：320B 级模型在 24 GB 卡上做 agent 后端不现实，不是调参能解决的。

---

## 8. 显存与量化的关系

同一张卡上，模型体积直接决定专家驻留比例，进而决定解码速度：

| 模型 | 体积 | 专家驻留 | 解码 |
|---|---|---|---|
| Qwen3.8-FN UD-IQ4_XS | 93.7 GB | ~25% 槽位、75~80% 命中 | 68~77 tok/s |
| GLM-5.3-Flash 3.0bit | 105.8 GB | 13.7% | 19~20 tok/s |

注意"槽位占比"和"命中率"不是一回事——路由是集中的，靠 expert-profile 预热能把命中率拉高。

---

## 9. Windows 上读不到 AMD 显卡传感器

Strata 的 telemetry 对 AMD 只实现了 Linux 的 sysfs 路径：

```
/sys/class/drm/renderD*/device/hwmon/hwmon*/power1_average
```

Windows 没有 sysfs，所以 `/metrics` 里的 `gpu_note` 明写：

> no GPU load or VRAM readings for AMD cards on Windows yet

需要温度/功耗只能走外部工具（LibreHardwareMonitor 的 WMI / ADL）。

---

## 10. 复现方法

```bash
# 打补丁
git apply patches/strata-0.1.49.1-gfx1100.patch

# 用 bench/bench.py 测解码速度（需要引擎在跑）
export STRATA_API_KEY=your_key
python bench/bench.py baseline 16
```

测量要点：
- 固定提示词、固定输出长度、`temperature 0`
- 预热 2 次后再计时
- 从 `/metrics` 按请求时间戳取对应的 `decode_tok_s`
  （**不要**直接取 `requests[-1]`，环形缓冲不保证顺序）
- 跳过重启后的前 5 个请求（冷缓存不可比）
