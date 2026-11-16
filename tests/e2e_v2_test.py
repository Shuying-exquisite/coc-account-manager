# -*- coding: utf-8 -*-
"""第二轮优化端到端测试。

覆盖：主表锁定 / 设为起号时最后登录清零 / 结束起号回填当天 / 取消起号回填当天 /
      统计含起号账号 / JSON 导出。

用法：先起服务（默认 5000），再运行。可用环境变量 COC_TEST_PORT 改端口。
"""
import json
import os
import tempfile
import urllib.request
import urllib.error
from datetime import datetime

PORT = int(os.environ.get('COC_TEST_PORT', '5000'))
BASE = f"http://127.0.0.1:{PORT}"


def req(method, path, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            raw = resp.read().decode('utf-8')
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8')
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


def main():
    p = f = 0
    today = datetime.now().strftime('%Y-%m-%d')

    def check(label, cond, extra=''):
        nonlocal p, f
        if cond:
            p += 1
            print(f"  PASS  {label}")
        else:
            f += 1
            print(f"  FAIL  {label}  {extra}")

    st, _ = req('GET', '/api/statistics')
    check('服务可用', st == 200, f'got {st}')
    if st != 200:
        return False

    # 造两个普通账号（A 预置一个历史登录时间，用于验证"设为起号后清零"）
    st, a1 = req('POST', '/api/accounts', {'account_name': '起号测试A', 'account_id': 'R_A',
                                           'owner_type': '本人', 'platform': 'QQ',
                                           'town_hall_level': 10, 'last_login_date': '2026-01-01'})
    st, a2 = req('POST', '/api/accounts', {'account_name': '起号测试B', 'account_id': 'R_B',
                                           'owner_type': '本人', 'platform': 'QQ',
                                           'town_hall_level': 8, 'last_login_date': '2026-02-02'})
    id1, id2 = a1.get('id'), a2.get('id')
    check('造账号成功(含历史登录时间)', bool(id1 and id2), f'{a1} {a2}')
    if not (id1 and id2):
        return False

    st, s0 = req('GET', '/api/statistics')
    base_total = s0['total']

    # ---- 1) 设为起号：最后登录时间清零 ----
    st, _ = req('POST', '/api/raising/promote', {'id': id1, 'device_number': 'T1', 'target_th_level': 15})
    check('promote 成功', st == 200)
    st, acc1 = req('GET', f'/api/accounts/{id1}')
    check('设为起号后 最后登录时间已清零',
          acc1.get('last_login_date') in (None, ''), f"got {acc1.get('last_login_date')!r}")

    # ---- 2) 统计包含起号账号 ----
    st, s1 = req('GET', '/api/statistics')
    check('总账号数包含起号账号(未减少)', s1['total'] == base_total, f"base={base_total} now={s1['total']}")
    check('raising_count>=1', s1.get('raising_count', 0) >= 1, f"raising_count={s1.get('raising_count')}")

    # ---- 3) 主表锁定 ----
    st, r = req('PUT', f'/api/accounts/{id1}', {'account_name': '试图改名'})
    check('起号账号在主表禁止编辑(403)', st == 403, f'{st} {r}')
    check('锁定提示含"锁定"', isinstance(r, dict) and '锁定' in str(r.get('error', '')), f'{r}')
    st, r = req('DELETE', f'/api/accounts/{id1}')
    check('起号账号在主表禁止删除(403)', st == 403, f'{st} {r}')

    # ---- 4) 普通账号仍可编辑 ----
    st, r = req('PUT', f'/api/accounts/{id2}', {'account_name': 'B改名'})
    check('普通账号仍可编辑(200)', st == 200, f'{st} {r}')

    # ---- 5) 结束起号：回填当天日期 + 等级 + 解锁 ----
    st, r = req('POST', f'/api/raising/{id1}/finish', {})
    check('结束起号成功', st == 200, f'{st} {r}')
    st, acc = req('GET', f'/api/accounts/{id1}')
    check('结束后 最后登录时间=今天', acc.get('last_login_date') == today, f"got {acc.get('last_login_date')} want {today}")
    check('结束后 大本营等级=目标15', acc.get('town_hall_level') == 15, f"got {acc.get('town_hall_level')}")
    st, r = req('PUT', f'/api/accounts/{id1}', {'account_name': '解锁后改名'})
    check('结束起号后主表解锁可编辑(200)', st == 200, f'{st} {r}')

    # ---- 6) 取消起号：也回填当天日期 + 解锁 ----
    st, _ = req('POST', '/api/raising/promote', {'id': id2, 'device_number': 'T2', 'target_th_level': 16})
    check('B 设为起号成功', st == 200)
    st, acc2 = req('GET', f'/api/accounts/{id2}')
    check('B 设为起号后 最后登录时间已清零', acc2.get('last_login_date') in (None, ''), f"got {acc2.get('last_login_date')!r}")
    st, r = req('DELETE', f'/api/raising/{id2}')
    check('取消起号成功', st == 200, f'{st} {r}')
    st, acc2 = req('GET', f'/api/accounts/{id2}')
    check('取消起号后 最后登录时间=今天', acc2.get('last_login_date') == today, f"got {acc2.get('last_login_date')} want {today}")
    check('取消起号后 等级不变(8)', acc2.get('town_hall_level') == 8, f"got {acc2.get('town_hall_level')}")
    st, r = req('PUT', f'/api/accounts/{id2}', {'account_name': 'B解锁改名'})
    check('取消起号后主表解锁可编辑(200)', st == 200, f'{st} {r}')

    # ---- 7) JSON 导出 ----
    out = os.path.join(tempfile.gettempdir(), 'coc_e2e_export.json')
    if os.path.exists(out):
        os.remove(out)
    st, r = req('POST', '/api/export/json/file', {'path': out})
    check('JSON 导出接口成功', st == 200, f'{st} {r}')
    check('JSON 文件已生成', os.path.exists(out), out)
    if os.path.exists(out):
        with open(out, encoding='utf-8') as fp:
            payload = json.load(fp)
        check('JSON 含 accounts 数组', isinstance(payload.get('accounts'), list) and len(payload['accounts']) >= 2,
              f"len={len(payload.get('accounts', []))}")
        check('JSON 含 rentals / monthly_metrics / export_time',
              all(k in payload for k in ('rentals', 'monthly_metrics', 'export_time')))
        os.remove(out)

    # 清理
    req('DELETE', f'/api/accounts/{id1}')
    req('DELETE', f'/api/accounts/{id2}')

    print(f"\n结果: {p} 通过, {f} 失败")
    return f == 0


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
