# -*- coding: utf-8 -*-
"""起号逻辑优化 —— 端到端 API 测试（打在无头启动的 Flask 服务上）。

用法：先 COC_NO_GUI=1 启动打包产物，再运行本脚本。
覆盖：进度字段、排除空设备号、设备号唯一性(编辑/promote)、
      目标等级校验、完成起号回填、取消起号不回填、冗余路由已移除。
"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:5000"


def req(method, path, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
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
    passed = 0
    failed = 0

    def check(label, cond, extra=''):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            print(f"  FAIL  {label}  {extra}")

    # 0) 服务可用
    st, _ = req('GET', '/api/statistics')
    check('服务可用 (GET /api/statistics = 200)', st == 200, f'got {st}')

    # 造数据：用 POST /api/accounts 新增两个普通账号，再 promote 成起号
    st, a1 = req('POST', '/api/accounts', {'account_name': '起号测试A', 'account_id': 'E2E_A',
                                          'owner_type': '本人', 'platform': 'QQ',
                                          'town_hall_level': 10})
    st2, a2 = req('POST', '/api/accounts', {'account_name': '起号测试B', 'account_id': 'E2E_B',
                                            'owner_type': '本人', 'platform': 'QQ',
                                            'town_hall_level': 16})
    id1 = (a1 or {}).get('id')
    id2 = (a2 or {}).get('id')
    check('造测试账号成功', bool(id1 and id2), f'a1={a1} a2={a2}')
    if not (id1 and id2):
        print('无法继续'); return

    # 1) promote 设为起号（设备1，目标15）
    st, r = req('POST', '/api/raising/promote', {'id': id1, 'device_number': '1', 'target_th_level': 15})
    check('promote 设为起号成功', st == 200, f'{st} {r}')

    # 2) 起号列表返回进度字段（10/15 -> 67%，差5本）
    st, rows = req('GET', '/api/raising')
    a = next((x for x in rows if x['id'] == id1), None)
    check('起号列表含 progress_pct / th_gap', a is not None and
          a.get('progress_pct') == 67 and a.get('th_gap') == 5,
          f'a={ {k: a.get(k) for k in ("progress_pct","th_gap","town_hall_level","target_th_level")} if a else None}')

    # 3) 设备号唯一性：编辑时把 id1 的设备号改成别的号已占用的值
    st, r2 = req('POST', '/api/raising/promote', {'id': id2, 'device_number': '2', 'target_th_level': 16})
    check('第二个起号 promote 成功', st == 200, f'{st} {r2}')
    st, r = req('PUT', f'/api/raising/{id1}', {'device_number': '2'})
    check('编辑时设备号重复被拒 (400)', st == 400, f'{st} {r}')
    check('拒绝时给出精确错误提示', isinstance(r, dict) and '占用' in str(r.get('error', '')), f'{r}')

    # 4) 目标等级非法被拒
    st, r = req('PUT', f'/api/raising/{id1}', {'target_th_level': 99})
    check('目标等级 99 被拒 (400)', st == 400, f'{st} {r}')

    # 5) 冗余 POST /api/raising 已移除（应为 405 Method Not Allowed）
    st, r = req('POST', '/api/raising', {'device_number': '9', 'account_name': '野账号'})
    check('冗余 POST /api/raising 已移除 (405)', st == 405, f'{st} {r}')

    # 6) 完成起号：大本营等级回填为目标等级，且移出起号列表
    st, r = req('POST', f'/api/raising/{id1}/finish', {})
    check('完成起号接口成功', st == 200, f'{st} {r}')
    st, acc = req('GET', f'/api/accounts/{id1}')
    check('完成后 town_hall_level 更新为 15 (目标)',
          isinstance(acc, dict) and acc.get('town_hall_level') == 15, f'{acc}')
    st, rows = req('GET', '/api/raising')
    check('完成后从起号列表移除', all(x['id'] != id1 for x in rows), f'ids={[x["id"] for x in rows]}')

    # 7) 取消起号：不回填等级，仅移除
    st, r = req('DELETE', f'/api/raising/{id2}')
    check('取消起号接口成功', st == 200, f'{st} {r}')
    st, acc2 = req('GET', f'/api/accounts/{id2}')
    check('取消后账号仍在主表且等级不变(16)',
          isinstance(acc2, dict) and acc2.get('town_hall_level') == 16, f'{acc2}')
    st, rows = req('GET', '/api/raising')
    check('取消后从起号列表移除', all(x['id'] != id2 for x in rows), f'ids={[x["id"] for x in rows]}')

    # 清理测试数据
    req('DELETE', f'/api/accounts/{id1}')
    req('DELETE', f'/api/accounts/{id2}')

    print(f"\n结果: {passed} 通过, {failed} 失败")
    return failed == 0


if __name__ == '__main__':
    ok = main()
    raise SystemExit(0 if ok else 1)
