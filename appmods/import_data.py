"""
从 Excel 导入数据到 SQLite 数据库
支持从任意文件路径导入
"""
import os
import sys
from datetime import datetime, timedelta
import openpyxl
from io import BytesIO

# 添加当前目录到路径（兼容 PyInstaller 打包）
if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import init_db, get_db, DB_PATH

DEFAULT_EXCEL_PATH = os.path.join(os.path.expanduser("~"), "Downloads", "部落冲突月度指标.xlsx")


def excel_serial_to_date(serial):
    """将 Excel 日期序列号转换为日期字符串"""
    if serial is None:
        return None
    if isinstance(serial, datetime):
        return serial.strftime("%Y-%m-%d")
    if isinstance(serial, (int, float)):
        try:
            base_date = datetime(1899, 12, 30)
            result_date = base_date + timedelta(days=int(serial))
            return result_date.strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(serial, str):
        return serial.strip() if serial.strip() else None
    return None


def import_data(file_path=None, file_bytes=None):
    """
    导入 Excel 数据
    file_path: Excel 文件路径（优先使用）
    file_bytes: Excel 文件字节流（用于上传导入）
    返回: (成功标志, 导入数量, 错误信息)
    """
    # 确定数据源
    if file_path:
        if not os.path.exists(file_path):
            return False, 0, f"文件不存在: {file_path}"
        wb = openpyxl.load_workbook(file_path, data_only=True)
    elif file_bytes:
        wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    else:
        # 使用默认路径
        if not os.path.exists(DEFAULT_EXCEL_PATH):
            return False, 0, f"默认文件不存在: {DEFAULT_EXCEL_PATH}"
        wb = openpyxl.load_workbook(DEFAULT_EXCEL_PATH, data_only=True)

    # 初始化数据库
    init_db()

    # 清空已有数据
    conn = get_db()
    conn.execute("DELETE FROM accounts")
    conn.execute("DELETE FROM account_rentals")
    conn.execute("DELETE FROM operation_logs")

    imported_count = 0

    # 起号表的数据（设备分配和目标等级）
    device_map = {}
    if "起号" in wb.sheetnames:
        ws = wb["起号"]
        for row in ws.iter_rows(min_row=4, max_row=ws.max_row, values_only=True):
            if not row or len(row) < 5:
                continue
            account_id_val = row[4] if len(row) > 4 else None
            device_num = row[0] if len(row) > 0 else None
            target = row[6] if len(row) > 6 else None

            if account_id_val is not None:
                key = str(account_id_val)
                target_val = None
                if isinstance(target, int) and target <= 20:
                    target_val = target
                device_map[key] = {
                    "device_number": device_num if isinstance(device_num, int) else None,
                    "target_th_level": target_val,
                }

    sheet_configs = [
        ("本人QQ号", "本人", "QQ"),
        ("本人微信号", "本人", "微信"),
        ("朋友微信号", "朋友", "微信"),
        ("朋友QQ号", "朋友", "QQ"),
    ]

    for sheet_name, owner_type, platform in sheet_configs:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=3, max_row=ws.max_row, values_only=True):
            if not row or len(row) < 7:
                continue
            owner_name = str(row[1]) if row[1] else ""
            account_name = str(row[2]) if row[2] else ""
            binding_detail = str(row[3]) if row[3] else ""
            account_id_val = str(row[4]) if row[4] else ""
            last_login = excel_serial_to_date(row[5])
            th_level = row[6] if row[6] is not None else 0

            if not account_name and not account_id_val:
                continue

            extra = device_map.get(account_id_val, {})
            conn.execute(
                """INSERT INTO accounts (owner_type, platform, owner_name, account_name,
                   binding_detail, account_id, last_login_date, town_hall_level,
                   target_th_level, device_number, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    owner_type, platform, owner_name, account_name, binding_detail,
                    account_id_val, last_login, th_level,
                    extra.get("target_th_level"), extra.get("device_number"), "",
                ),
            )
            imported_count += 1

    # 导入账号出租表
    rental_count = 0
    if "账号出租" in wb.sheetnames:
        ws = wb["账号出租"]
        for row in ws.iter_rows(min_row=3, max_row=ws.max_row, values_only=True):
            if not row or len(row) < 5:
                continue
            owner_name = str(row[1]) if row[1] else ""
            account_name = str(row[2]) if row[2] else ""
            binding_detail = str(row[3]) if row[3] else ""
            account_id_val = str(row[4]) if row[4] else ""
            start_date = excel_serial_to_date(row[5]) if len(row) > 5 else None
            duration_days = int(row[6]) if len(row) > 6 and isinstance(row[6], (int, float)) else None
            end_date = excel_serial_to_date(row[7]) if len(row) > 7 else None

            if not account_name and not account_id_val:
                continue

            # 关联到 accounts 表
            linked_account_id = None
            if account_id_val:
                account_row = conn.execute(
                    "SELECT id FROM accounts WHERE account_id = ? LIMIT 1",
                    (account_id_val,),
                ).fetchone()
                if account_row:
                    linked_account_id = account_row["id"]
                else:
                    # 尝试用名称匹配
                    account_row = conn.execute(
                        "SELECT id FROM accounts WHERE account_name = ? LIMIT 1",
                        (account_name,),
                    ).fetchone()
                    if account_row:
                        linked_account_id = account_row["id"]

            conn.execute(
                """INSERT INTO account_rentals (account_id, owner_name, account_name,
                   binding_detail, account_id_text, start_date, duration_days, end_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    linked_account_id, owner_name, account_name, binding_detail,
                    account_id_val, start_date, duration_days, end_date,
                ),
            )
            rental_count += 1

    conn.commit()
    conn.close()
    print(f"[导入完成] 共导入 {imported_count} 条账户记录, {rental_count} 条出租记录")
    return True, imported_count, f"导入成功，账户 {imported_count} 条，出租 {rental_count} 条"


