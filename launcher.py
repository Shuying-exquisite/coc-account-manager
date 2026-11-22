import os
import sys
import time
import socket
import threading
import marshal
import types
import traceback

# These stdlib modules are imported by the exec-loaded .pyc modules below,
# so we import them here to make sure PyInstaller bundles them.
import sqlite3  # noqa: F401
import datetime  # noqa: F401
import webbrowser  # noqa: F401
from flask import request, jsonify  # noqa: F401

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPMODS_DIR = os.path.join(BASE_DIR, 'appmods')

# pythonnet / clr_loader / clr.py are shipped as REAL files next to the exe
# (PyInstaller freezes modules into its archive, which breaks their __file__
# based lookup of Python.Runtime.dll / ClrLoader.dll). Make sure the exe
# directory is importable so `import clr` resolves to the on-disk packages.
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _load_module(name, path):
    """加载 appmods 下的模块。

    桌面版（PyInstaller 冻结）：直接读 .pyc 的 code object（跳过 16 字节头再
    marshal 反序列化），绕过 pyc 校验，与打包前行为完全一致。

    Web 服务版（COC_WEB=1，部署在服务器上、宿主 Python 版本可能与构建机不同）：
    改用 .py 源码加载，避免 .pyc 版本不兼容（.pyc 的 magic 必须与解释器一致）。
    """
    pyc = path if path.endswith('.pyc') else (path + '.pyc')
    py = (path[:-4] if path.endswith('.pyc') else path) + '.py'

    use_source = bool(os.environ.get('COC_WEB')) and os.path.exists(py)
    if use_source or not os.path.exists(pyc):
        if not os.path.exists(py):
            raise FileNotFoundError('找不到模块: %s (也没有 .pyc)' % py)
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, py)
        mod = importlib.util.module_from_spec(spec)
        mod.__file__ = py
        mod.__package__ = ''
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    with open(pyc, 'rb') as f:
        data = f.read()
    code = marshal.loads(data[16:])
    mod = types.ModuleType(name)
    mod.__file__ = pyc
    mod.__package__ = ''
    mod.__loader__ = None
    sys.modules[name] = mod
    exec(code, mod.__dict__)
    return mod


def _setup_web_auth(flask_app):
    """Web 公网入口的 HTTP Basic 口令验证。口令从环境变量读取，绝不写死。"""
    import secrets as _secrets
    from flask import Response, session, redirect, request as _rq, render_template_string
    from datetime import timedelta

    _user = os.environ.get('COC_WEB_USER', 'admin')
    _pass = os.environ.get('COC_WEB_PASS', '')
    if not _pass:
        raise RuntimeError('COC_WEB_PASS 未设置，拒绝以无口令方式暴露公网')

    # session 签名密钥：优先用环境变量（重启后登录态不失效），否则每次随机生成
    flask_app.secret_key = os.environ.get('COC_WEB_SECRET') or _secrets.token_hex(32)
    flask_app.permanent_session_lifetime = timedelta(days=7)

    _LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 · 部落冲突账号管理</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
 background:radial-gradient(circle at 50% 0%,#1e2a4a 0%,#16213e 45%,#1a1a2e 100%);
 font-family:"Microsoft YaHei",system-ui,-apple-system,sans-serif;color:#e8e8e8;padding:20px}
.card{width:370px;max-width:100%;padding:36px 30px 30px;
 background:linear-gradient(160deg,rgba(30,42,74,.97),rgba(22,33,62,.97));
 border:1px solid rgba(255,215,0,.22);border-radius:18px;
 box-shadow:0 20px 55px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.04)}
.logo{font-size:42px;text-align:center;line-height:1;margin-bottom:12px;
 filter:drop-shadow(0 4px 12px rgba(255,215,0,.35))}
