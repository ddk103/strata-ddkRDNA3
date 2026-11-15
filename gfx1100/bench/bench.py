"""Decode-speed A/B benchmark.

Fixed prompt, temperature 0, fixed output length, N consecutive runs. Reads the
engine's self-reported `decode_tok_s` from /metrics (excluding queue time, which
is more accurate than the wall clock).

Usage:
    python bench.py <label> [runs]

Environment:
    STRATA_BASE       engine URL          (default http://127.0.0.1:8090)
    STRATA_API_KEY    bearer token        (required)
    STRATA_MODEL      model id            (default: auto-detected from /v1/models)
    STRATA_BENCH_DIR  where JSON is saved (default: this script's directory)

Output:
    <STRATA_BENCH_DIR>/bench-<label>.json  and a summary on stdout.

Note: output is deliberately ASCII so it works on Windows code pages that are
not UTF-8 (a CP936 console raises UnicodeEncodeError on Chinese text).
"""
import json
import os
import statistics
import sys
import time
import urllib.request

BASE = os.environ.get('STRATA_BASE', 'http://127.0.0.1:8090')
KEY = os.environ.get('STRATA_API_KEY', '')
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.environ.get('STRATA_BENCH_DIR') or HERE

# Fixed prompt: technical content, stable output, roughly 1.5K tokens.
PROMPT = (
    "Write a technical explanation of GPU memory hierarchies for a game engine programmer. "
    "Cover: how VRAM differs from system RAM in bandwidth and latency, why texture compression matters, "
    "the role of L2 cache on RDNA3, what causes shader stalls on memory-bound workloads, "
    "how tile-based rendering changes the access pattern, and what a frame budget implies for the "
    "number of texture samples per pixel. Be concrete with numbers where you can, and keep the "
    "structure as a short numbered list of sections with a paragraph each."
)

label = sys.argv[1] if len(sys.argv) > 1 else 'run'
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 12
MAX_TOKENS = 256


def request(path, body=None, timeout=1800):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def metrics():
    return request('/metrics', timeout=30)


def detect_model():
    if os.environ.get('STRATA_MODEL'):
        return os.environ['STRATA_MODEL']
    try:
        m = request('/v1/models', timeout=15)
        return m['data'][0]['id']
    except Exception:
        return ''


MODEL = detect_model()


def once():
    t0 = time.time()
    body = {'model': MODEL, 'messages': [{'role': 'user', 'content': PROMPT}],
            'max_tokens': MAX_TOKENS, 'temperature': 0}
    r = request('/v1/chat/completions', body)
    return time.time() - t0, r.get('usage', {})


print('[%s] warming up: 2 runs (discarded)' % label)
for _ in range(2):
    once()

rows = []
for i in range(runs):
    t_start = time.time()
    wall, usage = once()
    # The engine's per-request record: take the newest entry whose time is at or
    # after this request started. Do NOT use requests[-1] -- the ring buffer does
    # not guarantee ordering, and a stale entry silently gives wrong numbers.
    last = {}
    for _ in range(6):
        try:
            m = metrics()
            cand = [r for r in (m.get('requests') or []) if r.get('time', 0) >= t_start - 2]
            if cand:
                last = max(cand, key=lambda r: r.get('time', 0))
                break
        except Exception:
            pass
        time.sleep(0.4)
    dec = last.get('decode_tok_s')
    outn = (usage or {}).get('completion_tokens') or last.get('output_tokens')
    # Wall-clock cross check: subtract only the prefill time.
    pre = (last.get('prompt_ms') or 0) / 1000.0
    wall_dec = round(outn / (wall - pre), 1) if outn and (wall - pre) > 0.2 else None
    row = {'wall_s': round(wall, 2), 'out_tokens': outn,
           'decode_tok_s': dec, 'decode_ms': last.get('decode_ms'),
           'prefill_ms': last.get('prompt_ms'),
           'first_token_s': last.get('first_engine_token_s'),
           'wall_derived': wall_dec}
    rows.append(row)
    print('  %2d  wall=%5.1fs  out=%4s  decode=%6s tok/s  (wall %5s)  prefill=%7s ms'
          % (i + 1, row['wall_s'], row['out_tokens'], row['decode_tok_s'],
             row['wall_derived'], row['prefill_ms']))

dec = [r['decode_tok_s'] for r in rows
       if isinstance(r['decode_tok_s'], (int, float)) and r['decode_tok_s'] > 0]
out = [r['out_tokens'] for r in rows if r['out_tokens']]
pre = [r['prefill_ms'] for r in rows if r['prefill_ms']]

print()
if dec:
    print('%s decode: n=%d  median %.2f tok/s  min %.2f  max %.2f  sd %.2f'
          % (label, len(dec), statistics.median(dec), min(dec), max(dec),
             statistics.pstdev(dec) if len(dec) > 1 else 0))
    print('%s output length median: %s tokens' % (label, statistics.median(out) if out else '?'))
    if pre:
        print('%s prefill median: %.0f ms' % (label, statistics.median(pre)))
else:
    print(label, 'no decode data -- check /metrics')

path = os.path.join(OUTDIR, 'bench-%s.json' % label)
with open(path, 'w', encoding='utf-8') as f:
    json.dump({'label': label, 'model': MODEL, 'base': BASE,
               'runs': runs, 'max_tokens': MAX_TOKENS, 'rows': rows}, f,
              ensure_ascii=False, indent=1)
print('saved:', path)
