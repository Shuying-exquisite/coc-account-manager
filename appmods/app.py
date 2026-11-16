"""
部落冲突账户数据管理系统 - Flask 后端
"""
import os
import sys
import threading
import webbrowser
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path):
    """兼容 PyInstaller 打包后的资源路径"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


from database import (
    init_db, get_all_accounts, get_account, add_account, update_account,
    delete_account, get_statistics, get_operation_logs, get_all_owners,
    log_operation, get_db, DB_PATH, get_raising_accounts, update_raising_account,
    get_all_rentals, get_rental, add_rental, update_rental, delete_rental,
)

app = Flask(__name__, template_folder=resource_path("templates"), static_folder=resource_path("static"))


@app.route("/")
def index():
    return render_template("index.html")


# ==================== 账户 API ====================

@app.route("/api/accounts", methods=["GET"])
def api_get_accounts():
    filters = {
        "platform": request.args.get("platform"),
        "owner_type": request.args.get("owner_type"),
        "owner_name": request.args.get("owner_name"),
        "th_level": request.args.get("th_level", type=int) if request.args.get("th_level") else None,
        "search": request.args.get("search"),
    }
    # 移除空值
    filters = {k: v for k, v in filters.items() if v}
    accounts = get_all_accounts(filters if filters else None)
    return jsonify(accounts)


@app.route("/api/accounts/<int:account_id>", methods=["GET"])
def api_get_account(account_id):
    account = get_account(account_id)
    if account:
        return jsonify(account)
    return jsonify({"error": "未找到账户"}), 404


@app.route("/api/accounts", methods=["POST"])
def api_add_account():
    data = request.get_json()
    if not data.get("account_name") and not data.get("account_id"):
        return jsonify({"error": "账号名称和账号至少填写一个"}), 400
    account_id = add_account(data)
    return jsonify({"id": account_id, "message": "新增成功"}), 201


@app.route("/api/accounts/<int:account_id>", methods=["PUT"])
def api_update_account(account_id):
    data = request.get_json()
    update_account(account_id, data)
    return jsonify({"message": "修改成功"})


@app.route("/api/accounts/<int:account_id>", methods=["DELETE"])
def api_delete_account(account_id):
    delete_account(account_id)
    return jsonify({"message": "删除成功"})


# ==================== 起号管理 API ====================

@app.route("/api/raising", methods=["GET"])
def api_get_raising_accounts():
    """获取起号账户列表（有设备编号的账号）"""
    filters = {
        "search": request.args.get("search"),
        "target_th_level": request.args.get("target_th_level", type=int)
        if request.args.get("target_th_level")
        else None,
    }
    filters = {k: v for k, v in filters.items() if v}
    accounts = get_raising_accounts(filters if filters else None)
    return jsonify(accounts)


@app.route("/api/raising/<int:account_id>", methods=["GET"])
def api_get_raising_account(account_id):
    """获取单个起号账户详情"""
    account = get_account(account_id)
    if account and account.get("device_number") is not None:
        return jsonify(account)
    return jsonify({"error": "未找到起号账户"}), 404


@app.route("/api/raising/<int:account_id>", methods=["PUT"])
def api_update_raising_account(account_id):
    """在起号子界面修改数据，同步到账号主表"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体不能为空"}), 400
    success = update_raising_account(account_id, data)
    if success:
        return jsonify({"message": "起号数据已同步到账号主表"})
    return jsonify({"error": "未找到起号账户或没有可更新的字段"}), 404


# ==================== 账号出租 API ====================

@app.route("/api/rentals", methods=["GET"])
def api_get_rentals():
    """获取出租账号列表"""
    filters = {
        "search": request.args.get("search"),
        "status": request.args.get("status"),
    }
    filters = {k: v for k, v in filters.items() if v}
    rentals = get_all_rentals(filters if filters else None)
    return jsonify(rentals)


@app.route("/api/rentals/<int:rental_id>", methods=["GET"])
def api_get_rental(rental_id):
    """获取单条出租记录"""
    rental = get_rental(rental_id)
    if rental:
        return jsonify(rental)
    return jsonify({"error": "未找到出租记录"}), 404


@app.route("/api/rentals", methods=["POST"])
def api_add_rental():
    """新增出租记录"""
    data = request.get_json()
    if not data.get("account_name") and not data.get("account_id_text"):
        return jsonify({"error": "账号名称和账号至少填写一个"}), 400
    rental_id = add_rental(data)
    return jsonify({"id": rental_id, "message": "新增出租成功"}), 201


@app.route("/api/rentals/<int:rental_id>", methods=["PUT"])
def api_update_rental(rental_id):
    """更新出租记录"""
    data = request.get_json()
    update_rental(rental_id, data)
    return jsonify({"message": "修改出租成功"})


@app.route("/api/rentals/<int:rental_id>", methods=["DELETE"])
def api_delete_rental(rental_id):
    """删除出租记录"""
    delete_rental(rental_id)
    return jsonify({"message": "删除出租成功"})


# ==================== 统计 API ====================

@app.route("/api/statistics", methods=["GET"])
def api_statistics():
    return jsonify(get_statistics())


@app.route("/api/owners", methods=["GET"])
def api_owners():
    return jsonify(get_all_owners())


@app.route("/api/logs", methods=["GET"])
def api_logs():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(get_operation_logs(limit))


# ==================== 数据导入/导出 ====================

@app.route("/api/import", methods=["POST"])
def api_import():
    """从默认路径重新导入数据"""
    from import_data import import_data
    success, count, msg = import_data()
    if success:
        return jsonify({"message": f"导入完成，共 {count} 条记录", "count": count})
    return jsonify({"error": msg}), 500


@app.route("/api/import/upload", methods=["POST"])
def api_import_upload():
    """通过上传文件导入数据"""
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "未选择文件"}), 400

    if not file.filename.endswith((".xlsx", ".xls")):
        return jsonify({"error": "请上传 Excel 文件 (.xlsx)"}), 400

    try:
        file_bytes = file.read()
        from import_data import import_data
        success, count, msg = import_data(file_bytes=file_bytes)
        if success:
            return jsonify({"message": f"导入完成，共 {count} 条记录", "count": count})
        return jsonify({"error": msg}), 500
    except Exception as e:
        return jsonify({"error": f"导入失败: {str(e)}"}), 500


@app.route("/api/export", methods=["GET"])
def api_export():
    """导出所有账户数据为 JSON"""
    accounts = get_all_accounts()
    return jsonify({
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(accounts),
        "accounts": accounts,
    })


@app.route("/api/export/excel", methods=["GET"])
def api_export_excel():
    """导出为与原文件相同结构的 Excel 文件"""
    from import_data import export_to_excel
    output = export_to_excel()
    filename = f"部落冲突月度指标_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/api/clear", methods=["POST"])
def api_clear():
    """清空所有数据"""
    conn = get_db()
    conn.execute("DELETE FROM accounts")
    conn.execute("DELETE FROM account_rentals")
    conn.execute("DELETE FROM operation_logs")
    conn.commit()
    conn.close()
    return jsonify({"message": "数据已清空"})


if __name__ == "__main__":
    # 确保数据库已初始化（升级表结构）
    init_db()
    print("=" * 50)
    print("  部落冲突账户数据管理系统")
    print("  访问地址: http://127.0.0.1:5000")
    print("  按 Ctrl+C 退出")
    print("=" * 50)
    # 延迟 1.5 秒后自动打开浏览器
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
