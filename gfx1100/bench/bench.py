"""瑙ｇ爜閫熷害 A/B 鍩哄噯銆?
鍚屼竴鎻愮ず璇嶃€乼emperature 0銆佸浐瀹氳緭鍑洪暱搴︼紝杩炵画 N 娆★紝浠?/metrics 鍙栧紩鎿庤嚜鎶ョ殑
decode_tok_s锛堟帓闄ゆ帓闃熸椂闂达紝姣斿閽熸洿鍑嗭級銆?
鐢ㄦ硶: python bench.py <鏍囩> [娆℃暟]
杈撳嚭: E:\\Strata\\quant\\bench-<鏍囩>.json  + 鎺у埗鍙版憳瑕?"""
import json
import os
import statistics
import sys
import time
import urllib.request

BASE = os.environ.get('STRATA_BASE', 'http://127.0.0.1:8090')
KEY = os.environ.get('STRATA_API_KEY', '')
MODEL = 'qwen3.8-flash-next-unsloth-ud-iq4_xs-v31'

# 鍥哄畾鎻愮ず璇嶏細鎶€鏈€у唴瀹癸紝杈撳嚭绋冲畾锛岀害 1.5K token
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


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + KEY})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read().decode())


def metrics():
    req = urllib.request.Request(BASE + '/metrics', headers={'Authorization': 'Bearer ' + KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def once(stream=False):
    t0 = time.time()
    body = {'model': MODEL, 'messages': [{'role': 'user', 'content': PROMPT}],
            'max_tokens': MAX_TOKENS, 'temperature': 0}
    if stream:
        body['stream'] = True
        req = urllib.request.Request(BASE + '/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer ' + KEY})
        with urllib.request.urlopen(req, timeout=1800) as r:
            for _ in r:
                pass
        return time.time() - t0, None
    r = post('/v1/chat/completions', body)
    return time.time() - t0, r.get('usage', {})


print('[' + label + '] 棰勭儹 2 娆?...')
for _ in range(2):
    once()

rows = []
for i in range(runs):
    t_start = time.time()
    wall, usage = once()
    # 寮曟搸鑷姤鐨?per-request 鏁版嵁锛氭寜 time 鍙栥€屾湰娆¤姹傚紑濮嬩箣鍚庛€嶆渶鏂扮殑涓€鏉★紝
    # 涓嶈兘鐩存帴鍙?requests[-1]锛堢幆褰㈢紦鍐蹭笉淇濊瘉椤哄簭锛?    last = {}
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
    dms = last.get('decode_ms')
    outn = (usage or {}).get('completion_tokens') or last.get('output_tokens')
    # 澧欓挓浜ゅ弶鏍￠獙锛氬彧鎵ｉ櫎棰勫～鏃堕棿
    pre = (last.get('prompt_ms') or 0) / 1000.0
    wall_dec = round(outn / (wall - pre), 1) if outn and (wall - pre) > 0.2 else None
    row = {'wall_s': round(wall, 2), 'out_tokens': outn,
           'decode_tok_s': dec, 'decode_ms': dms,
           'prefill_ms': last.get('prompt_ms'),
           'first_token_s': last.get('first_engine_token_s'),
           'wall_derived': wall_dec}
    rows.append(row)
    print('  %2d  wall=%5.1fs 杈撳嚭=%4s decode=%6s tok/s (澧欓挓 %5s)  棰勫～=%7s ms'
          % (i + 1, row['wall_s'], row['out_tokens'], row['decode_tok_s'],
             row['wall_derived'], row['prefill_ms']))

dec = [r['decode_tok_s'] for r in rows if isinstance(r['decode_tok_s'], (int, float)) and r['decode_tok_s'] > 0]
out = [r['out_tokens'] for r in rows if r['out_tokens']]
print()
if dec:
    print('%s 瑙ｇ爜: n=%d  涓綅 %.2f tok/s  鏈€灏?%.2f  鏈€澶?%.2f  鏍囧噯宸?%.2f'
          % (label, len(dec), statistics.median(dec), min(dec), max(dec),
             statistics.pstdev(dec) if len(dec) > 1 else 0))
    print('%s 杈撳嚭闀垮害涓綅: %s token' % (label, statistics.median(out) if out else '?'))
else:
    print(label, '娌℃湁鍙栧埌 decode 鏁版嵁 鈥斺€?妫€鏌?/metrics')

with open(r'E:\Strata\quant\bench-' + label + '.json', 'w', encoding='utf-8') as f:
    json.dump({'label': label, 'runs': runs, 'max_tokens': MAX_TOKENS, 'rows': rows}, f,
              ensure_ascii=False, indent=1)
print('宸蹭繚瀛? E:\\Strata\\quant\\bench-' + label + '.json')