def export_to_excel():
    """
    将数据库中的数据导出为与原文件相同结构的 Excel
    返回: BytesIO 字节流
    """
    conn = get_db()

    # 创建工作簿
    wb = openpyxl.Workbook()
    # 删除默认sheet
    wb.remove(wb.active)

    headers = ["账号归属", "账号名称", "绑定详情", "账号", "最后登陆时间", "大本营等级"]

    sheet_configs = [
        ("本人QQ号", "本人", "QQ", "账号"),
        ("本人微信号", "本人", "微信", "vx号"),
        ("朋友微信号", "朋友", "微信", "vx号"),
        ("朋友QQ号", "朋友", "QQ", "账号"),
    ]

    for sheet_name, owner_type, platform, id_col_name in sheet_configs:
        ws = wb.create_sheet(title=sheet_name)
        # 写表头（B2开始，与原文件一致）
        ws["B2"] = "账号归属"
        ws["C2"] = "账号名称"
        ws["D2"] = "绑定详情"
        ws["E2"] = id_col_name
        ws["F2"] = "最后登陆时间"
        ws["G2"] = "大本营等级"

        # 查询数据
        rows = conn.execute(
            "SELECT owner_name, account_name, binding_detail, account_id, "
            "last_login_date, town_hall_level FROM accounts "
            "WHERE owner_type=? AND platform=? "
            "ORDER BY town_hall_level DESC, account_name",
            (owner_type, platform),
        ).fetchall()

        for i, row in enumerate(rows):
            r = i + 3  # 从第3行开始
            ws.cell(row=r, column=2, value=row["owner_name"] or "")
            ws.cell(row=r, column=3, value=row["account_name"] or "")
            ws.cell(row=r, column=4, value=row["binding_detail"] or "")
            ws.cell(row=r, column=5, value=row["account_id"] or "")
            ws.cell(row=r, column=6, value=row["last_login_date"] or "")
            ws.cell(row=r, column=7, value=row["town_hall_level"] or 0)

    # 起号表
    ws_qh = wb.create_sheet(title="起号")
    ws_qh["A2"] = "序号"
    ws_qh["B2"] = "账号归属"
    ws_qh["C2"] = "账号名称"
    ws_qh["D2"] = "绑定详情"
    ws_qh["E2"] = "账号"
    ws_qh["F2"] = "大本营等级"
    ws_qh["G2"] = "目标等级大本营等级"

    qh_rows = conn.execute(
        "SELECT owner_name, account_name, binding_detail, account_id, "
        "town_hall_level, target_th_level, device_number FROM accounts "
        "WHERE device_number IS NOT NULL "
        "ORDER BY device_number"
    ).fetchall()

    for i, row in enumerate(qh_rows):
        r = i + 3
        ws_qh.cell(row=r, column=1, value=row["device_number"])
        ws_qh.cell(row=r, column=2, value=row["owner_name"] or "")
        ws_qh.cell(row=r, column=3, value=row["account_name"] or "")
        ws_qh.cell(row=r, column=4, value=row["binding_detail"] or "")
        ws_qh.cell(row=r, column=5, value=row["account_id"] or "")
        ws_qh.cell(row=r, column=6, value=row["town_hall_level"] or 0)
        ws_qh.cell(row=r, column=7, value=row["target_th_level"] or "")

    # 账号出租表
    ws_rental = wb.create_sheet(title="账号出租")
    ws_rental["B2"] = "账号归属"
    ws_rental["C2"] = "账号名称"
    ws_rental["D2"] = "绑定详情"
    ws_rental["E2"] = "账号"
    ws_rental["F2"] = "起租日"
    ws_rental["G2"] = "租售时长"
    ws_rental["H2"] = "结束日"

    rental_rows = conn.execute(
        "SELECT owner_name, account_name, binding_detail, account_id_text, "
        "start_date, duration_days, end_date FROM account_rentals "
        "ORDER BY created_at"
    ).fetchall()

    for i, row in enumerate(rental_rows):
        r = i + 3
        ws_rental.cell(row=r, column=2, value=row["owner_name"] or "")
        ws_rental.cell(row=r, column=3, value=row["account_name"] or "")
        ws_rental.cell(row=r, column=4, value=row["binding_detail"] or "")
        ws_rental.cell(row=r, column=5, value=row["account_id_text"] or "")
        ws_rental.cell(row=r, column=6, value=row["start_date"] or "")
        ws_rental.cell(row=r, column=7, value=row["duration_days"] if row["duration_days"] is not None else "")
        ws_rental.cell(row=r, column=8, value=row["end_date"] or "")

    conn.close()

    # 保存到字节流
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


if __name__ == "__main__":
    success, count, msg = import_data()
    print(msg, f"共 {count} 条")
