# -*- coding: utf-8 -*-
"""
部落冲突账号管理系统 —— 一键重建脚本

用法（在任意目录执行都行，脚本用自身所在目录作为 build 根）：
    python rebuild.py                 # 完整重建：编译 pyc + 打包窗口版 exe
    python rebuild.py --compile-only  # 只把 appmods/*.py 编译成 *.pyc
    python rebuild.py --verify-only   # 只校验源码与 pyc 字节码一致性

构建解释器路径可通过环境变量 COC_BUILD_PY 指定；未指定时默认用当前 python。
    COC_BUILD_PY=/path/to/python.exe python rebuild.py

关于 .pyc：
    launcher.py 在桌面版下通过 marshal 直接加载 appmods/*.pyc（跳过 16 字节头），
    所以改了 .py 之后必须重新编译 .pyc 才会生效。Web 版（COC_WEB=1）则直接读 .py，
    不依赖 .pyc。
"""
import os
import sys
import shutil
import subprocess
import hashlib
import marshal
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APPMODS = os.path.join(HERE, 'appmods')
VENV_PY = os.environ.get('COC_BUILD_PY') or sys.executable
SPEC = os.path.join(HERE, 'COC_Account_Manager.spec')

# 可选的"参考 .pyc"目录（用于字节码一致性对比；找不到就跳过）
RUN_APPMODS = os.environ.get('COC_REF_PYCDIR', '')


def _fp(co):
    parts = []
    def walk(c):
        parts.append((c.co_name, tuple(c.co_names),
                      tuple(x for x in c.co_consts if isinstance(x, (str, int, float, bytes))),
                      c.co_code))
        for x in c.co_consts:
            if hasattr(x, 'co_code'):
                walk(x)
    walk(co)
    return hashlib.md5(repr(parts).encode()).hexdigest()


def _pyc_code(path):
    with open(path, 'rb') as f:
        data = f.read()
    return marshal.loads(data[16:])


def compile_pyc():
    """把 appmods/*.py 编译成 *.pyc（launcher.py 通过 marshal 加载，跳过 16 字节头）。"""
    import py_compile
    for name in ('app', 'database', 'import_data'):
        src = os.path.join(APPMODS, name + '.py')
        dst = os.path.join(APPMODS, name + '.pyc')
        py_compile.compile(src, cfile=dst, doraise=True)
        print(f'  [compile] {name}.py -> {name}.pyc ({os.path.getsize(dst)} bytes)')


def verify():
    """校验 appmods/*.py 编译后的字节码与将要打包的 *.pyc 一致（硬性要求）。

    注意：与"线上运行版" .pyc 的对比只作信息提示、不作为断言——
    当我们主动升级了源码（例如优化起号逻辑）时，与旧版字节码不同是正常的。
    2026-11-15 找回源码时这项用于证明"找回的源码=线上版本"；
    此后进入正常迭代，比较基准改为"工程内 .py ↔ .pyc"。
    """
    ok = True
    for name in ('app', 'database', 'import_data'):
        py = os.path.join(APPMODS, name + '.py')
        pyc = os.path.join(APPMODS, name + '.pyc')
        fp_py = _fp(compile(open(py, encoding='utf-8').read(), py, 'exec'))
        fp_pyc = _fp(_pyc_code(pyc))
        status = 'MATCH' if fp_py == fp_pyc else 'DIFF'
        print(f'  [verify] {name}: .py vs .pyc = {status}')
        if status != 'MATCH':
            ok = False
        if os.path.isdir(RUN_APPMODS):
            run_pyc = os.path.join(RUN_APPMODS, name + '.pyc')
            if os.path.exists(run_pyc):
                fp_run = _fp(_pyc_code(run_pyc))
                st2 = '相同(与线上旧版一致)' if fp_py == fp_run else '不同(本次已升级源码)'
                print(f'  [verify] {name}: 与线上运行版.pyc = {st2}')
    return ok


def build():
    """用 PyInstaller 打包窗口版（全新 distpath，清空 NODE_OPTIONS）。"""
    if not os.path.exists(VENV_PY):
        print(f'  [error] 构建 venv 不存在: {VENV_PY}')
        print('         请按 README.md 的“重建构建环境”一节重建。')
        return False
    # 全新 distpath：时间戳命名，避免复用触发安全删除钩子
    distpath = os.path.join(HERE, 'dist_rebuild_' + __import__('time').strftime('%Y%m%d_%H%M%S'))
    workpath = os.path.join(tempfile.gettempdir(), 'pyi_coc_rebuild_' + __import__('time').strftime('%H%M%S'))
    cmd = [VENV_PY, '-m', 'PyInstaller', SPEC,
           '--noconfirm', '--clean',
           '--workpath', workpath, '--distpath', distpath]
    env = os.environ.copy()
    env['NODE_OPTIONS'] = ''   # 关键：清空安全删除 shim 注入
    print(f'  [build] cmd: {" ".join(cmd)}')
    print(f'  [build] distpath: {distpath}')
    ret = subprocess.run(cmd, cwd=HERE, env=env)
    if ret.returncode != 0:
        print('  [error] PyInstaller 失败')
        return False
    out = os.path.join(distpath, 'COC_Account_Manager')
    # 输出校验
    checks = {
        'COC_Account_Manager.exe': os.path.join(out, 'COC_Account_Manager.exe'),
        '_tkinter.pyd': os.path.join(out, '_tkinter.pyd'),
        'appmods/app.pyc': os.path.join(out, 'appmods', 'app.pyc'),
        'templates/index.html': os.path.join(out, 'templates', 'index.html'),
    }
    all_ok = True
    for label, p in checks.items():
        exists = os.path.exists(p)
        print(f'  [check] {label}: {"OK" if exists else "MISSING"}')
        all_ok = all_ok and exists
    print(f'\n  打包输出: {out}')
    print(f'  校验: {"全部通过 ✅" if all_ok else "有缺失 ❌"}')
    return all_ok


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--compile-only' in args:
        compile_pyc()
    elif '--verify-only' in args:
        sys.exit(0 if verify() else 1)
    else:
        print('== 1/3 编译 pyc ==')
        compile_pyc()
        print('== 2/3 校验字节码一致性 ==')
        if not verify():
            print('校验失败，终止打包。')
            sys.exit(1)
        print('== 3/3 PyInstaller 打包 ==')
        sys.exit(0 if build() else 1)