h1{font-size:18px;text-align:center;font-weight:700;letter-spacing:.5px}
.sub{text-align:center;font-size:12px;color:#6c6c8a;margin:8px 0 26px}
label{display:block;font-size:12px;color:#a0a0b8;margin:16px 0 7px}
input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.12);
 background:rgba(0,0,0,.3);color:#e8e8e8;font-size:14px;outline:none;transition:.18s}
input:focus{border-color:#ffd700;box-shadow:0 0 0 3px rgba(255,215,0,.14);background:rgba(0,0,0,.42)}
button{width:100%;margin-top:26px;padding:13px;border:none;border-radius:10px;cursor:pointer;
 font-size:15px;font-weight:700;color:#1a1a2e;letter-spacing:2px;
 background:linear-gradient(135deg,#ffd700,#c9a700);transition:.18s}
button:hover{filter:brightness(1.09);transform:translateY(-1px)}
button:active{transform:translateY(0)}
.err{margin-top:16px;padding:10px 13px;border-radius:9px;font-size:13px;
 background:rgba(231,76,60,.16);color:#ff7b6b;border:1px solid rgba(231,76,60,.32)}
.foot{text-align:center;font-size:11px;color:#4a4a66;margin-top:22px}
</style></head>
<body>
<form class="card" method="post" action="/login">
 <div class="logo">⚔️</div>
 <h1>部落冲突账号管理</h1>
 <div class="sub">请登录后使用</div>
 <label>账号</label>
 <input name="username" autocomplete="username" autofocus>
 <label>口令</label>
 <input name="password" type="password" autocomplete="current-password">
 <button type="submit">登 录</button>
 {% if err %}<div class="err">{{ err }}</div>{% endif %}
 <div class="foot">仅限本人使用 · 请勿分享链接</div>
</form>
</body></html>"""

    def _safe_next(target):
        # 只允许站内相对路径，防开放重定向
        if target and target.startswith('/') and not target.startswith('//') and not target.startswith('/login'):
            return target
        return '/'

    @flask_app.route('/login', methods=['GET', 'POST'])
    def _coc_login():
        err = ''
        if _rq.method == 'POST':
            u = _rq.form.get('username', '')
            p = _rq.form.get('password', '')
            if (_secrets.compare_digest(u, _user) and _secrets.compare_digest(p, _pass)):
                session.clear()
                session['coc_auth'] = True
                session.permanent = True
                return redirect(_safe_next(_rq.args.get('next')))
            err = '账号或口令错误'
        return render_template_string(_LOGIN_HTML, err=err)

    @flask_app.route('/logout')
    def _coc_logout():
        session.clear()
        return redirect('/login')

    @flask_app.before_request
    def _coc_auth_guard():
        path = _rq.path
        # 登录页与静态资源放行
        if path == '/login' or path == '/logout' or path.startswith('/static/'):
            return None
        if session.get('coc_auth') is True:
            return None
        # 页面请求跳登录页；API 请求返回 401 JSON，避免前端拿到 HTML
        if path.startswith('/api/'):
            return Response('{"error":"未登录"}', 401, {'Content-Type': 'application/json'})
        return redirect('/login?next=' + path)


def _wait_for_port(host, port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    # Preload local modules so that app.pyc's `import database` /
    # `import import_data` resolve to the originals (never re-implemented,
    # so the database schema and business logic stay 100% intact).
    db_mod = _load_module('database', os.path.join(APPMODS_DIR, 'database.pyc'))
    _load_module('import_data', os.path.join(APPMODS_DIR, 'import_data.pyc'))
        # --- Robust Excel import (monkey-patch the frozen import_data.import_data) ---
    # Implemented with the standard library ONLY (zipfile + xml.etree) so it
    # works inside the PyInstaller bundle without openpyxl/lxml C-extension
    # crashes. This mirrors the export path which also uses raw zipfile+xml.
    import io as _io
    import zipfile
    from xml.etree import ElementTree as _ET

    _NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    _RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

    def _coc_to_int(v):
        if v is None or v == '':
            return 0
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        try:
            return int(float(str(v).strip()))
        except Exception:
            return 0

    def _coc_convert_date(v):
        if v is None or v == '':
            return None
        if isinstance(v, (int, float)):
            if v > 10000:
                s = str(int(v))
                if len(s) == 8:
                    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
                return str(v)
            try:
                _base = datetime.datetime(1899, 12, 30)
                return (_base + datetime.timedelta(days=int(v))).strftime('%Y-%m-%d')
            except Exception:
                return str(v)
        if hasattr(v, 'strftime'):
            return v.strftime('%Y-%m-%d')
        s = str(v).strip()
        for _f in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
            try:
                return datetime.datetime.strptime(s, _f).strftime('%Y-%m-%d')
            except Exception:
                pass
        return s

    def _xlsx_col_to_idx(col):
        idx = 0
        for ch in col.upper():
            if 'A' <= ch <= 'Z':
                idx = idx * 26 + (ord(ch) - 64)
        return idx - 1

    def _xlsx_read_sheets(raw):
        z = zipfile.ZipFile(_io.BytesIO(raw))
        names = z.namelist()
        shared = []
        if 'xl/sharedStrings.xml' in names:
            try:
                root = _ET.fromstring(z.read('xl/sharedStrings.xml'))
                for si in root.iter(f'{_NS}si'):
                    shared.append(''.join(t.text or '' for t in si.iter(f'{_NS}t')))
            except Exception:
                pass
        sheets = []
        if 'xl/workbook.xml' in names:
            wb = _ET.fromstring(z.read('xl/workbook.xml'))
            for s in wb.iter(f'{_NS}sheet'):
                sheets.append((s.get('name'), s.get(f'{_RNS}id')))
        rels = {}
        if 'xl/_rels/workbook.xml.rels' in names:
            rroot = _ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            for rel in rroot:
                rels[rel.get('Id')] = rel.get('Target')
        out = {}
        for nm, rid in sheets:
            tgt = rels.get(rid, '')
            if not tgt:
                continue
            tgt = tgt.lstrip('/')
            path = tgt if tgt.startswith('xl/') else ('xl/' + tgt)
            try:
                data = z.read(path)
            except Exception:
                continue
            out[nm] = _xlsx_parse_sheet(data, shared)
        return out

    def _xlsx_parse_sheet(data, shared):
        root = _ET.fromstring(data)
        rows = []
        for row in root.iter(f'{_NS}row'):
            cells = {}
            maxc = -1
            for c in row.iter(f'{_NS}c'):
                ref = c.get('r') or ''
                col = ''.join(ch for ch in ref if ch.isalpha())
                if not col:
                    continue
                ci = _xlsx_col_to_idx(col)
                t = c.get('t')
                v = c.find(f'{_NS}v')
                isel = c.find(f'{_NS}is')
                val = None
                if t == 's' and v is not None and v.text is not None:
                    try:
                        val = shared[int(v.text)]
                    except Exception:
                        val = None
                elif t == 'inlineStr' and isel is not None:
                    val = ''.join(tt.text or '' for tt in isel.iter(f'{_NS}t'))
                elif v is not None:
                    val = v.text
                cells[ci] = val
                if ci > maxc:
                    maxc = ci
            rows.append([cells.get(i) for i in range(maxc + 1)])
        return rows

    _STD_SHEETS = {
        '本人QQ号': ('本人', 'QQ'),
        '本人微信号': ('本人', '微信'),
        '朋友微信号': ('朋友', '微信'),
        '朋友QQ号': ('朋友', 'QQ'),
    }
    _ACCOUNT_HEADER_MAP = {
        '账号名称': 'account_name', '账号': 'account_id', '账号id': 'account_id',
        '账号ID': 'account_id', '账号归属': 'owner_name', '归属人': 'owner_name',
        '归属': 'owner_name', '绑定详情': 'binding_detail', '绑定': 'binding_detail',
        '最后登陆时间': 'last_login', '最后登录时间': 'last_login', '最后登录': 'last_login',
        '登陆时间': 'last_login', '登陆': 'last_login', '登录': 'last_login',
        '大本营等级': 'th_level', '大本营': 'th_level', '等级': 'th_level',
        '目标等级': 'target_th_level', '目标': 'target_th_level',
        '起号设备': 'device_number', '设备号': 'device_number', '设备': 'device_number',
    }
    _RENTAL_HEADER_MAP = {
        '账号归属': 'owner_name', '归属人': 'owner_name', '归属': 'owner_name',
        '账号名称': 'account_name', '名称': 'account_name', '名字': 'account_name',
        '绑定详情': 'binding_detail', '绑定': 'binding_detail',
        '账号': 'account_id', '账号id': 'account_id', '账号ID': 'account_id',
        '起租日': 'start_date', '开始日': 'start_date', '开始日期': 'start_date',
        '租售时长': 'duration_days', '时长': 'duration_days', '租期': 'duration_days',
        '结束日': 'end_date', '到期日': 'end_date', '结束日期': 'end_date',
    }
    # Standard account export layout (7 columns)
    _ACCOUNT_POS_FALLBACK = {0: 'owner_name', 1: 'account_name', 2: 'binding_detail',
                             3: 'account_id', 4: 'last_login', 5: 'th_level'}
    # Rental export layout from image2 (7 columns)
    _RENTAL_POS_FALLBACK = {0: 'owner_name', 1: 'account_name', 2: 'binding_detail',
                            3: 'account_id', 4: 'start_date', 5: 'duration_days', 6: 'end_date'}

    def _detect_header(rows, keywords):
        for i, r in enumerate(rows[:10]):
            score = 0
            for c in r:
                if c is not None and str(c).strip() in keywords:
                    score += 1
            if score >= 2:
                return i
        return None

    def _build_colmap(header, mapping):
        colmap = {}
        for ci, h in enumerate(header):
            if h is None:
                continue
            key = mapping.get(str(h).strip())
            if key:
                colmap[key] = ci
        return colmap

    def _coc_robust_import_data(file_bytes=None, file_path=None):
        try:
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    raw = f.read()
            elif file_bytes:
                raw = file_bytes
            else:
                return (False, 0, '未提供文件')
            try:
                _sheets = _xlsx_read_sheets(raw)
            except Exception as _e:
                return (False, 0, f'无法读取Excel（若为.xls旧格式请另存为.xlsx）：{_e}')
        except Exception as _e:
            return (False, 0, f'无法读取Excel：{_e}')
        _conn = db_mod.get_db()
        _imported_accounts = 0
        _imported_rentals = 0
        for _sname, _rows in _sheets.items():
            if not _rows:
                continue
            if _sname == '账号出租':
                # --- import into account_rentals ---
                _header_idx = _detect_header(_rows, set(_RENTAL_HEADER_MAP.keys()))
                if _header_idx is not None:
                    _start = _header_idx + 1
                    _header = _rows[_header_idx]
                else:
                    if len(_rows) > 1 and all(c is None for c in _rows[0]):
                        _start = 2
                        _header = _rows[1] if len(_rows) > 1 else []
                    else:
                        _start = 1
                        _header = _rows[0] if _rows else []
                _colmap = _build_colmap(_header, _RENTAL_HEADER_MAP)
                def _rval(_key, _row):
                    _ci = _colmap.get(_key)
                    if _ci is None:
                        for _pos, _k in _RENTAL_POS_FALLBACK.items():
                            if _k == _key and _pos < len(_row):
                                _ci = _pos
                                break
                    if _ci is None or _ci >= len(_row):
                        return None
                    return _row[_ci]
                for _r in _rows[_start:]:
                    if not _r or all(c is None for c in _r):
                        continue
                    _an = str(_rval('account_name', _r) or '').strip()
                    _aid = str(_rval('account_id', _r) or '').strip()
                    if not _an and not _aid:
                        continue
                    _on = str(_rval('owner_name', _r) or '').strip()
                    _bd = str(_rval('binding_detail', _r) or '').strip()
                    _sd = _coc_convert_date(_rval('start_date', _r))
                    _dd = _coc_to_int(_rval('duration_days', _r))
                    _ed = _coc_convert_date(_rval('end_date', _r))
                    # Try to link to existing account
                    _acc_id = None
                    if _aid:
                        _row2 = _conn.execute('SELECT id FROM accounts WHERE account_id = ? LIMIT 1', (_aid,)).fetchone()
                        if _row2:
                            _acc_id = _row2[0]
                    if _acc_id is None and _an:
                        _row2 = _conn.execute('SELECT id FROM accounts WHERE account_name = ? LIMIT 1', (_an,)).fetchone()
                        if _row2:
                            _acc_id = _row2[0]
                    _conn.execute(
                        "INSERT INTO account_rentals (account_id, owner_name, account_name, binding_detail, "
                        "account_id_text, start_date, duration_days, end_date) VALUES (?,?,?,?,?,?,?,?)",
                        (_acc_id, _on, _an, _bd, _aid, _sd, _dd, _ed))
                    _imported_rentals += 1
                continue
            # --- standard account sheets ---
            _ot, _pf = _STD_SHEETS.get(_sname, (None, None))
            _is_raising = (_sname == '起号')
            _account_keywords = set(_ACCOUNT_HEADER_MAP.keys())
            _header_idx = _detect_header(_rows, _account_keywords)
            if _header_idx is not None:
                _start = _header_idx + 1
                _header = _rows[_header_idx]
            else:
                if len(_rows) > 1 and all(c is None for c in _rows[0]):
                    _start = 2
                    _header = _rows[1] if len(_rows) > 1 else []
                else:
                    _start = 1
                    _header = _rows[0] if _rows else []
            _colmap = _build_colmap(_header, _ACCOUNT_HEADER_MAP)
            def _aval(_key, _row):
                _ci = _colmap.get(_key)
                if _ci is None:
                    for _pos, _k in _ACCOUNT_POS_FALLBACK.items():
                        if _k == _key and _pos < len(_row):
                            _ci = _pos
                            break
                if _ci is None or _ci >= len(_row):
                    return None
                return _row[_ci]
            for _r in _rows[_start:]:
                if not _r or all(c is None for c in _r):
                    continue
                _an = str(_aval('account_name', _r) or '').strip()
                _aid = str(_aval('account_id', _r) or '').strip()
                if not _an and not _aid:
                    continue
                _on = str(_aval('owner_name', _r) or '').strip() or (_ot or '其他')
                _bd = str(_aval('binding_detail', _r) or '').strip()
                _ll = _coc_convert_date(_aval('last_login', _r))
                _th = _coc_to_int(_aval('th_level', _r))
                _target = _coc_to_int(_aval('target_th_level', _r))
                # 只有"起号" sheet 才写入 device_number；普通账号 sheet 一律 NULL，
                # 避免 database.get_raising_accounts 的 WHERE device_number IS NOT NULL
                # 把空字符串也当成起号账号显示出来。
                if _is_raising:
                    _device = str(_aval('device_number', _r) or '').strip()
                    if not _device:
                        _device = '1'
                else:
                    _device = None
                _notes = ''
                _conn.execute(
                    "INSERT INTO accounts (owner_type, platform, owner_name, account_name, binding_detail, "
                    "account_id, last_login_date, town_hall_level, target_th_level, device_number, notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (_ot or '其他', _pf or '其他', _on, _an, _bd, _aid, _ll, _th, _target, _device, _notes))
                _imported_accounts += 1
        _conn.commit()
        _total = _imported_accounts + _imported_rentals
        _msg = f"成功导入 {_total} 条记录"
        if _imported_accounts:
            _msg += f"（账户 {_imported_accounts}"
            if _imported_rentals:
                _msg += f"，出租 {_imported_rentals}）"
            else:
                _msg += "）"
        elif _imported_rentals:
            _msg += f"（出租 {_imported_rentals}）"
        return (True, _total, _msg)

    sys.modules['import_data'].import_data = _coc_robust_import_data


    # Importing app.pyc as module 'app' (not '__main__') means its own
    # `if __name__ == '__main__': app.run(...)` startup block is skipped,
    # and we control the server + window ourselves.
    app_mod = _load_module('app', os.path.join(APPMODS_DIR, 'app.pyc'))
    app = app_mod.app

    # --- 覆盖起号编辑路由，给出精确的错误提示 -----------------------------
    # app.pyc 里 api_update_raising_account 把错误写死成 404"未找到起号账户"，
    # 无法表达"设备号重复/等级非法"。通过替换 Flask 的 view_functions 映射
    # （不重复注册路由）来复用新的 database.update_raising_account 校验逻辑。
    def _coc_update_raising_view(account_id):
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({'error': '请求体不能为空'}), 400
        dev = data.get('device_number')
        if dev not in (None, ''):
            dev = str(dev).strip()
            _conn = db_mod.get_db()
            _dup = _conn.execute(
                'SELECT id FROM accounts WHERE device_number = ? AND id != ?',
                (dev, account_id),
            ).fetchone()
            _conn.close()
            if _dup:
                return jsonify({'error': f'起号设备「{dev}」已被其他账号占用，不可重复'}), 400
        target = data.get('target_th_level')
        if target not in (None, ''):
            try:
                _tv = int(target)
                if _tv < 0:
                    return jsonify({'error': '目标等级须为非负整数'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': '目标等级须为数字'}), 400
        # 起号序号：可编辑但不可与其他起号重复
        seq = data.get('raising_seq')
        if seq not in (None, ''):
            try:
                _sq = int(seq)
            except (ValueError, TypeError):
                return jsonify({'error': '序号须为数字'}), 400
            if _sq < 0:
                return jsonify({'error': '序号不能为负数'}), 400
            _conn = db_mod.get_db()
            _dupq = _conn.execute(
                "SELECT id, account_name FROM accounts WHERE raising_seq = ? AND id != ? "
                "AND device_number IS NOT NULL AND device_number != ''",
                (_sq, account_id),
            ).fetchone()
            _conn.close()
            if _dupq:
                _nm = ''
                try:
                    _nm = _dupq['account_name'] or ''
                except Exception:
                    try:
                        _nm = _dupq[1] or ''
                    except Exception:
                        _nm = ''
                return jsonify({'error': f'序号 {_sq} 已被「{_nm}」占用，请换一个'}), 400
        ok = db_mod.update_raising_account(account_id, data)
        if ok:
            return jsonify({'message': '起号数据已同步到账号主表'})
        return jsonify({'error': '起号记录不存在或没有可更新的字段'}), 404

    app.view_functions['api_update_raising_account'] = _coc_update_raising_view

    # --- 起号账号在主表锁定：直接改/删账号的接口对起号账号一律拒绝 ---------
    # 前端已把起号账号的编辑/删除按钮置灰，这里在后端再兜一层，
    # 防止绕过前端（直接调 API / 并发操作）改动起号账号。起号账号的修改
    # 只能走 PUT /api/raising/<id>（起号管理），或先"结束起号"解锁。
    def _coc_is_account_locked(account_id):
        _conn = db_mod.get_db()
        try:
            _r = _conn.execute(
                'SELECT device_number FROM accounts WHERE id = ?', (account_id,)
            ).fetchone()
        finally:
            _conn.close()
        if _r is None:
            return None
        try:
            _dv = _r['device_number']
        except (TypeError, IndexError, KeyError):
            _dv = _r[0]
        return _dv is not None and str(_dv).strip() != ''

    def _coc_update_account_view(account_id):
        if _coc_is_account_locked(account_id):
            return jsonify({'error': '该账号已加入起号管理，已在账号主表锁定。请到「起号」中编辑'}), 403
        data = request.get_json(silent=True) or {}
        db_mod.update_account(account_id, data)
        return jsonify({'message': '修改成功'})

    def _coc_delete_account_view(account_id):
        if _coc_is_account_locked(account_id):
            return jsonify({'error': '该账号已加入起号管理，已在账号主表锁定。请先在「起号」中结束起号'}), 403
        db_mod.delete_account(account_id)
        return jsonify({'message': '删除成功'})

    app.view_functions['api_update_account'] = _coc_update_account_view
    app.view_functions['api_delete_account'] = _coc_delete_account_view

    # --- 禁用「清空数据」接口（2026-11-16 用户要求去掉按钮，后端一并停用）----
    # 公网部署下保留该接口风险高（登录后一个 POST 就能清空全部账号），
    # 前端按钮已移除，这里在后端直接拒绝，双保险。
    def _coc_clear_disabled():
        return jsonify({'error': '清空数据功能已停用'}), 403

    app.view_functions['api_clear'] = _coc_clear_disabled

    # --- Extend the frozen backend with 起号 add / delete -------------------
    # The original `app.pyc` only exposed GET / PUT on /api/raising, so the
    # 起号管理 UI had no way to create or remove a raising account. We add
    # those two routes here WITHOUT touching the frozen bytecode: a raising
    # account is simply an `accounts` row whose `device_number` is set, so we
    # reuse the original db.add_account / db.delete_account helpers (which keep
    # all schema / logging / business logic intact).
    def _device_number_taken(device_number, exclude_id=None):
        """起号设备在 accounts 表中必须唯一。"""
        if not device_number:
            return False
        device_number = str(device_number).strip()
        conn = db_mod.get_db()
        if exclude_id is None:
            cur = conn.execute(
                'SELECT COUNT(*) FROM accounts WHERE device_number = ?',
                (device_number,),
            )
        else:
            cur = conn.execute(
                'SELECT COUNT(*) FROM accounts WHERE device_number = ? AND id != ?',
                (device_number, int(exclude_id)),
            )
        cnt = cur.fetchone()[0]
        conn.close()
        return cnt > 0

    # 起号新增统一走 /api/raising/promote：从账号主表选取已有账号，
    # 只给它打 device_number 标记。已移除冗余的 POST /api/raising
    # （它会 new 一个不属于任何 sheet 分类的"野账号"，且前端并无新增入口）。

    @app.route('/api/raising/<int:rid>/finish', methods=['POST'])
    def api_finish_raising(rid):
        # 结束起号：把账号移出起号列表（清空 device_number），并把目标大本营
        # 等级(target_th_level)回填进主表的大本营等级(town_hall_level)，账号本身保留。
        try:
            conn = db_mod.get_db()
            cur = conn.execute(
                'SELECT account_name FROM accounts WHERE id = ?', (rid,)
            )
            row = cur.fetchone()
            if row is None:
                conn.close()
                return jsonify({'error': '起号记录不存在'}), 404
            # 结束起号时：清设备号（解锁）、大本营等级回填为目标等级、
            # 最后登录时间记为结束当天（精确到日期 YYYY-MM-DD）。
            _today = datetime.datetime.now().strftime('%Y-%m-%d')
            conn.execute(
                'UPDATE accounts SET device_number = NULL, '
                'town_hall_level = COALESCE(target_th_level, town_hall_level), '
                'last_login_date = ? '
                'WHERE id = ?', (_today, rid)
            )
            conn.commit()
            conn.close()
            try:
                name = row[0] if row else ''
                db_mod.log_operation('结束起号', 'account', rid, f'结束起号: {name}')
            except Exception:
                pass
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500
        return jsonify({'message': '已结束起号（账号与目标等级保留在主表）'}), 200

    @app.route('/api/raising/<int:rid>', methods=['DELETE'])
    def api_delete_raising(rid):
        # IMPORTANT: removing a 起号 record must NOT delete the underlying
        # account. A raising record is simply an `accounts` row whose
        # `device_number` is set (see get_raising_accounts's
        # `device_number IS NOT NULL` filter), so "cancelling" a raising
        # record only clears that flag and leaves the account in the main
        # table. We deliberately do NOT call db.delete_account here.
        try:
            conn = db_mod.get_db()
            cur = conn.execute(
                'SELECT account_name FROM accounts WHERE id = ?', (rid,)
            )
            row = cur.fetchone()
            # 取消起号：清设备号（解锁），最后登录时间记为取消当天（精确到日期）。
            _today = datetime.datetime.now().strftime('%Y-%m-%d')
            conn.execute(
                'UPDATE accounts SET device_number = NULL, last_login_date = ? WHERE id = ?',
                (_today, rid)
            )
            conn.commit()
            conn.close()
            try:
                name = row[0] if row else ''
                db_mod.log_operation('取消起号', 'account', rid, f'取消起号: {name}')
            except Exception:
                pass
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500
        return jsonify({'message': '已取消起号（账号保留在主表中）'}), 200

    @app.route('/api/raising/promote', methods=['POST'])
    def api_promote_raising():
        # "新增起号" should pick an EXISTING account from the main table and
        # turn it into a raising account by setting its `device_number`
        # (raising records == accounts rows with device_number IS NOT NULL).
        # We do NOT create a duplicate row.
        data = request.get_json(force=True, silent=True) or {}
        acc_id = data.get('id')
        device_number = data.get('device_number')
        if not acc_id or not device_number:
            return jsonify({'error': '请选择账号并填写起号设备'}), 400
        if _device_number_taken(device_number):
            return jsonify({'error': f'起号设备 {device_number} 已存在，不可重复'}), 400
        # 目标等级合法性校验（非负整数，不设上限，留空表示不设）
        target_val = data.get('target_th_level')
        if target_val not in (None, ''):
            try:
                _tv = int(target_val)
                if _tv < 0:
                    return jsonify({'error': '目标等级须为非负整数'}), 400
                target_val = _tv
            except (ValueError, TypeError):
                return jsonify({'error': '目标等级须为数字'}), 400
        try:
            conn = db_mod.get_db()
            cur = conn.execute(
                'SELECT account_name FROM accounts WHERE id = ?', (int(acc_id),)
            )
            row = cur.fetchone()
            if row is None:
                conn.close()
                return jsonify({'error': '账号不存在'}), 404
            # 设为起号时：最后登录时间在主表清零（起号期间以"结束/取消起号"当天为准）。
            conn.execute(
                'UPDATE accounts SET device_number = ?, target_th_level = ?, '
                'last_login_date = NULL WHERE id = ?',
                (str(device_number).strip(), target_val, int(acc_id)),
            )
            conn.commit()
            conn.close()
            try:
                name = row[0] if row else ''
                db_mod.log_operation(
                    '设为起号', 'account', int(acc_id), f'设为起号: {name}'
                )
            except Exception:
                pass
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500
        return jsonify({'message': '已将账号设为起号'}), 200

    # The original entry point called init_db() before app.run(); do the
    # same so the schema exists. CREATE TABLE IF NOT EXISTS keeps it safe.
    db_mod.init_db()

    # 修复历史脏数据：早期导入/部分写入可能把普通账号的 device_number 存成空字符串，
    # 而 database.get_raising_accounts 只判断 IS NOT NULL，导致普通账号误入起号管理。
    try:
        _conn = db_mod.get_db()
        _conn.execute("UPDATE accounts SET device_number = NULL WHERE device_number = ''")
        _conn.commit()
        _conn.close()
    except Exception:
        pass

    # 仪表盘统计：统计【全部账号】，包含已加入起号管理的账号。
    # 起号只是给账号打一个设备号标记并临时锁定主表编辑，账号本身仍是真实存在的账号，
    # 因此总账号数与各维度分布都必须把它算进去（2026-11-16 用户明确要求）。
    def _coc_get_statistics():
        conn = db_mod.get_db()
        stats = {}
        stats['total'] = conn.execute('SELECT COUNT(*) as c FROM accounts').fetchone()['c']
        stats['by_platform'] = {
            'QQ': conn.execute(
                "SELECT COUNT(*) as c FROM accounts WHERE platform='QQ'"
            ).fetchone()['c'],
            '微信': conn.execute(
                "SELECT COUNT(*) as c FROM accounts WHERE platform='微信'"
            ).fetchone()['c'],
        }
        stats['by_owner_type'] = {
            '本人': conn.execute(
                "SELECT COUNT(*) as c FROM accounts WHERE owner_type='本人'"
            ).fetchone()['c'],
            '朋友': conn.execute(
                "SELECT COUNT(*) as c FROM accounts WHERE owner_type='朋友'"
            ).fetchone()['c'],
        }
        th_rows = conn.execute(
            'SELECT town_hall_level, COUNT(*) as c FROM accounts '
            'GROUP BY town_hall_level ORDER BY town_hall_level'
        ).fetchall()
        stats['by_th_level'] = {str(r['town_hall_level']): r['c'] for r in th_rows}
        owner_rows = conn.execute(
            'SELECT owner_name, COUNT(*) as c FROM accounts '
            'GROUP BY owner_name ORDER BY c DESC'
        ).fetchall()
        stats['by_owner'] = {r['owner_name']: r['c'] for r in owner_rows}
        max_th = conn.execute('SELECT MAX(town_hall_level) as m FROM accounts').fetchone()['m']
        stats['max_th'] = max_th or 0
        avg_th = conn.execute('SELECT AVG(town_hall_level) as a FROM accounts').fetchone()['a']
        stats['avg_th'] = round(avg_th, 1) if avg_th else 0
        stats['rental_count'] = conn.execute(
            'SELECT COUNT(*) as c FROM account_rentals'
        ).fetchone()['c']
        # 起号中的数量（仅作参考，已包含在 total 内，不额外扣减）
        stats['raising_count'] = conn.execute(
            "SELECT COUNT(*) as c FROM accounts WHERE device_number IS NOT NULL AND device_number != ''"
        ).fetchone()['c']
        conn.close()
        return stats

    db_mod.get_statistics = _coc_get_statistics
    # app.pyc 用 `from database import get_statistics` 把函数直接绑定进自己的
    # 命名空间（api_statistics 里是 LOAD_GLOBAL get_statistics），只 patch
    # db_mod.get_statistics 对路由不生效。必须同时 patch app_mod.get_statistics。
    app_mod.get_statistics = _coc_get_statistics

    # ==================== 导出 JSON（替代 Excel 导出） ====================
    @app.route('/api/export/json/dialog', methods=['GET'])
    def api_export_json_dialog():
        # 弹出系统"另存为"对话框，让用户选择 JSON 保存位置。
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            initial = '部落冲突账号_{}.json'.format(
                datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            )
            path = filedialog.asksaveasfilename(
                parent=root,
                title='导出 JSON 数据',
                initialfile=initial,
                defaultextension='.json',
                filetypes=[('JSON 文件', '*.json'), ('所有文件', '*.*')],
            )
            root.destroy()
            if not path:
                return jsonify({'cancelled': True}), 200
            return jsonify({'path': path}), 200
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500

    @app.route('/api/export/json/file', methods=['POST'])
    def api_export_json_file():
        # 导出全部数据为 JSON：账号（含起号账号）、出租记录、月度指标。
        try:
            import json as _json
            conn = db_mod.get_db()

            def _dump(sql):
                try:
                    return [dict(r) for r in conn.execute(sql).fetchall()]
                except Exception:
                    return []

            accounts = _dump('SELECT * FROM accounts ORDER BY id')
            rentals = _dump('SELECT * FROM account_rentals ORDER BY id')
            metrics = _dump('SELECT * FROM monthly_metrics ORDER BY id')
            conn.close()

            payload = {
                'export_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_accounts': len(accounts),
                'total_rentals': len(rentals),
                'accounts': accounts,
                'rentals': rentals,
                'monthly_metrics': metrics,
            }

            data = request.get_json(force=True, silent=True) or {}
            out = data.get('path')
            if not out:
                ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                out = os.path.join(BASE_DIR, '部落冲突账号_{}.json'.format(ts))
            else:
                out = str(out)
                if not out.lower().endswith('.json'):
                    out += '.json'

            with open(out, 'w', encoding='utf-8') as f:
                _json.dump(payload, f, ensure_ascii=False, indent=2)
            try:
                os.startfile(out)
            except Exception:
                pass
            return jsonify({'path': out, 'name': os.path.basename(out)})
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500

    @app.route('/api/export/json/download', methods=['GET'])
    def api_export_json_download():
        # Web 版导出：直接以附件流返回，由浏览器下载到用户本机。
        # 容器内没有 Tk 图形库（libtk8.6.so），无法弹服务端“另存为”对话框，
        # 所以 Web 版必须走这条「浏览器下载」路径。
        try:
            import json as _json
            from flask import Response
            from urllib.parse import quote

            conn = db_mod.get_db()

            def _dump(sql):
                try:
                    return [dict(r) for r in conn.execute(sql).fetchall()]
                except Exception:
                    return []

            accounts = _dump('SELECT * FROM accounts ORDER BY id')
            rentals = _dump('SELECT * FROM account_rentals ORDER BY id')
            metrics = _dump('SELECT * FROM monthly_metrics ORDER BY id')
            conn.close()

            payload = {
                'export_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_accounts': len(accounts),
                'total_rentals': len(rentals),
                'accounts': accounts,
                'rentals': rentals,
                'monthly_metrics': metrics,
            }
            body = _json.dumps(payload, ensure_ascii=False, indent=2)
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = '部落冲突账号_{}.json'.format(ts)
            disp = "attachment; filename*=UTF-8''{}".format(quote(fname))
            return Response(
                body,
                mimetype='application/json; charset=utf-8',
                headers={'Content-Disposition': disp, 'Cache-Control': 'no-store'},
            )
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500

    @app.route('/api/export/dialog', methods=['GET'])
    def api_export_dialog():
        # 弹出系统“另存为”对话框，让用户自己选择 Excel 保存位置。
        # tkinter.filedialog 在 Windows 上会调用原生 Win32 对话框，
        # 不需要额外依赖（envs/default 已带 tkinter）。
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            initial = (
                '部落冲突账号_{}.xlsx'.format(
                    datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                )
            )
            path = filedialog.asksaveasfilename(
                parent=root,
                title='导出 Excel',
                initialfile=initial,
                defaultextension='.xlsx',
                filetypes=[('Excel 文件', '*.xlsx'), ('所有文件', '*.*')],
            )
            root.destroy()
            if not path:
                return jsonify({'cancelled': True}), 200
            return jsonify({'path': path}), 200
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500

    @app.route('/api/export/excel/file', methods=['POST'])
    def api_export_excel_file():
        # 把账号导出为 .xlsx，默认保存到程序所在文件夹(BASE_DIR)。
        # 若前端传了 path 参数，则保存到用户指定的路径。
        # 使用纯标准库(zipfile + XML)生成 xlsx，避免对 openpyxl 的依赖，
        # 保证在 PyInstaller 冻结后一定能运行。
        try:
            import zipfile

            def _xml_escape(s):
                s = str(s)
                return (s.replace('&', '&amp;')
                         .replace('<', '&lt;')
                         .replace('>', '&gt;')
                         .replace('"', '&quot;')
                         .replace("'", '&apos;'))

            def _col_letter(idx):  # idx 为 1-based 列号
                s = ''
                while idx > 0:
                    idx, r = divmod(idx - 1, 26)
                    s = chr(65 + r) + s
                return s

            def _cell_xml(ref, val):
                if isinstance(val, bool):
                    text = _xml_escape(val)
                    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'
                elif isinstance(val, (int, float)):
                    return f'<c r="{ref}"><v>{val}</v></c>'
                else:
                    text = _xml_escape(val)
                    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

            def _sheet_xml(name, headers, rows):
                rows_xml = []
                for ri, row in enumerate([headers] + rows, start=1):
                    cells = []
                    for ci, val in enumerate(row, start=1):
                        ref = f'{_col_letter(ci)}{ri}'
                        cells.append(_cell_xml(ref, '' if val is None else val))
                    rows_xml.append(f'<row r="{ri}">{"".join(cells)}</row>')
                return (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    f'<sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
                )

            conn = db_mod.get_db()

            # Standard account sheets (owner_type + platform)
            std_defs = [
                ('本人QQ号', '本人', 'QQ'),
                ('本人微信号', '本人', '微信'),
                ('朋友微信号', '朋友', '微信'),
                ('朋友QQ号', '朋友', 'QQ'),
            ]
            std_headers = ['账号归属', '账号名称', '绑定详情', '账号', '最后登陆时间', '大本营等级', '目标等级']

            sheets = []  # (name, headers, rows)
            for sname, owner_type, platform in std_defs:
                rows = conn.execute(
                    "SELECT owner_name, account_name, binding_detail, account_id, "
                    "last_login_date, town_hall_level, target_th_level FROM accounts "
                    "WHERE owner_type=? AND platform=? ORDER BY id",
                    (owner_type, platform)
                ).fetchall()
                sheets.append((sname, std_headers, rows))

            # 起号 sheet
            raising_headers = ['账号归属', '账号名称', '绑定详情', '账号', '起号设备', '目标等级', '最后登陆时间']
            raising_rows = conn.execute(
                "SELECT owner_name, account_name, binding_detail, account_id, "
                "device_number, target_th_level, last_login_date FROM accounts "
                "WHERE device_number IS NOT NULL AND device_number != '' ORDER BY id"
            ).fetchall()
            sheets.append(('起号', raising_headers, raising_rows))

            # 账号出租 sheet
            rental_headers = ['账号归属', '账号名称', '绑定详情', '账号', '起租日', '租售时长', '结束日']
            rental_rows = []
            try:
                rental_rows = conn.execute(
                    "SELECT owner_name, account_name, binding_detail, account_id_text, "
                    "start_date, duration_days, end_date FROM account_rentals ORDER BY id"
                ).fetchall()
            except Exception:
                pass
            sheets.append(('账号出租', rental_headers, rental_rows))

            conn.close()

            # Build xlsx
            sheet_files = []
            ct_overrides = []
            wb_rels = []
            wb_sheets = []
            for i, (sname, headers, rows) in enumerate(sheets, start=1):
                sxml = _sheet_xml(sname, headers, rows)
                fname = f'sheet{i}.xml'
                sheet_files.append((f'xl/worksheets/{fname}', sxml))
                ct_overrides.append(
                    f'<Override PartName="/xl/worksheets/{fname}" '
                    f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                )
                rid = f'rId{i}'
                wb_rels.append(
                    f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                    f'Target="worksheets/{fname}"/>'
                )
                # make 账号出租 the active sheet
                sheet_attrs = f'name="{sname}" sheetId="{i}" r:id="{rid}"'
                if sname == '账号出租':
                    sheet_attrs += ' state="visible"'
                wb_sheets.append(f'<sheet {sheet_attrs}/>')

            active_tab_idx = next((i for i, (n, _, _) in enumerate(sheets) if n == '账号出租'), 0)
            workbook_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<bookViews><workbookView activeTab="{active_tab_idx}"/></bookViews>'
                f'<sheets>{"".join(wb_sheets)}</sheets></workbook>'
            )
            content_types = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                f'{"".join(ct_overrides)}</Types>'
            )
            rels = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="xl/workbook.xml"/></Relationships>'
            )
            wb_rels_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'{"".join(wb_rels)}</Relationships>'
            )

            data = request.get_json(force=True, silent=True) or {}
            out = data.get('path')
            if not out:
                ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                fname = f'部落冲突账号_{ts}.xlsx'
                out = os.path.join(BASE_DIR, fname)
            else:
                out = str(out)
                if not out.lower().endswith('.xlsx'):
                    out += '.xlsx'
                fname = os.path.basename(out)
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('[Content_Types].xml', content_types)
                z.writestr('_rels/.rels', rels)
                z.writestr('xl/workbook.xml', workbook_xml)
                z.writestr('xl/_rels/workbook.xml.rels', wb_rels_xml)
                for path, sxml in sheet_files:
                    z.writestr(path, sxml)

            try:
                os.startfile(out)
            except Exception:
                try:
                    os.startfile(os.path.dirname(out))
                except Exception:
                    pass
            return jsonify({'path': out, 'name': fname})
        except Exception:
            return jsonify({'error': traceback.format_exc()}), 500
    # ==================== Web 服务模式（部署到服务器 / 公网）====================
    # COC_WEB=1 时：不开桌面窗口，改用生产级 WSGI 服务器对外提供 HTTP 服务，
    # 并在入口加 HTTP Basic 口令验证。桌面版（不设 COC_WEB）完全不受影响。
    if os.environ.get('COC_WEB'):
        _setup_web_auth(app)
        _web_port = int(os.environ.get('COC_WEB_PORT', '8000'))
        # 源码模式下 templates 位于应用根目录（BASE_DIR），修正 Jinja 搜索路径
        _tpl_dir = os.path.join(BASE_DIR, 'templates')
        if os.path.isdir(_tpl_dir):
            try:
                from jinja2 import FileSystemLoader
                app.jinja_loader = FileSystemLoader(_tpl_dir)
            except Exception:
                pass
        try:
            from waitress import serve
            print('[COC-WEB] 服务已启动，监听 0.0.0.0:%d（已启用口令验证）' % _web_port, flush=True)
            serve(app, host='0.0.0.0', port=_web_port, threads=4,
                  ident='COC-Account-Manager', channel_timeout=120)
        except ImportError:
            print('[COC-WEB] 未安装 waitress，回退 Flask 内置服务器', flush=True)
            app.run(host='0.0.0.0', port=_web_port, debug=False,
                    threaded=True, use_reloader=False)
        return

    # Run the original Flask backend in a background thread.
    t = threading.Thread(
        target=lambda: app.run(
            host='127.0.0.1', port=5000, debug=False, use_reloader=False
        ),
        daemon=True,
    )
    t.start()

    if not _wait_for_port('127.0.0.1', 5000, timeout=30):
        raise RuntimeError('Flask 服务未能在 30 秒内启动 (端口 5000)')

    # Headless test mode (used only during build validation): verify that
    # pythonnet + the WebView2 (winforms/edgechromium) backend can be loaded
    # without a visible window, then write the outcome to coc_diag.log.
    if os.environ.get('COC_NO_GUI'):
        try:
            import clr  # noqa: F401  (loads pythonnet / .NET runtime)
            import webview.platforms.winforms  # noqa: F401  (loads WebView2 assemblies)
            diag = 'WEBVIEW_BACKEND_OK\n'
        except Exception:
            diag = traceback.format_exc()
        try:
            with open(os.path.join(BASE_DIR, 'coc_diag.log'), 'w', encoding='utf-8') as f:
                f.write(diag)
        except Exception:
            pass
        time.sleep(120)
        return

    # Show the UI in a native window (Edge / WebView2) instead of spawning
    # the system browser.
    import webview
    # 窗口标题栏/任务栏图标继承自 exe 内嵌图标资源（已在 spec 的 icon= 中设为新图标）。
    # 注意：pywebview 的 create_window 没有 icon 参数，传了会直接 TypeError 崩溃。
    webview.create_window(
        '部落冲突账号管理系统',
        'http://127.0.0.1:5000',
        width=1280,
        height=800,
    )
    webview.start()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        try:
            with open(os.path.join(BASE_DIR, 'coc_error.log'), 'w', encoding='utf-8') as f:
                f.write(tb)
        except Exception:
            pass
        sys.stderr.write(tb)
        sys.exit(1)
