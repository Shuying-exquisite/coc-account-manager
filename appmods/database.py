"""
部落冲突账户数据管理数据库
SQLite 数据库初始化与操作模块
"""
import sqlite3
import os
import sys
from datetime import datetime

# 打包为 exe 后，数据库放在 exe 同级目录（用户数据持久化）
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(APP_DIR, "coc_database.db")


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """初始化数据库，创建表结构"""
    conn = get_db()
    cursor = conn.cursor()

    # 账户主表 - 统一管理所有部落冲突账号
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_type TEXT NOT NULL DEFAULT '本人',
            platform TEXT NOT NULL DEFAULT 'QQ',
            owner_name TEXT DEFAULT '',
            account_name TEXT DEFAULT '',
            binding_detail TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            last_login_date TEXT,
            town_hall_level INTEGER DEFAULT 0,
            target_th_level INTEGER,
            device_number INTEGER,
            raising_seq INTEGER,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 月度指标表 - 跟踪每月发展数据
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monthly_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            record_month TEXT NOT NULL,
            gold_grab INTEGER DEFAULT 0,
            elixir_grab INTEGER DEFAULT 0,
            dark_elixir_grab INTEGER DEFAULT 0,
            attack_wins INTEGER DEFAULT 0,
            defense_wins INTEGER DEFAULT 0,
            trophies INTEGER DEFAULT 0,
            war_stars INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            UNIQUE(account_id, record_month)
        )
    """)

    # 操作日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 账号出租表 - 管理账号出租记录
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_rentals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            owner_name TEXT DEFAULT '',
            account_name TEXT DEFAULT '',
            binding_detail TEXT DEFAULT '',
            account_id_text TEXT DEFAULT '',
            start_date TEXT,
            duration_days INTEGER,
            end_date TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL
        )
    """)

    # 迁移：老库补充 raising_seq 列（起号序号，人工可编辑、起号范围内唯一）
    try:
        cursor.execute("ALTER TABLE accounts ADD COLUMN raising_seq INTEGER")
    except Exception:
        pass  # 列已存在

    # 创建索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_owner_type ON accounts(owner_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_th_level ON accounts(town_hall_level)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_account ON monthly_metrics(account_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rentals_account ON account_rentals(account_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rentals_start_date ON account_rentals(start_date)")

    conn.commit()
    conn.close()
    print(f"[数据库] 初始化完成: {DB_PATH}")


def log_operation(action, target_type=None, target_id=None, description=""):
    """记录操作日志"""
    conn = get_db()
    conn.execute(
        "INSERT INTO operation_logs (action, target_type, target_id, description) VALUES (?, ?, ?, ?)",
        (action, target_type, target_id, description),
    )
    conn.commit()
    conn.close()


# ==================== 账户 CRUD ====================

def get_all_accounts(filters=None):
    """获取所有账户，支持筛选"""
    conn = get_db()
    query = "SELECT * FROM accounts WHERE 1=1"
    params = []

    if filters:
        if filters.get("platform"):
            query += " AND platform = ?"
            params.append(filters["platform"])
        if filters.get("owner_type"):
            query += " AND owner_type = ?"
            params.append(filters["owner_type"])
        if filters.get("owner_name"):
            query += " AND owner_name = ?"
            params.append(filters["owner_name"])
        if filters.get("th_level") is not None:
            query += " AND town_hall_level = ?"
            params.append(filters["th_level"])
        if filters.get("search"):
            search = f"%{filters['search']}%"
            query += """ AND (account_name LIKE ? OR account_id LIKE ?
                       OR binding_detail LIKE ? OR owner_name LIKE ?)"""
            params.extend([search, search, search, search])

    query += " ORDER BY owner_type, platform, town_hall_level DESC, account_name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_account(account_id):
    """获取单个账户"""
    conn = get_db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_account(data):
    """新增账户"""
    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO accounts (owner_type, platform, owner_name, account_name,
            binding_detail, account_id, last_login_date, town_hall_level,
            target_th_level, device_number, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("owner_type", "本人"),
            data.get("platform", "QQ"),
            data.get("owner_name", ""),
            data.get("account_name", ""),
            data.get("binding_detail", ""),
            data.get("account_id", ""),
            data.get("last_login_date"),
            data.get("town_hall_level", 0),
            data.get("target_th_level"),
            data.get("device_number"),
            data.get("notes", ""),
        ),
    )
    account_id = cursor.lastrowid
    conn.commit()
    conn.close()
    log_operation("新增", "account", account_id, f"新增账户: {data.get('account_name', '')}")
    return account_id


def update_account(account_id, data):
    """更新账户"""
    conn = get_db()
    fields = []
    params = []
    for key in [
        "owner_type", "platform", "owner_name", "account_name", "binding_detail",
        "account_id", "last_login_date", "town_hall_level", "target_th_level",
        "device_number", "notes",
    ]:
        if key in data:
            fields.append(f"{key} = ?")
            params.append(data[key])

    fields.append("updated_at = datetime('now', 'localtime')")
    params.append(account_id)

    conn.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    log_operation("修改", "account", account_id, f"修改账户: {data.get('account_name', '')}")


def delete_account(account_id):
    """删除账户"""
    conn = get_db()
    account = conn.execute("SELECT account_name FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()
    name = account["account_name"] if account else ""
    log_operation("删除", "account", account_id, f"删除账户: {name}")


# ==================== 统计 ====================

def get_statistics():
    """获取仪表盘统计数据"""
    conn = get_db()
    stats = {}

    # 总数
    stats["total"] = conn.execute("SELECT COUNT(*) as c FROM accounts").fetchone()["c"]

    # 按平台
    stats["by_platform"] = {
        "QQ": conn.execute("SELECT COUNT(*) as c FROM accounts WHERE platform='QQ'").fetchone()["c"],
        "微信": conn.execute("SELECT COUNT(*) as c FROM accounts WHERE platform='微信'").fetchone()["c"],
    }

    # 按归属
    stats["by_owner_type"] = {
        "本人": conn.execute("SELECT COUNT(*) as c FROM accounts WHERE owner_type='本人'").fetchone()["c"],
        "朋友": conn.execute("SELECT COUNT(*) as c FROM accounts WHERE owner_type='朋友'").fetchone()["c"],
    }

    # 按大本营等级
    th_rows = conn.execute(
        "SELECT town_hall_level, COUNT(*) as c FROM accounts GROUP BY town_hall_level ORDER BY town_hall_level"
    ).fetchall()
    stats["by_th_level"] = {str(r["town_hall_level"]): r["c"] for r in th_rows}

    # 按归属人
    owner_rows = conn.execute(
        "SELECT owner_name, COUNT(*) as c FROM accounts GROUP BY owner_name ORDER BY c DESC"
    ).fetchall()
    stats["by_owner"] = {r["owner_name"]: r["c"] for r in owner_rows}

    # 最高大本营
    max_th = conn.execute("SELECT MAX(town_hall_level) as m FROM accounts").fetchone()["m"]
    stats["max_th"] = max_th if max_th else 0

    # 平均大本营
    avg_th = conn.execute("SELECT AVG(town_hall_level) as a FROM accounts").fetchone()["a"]
    stats["avg_th"] = round(avg_th, 1) if avg_th else 0

    # 出租账号数量
    stats["rental_count"] = conn.execute("SELECT COUNT(*) as c FROM account_rentals").fetchone()["c"]

    conn.close()
    return stats


def get_operation_logs(limit=50):
    """获取操作日志"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM operation_logs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_owners():
    """获取所有归属人列表"""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT owner_name FROM accounts WHERE owner_name != '' ORDER BY owner_name"
    ).fetchall()
    conn.close()
    return [r["owner_name"] for r in rows]


# ==================== 账号出租管理 ====================

def get_all_rentals(filters=None):
    """获取所有出租记录，支持筛选"""
    conn = get_db()
    query = """
        SELECT r.*,
               a.platform as account_platform,
               a.town_hall_level as account_th_level
        FROM account_rentals r
        LEFT JOIN accounts a ON r.account_id = a.id
        WHERE 1=1
    """
    params = []

    if filters:
        if filters.get("search"):
            search = f"%{filters['search']}%"
            query += """ AND (r.account_name LIKE ? OR r.account_id_text LIKE ?
                       OR r.binding_detail LIKE ? OR r.owner_name LIKE ?)"""
            params.extend([search, search, search, search])
        if filters.get("status"):
            today = datetime.now().strftime("%Y-%m-%d")
            if filters["status"] == "出租中":
                query += " AND r.start_date <= ? AND r.end_date >= ?"
                params.extend([today, today])
            elif filters["status"] == "已到期":
                query += " AND r.end_date < ?"
                params.append(today)
            elif filters["status"] == "未开始":
                query += " AND r.start_date > ?"
                params.append(today)

    query += " ORDER BY r.created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_rental(rental_id):
    """获取单条出租记录"""
    conn = get_db()
    row = conn.execute(
        """SELECT r.*, a.platform as account_platform, a.town_hall_level as account_th_level
           FROM account_rentals r
           LEFT JOIN accounts a ON r.account_id = a.id
           WHERE r.id = ?""",
        (rental_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _link_rental_to_account(conn, data):
    """根据账号ID尝试关联到 accounts 表"""
    account_id_text = data.get("account_id_text", "")
    account_name = data.get("account_name", "")
    if not account_id_text and not account_name:
        return None

    # 优先用账号ID匹配
    if account_id_text:
        row = conn.execute(
            "SELECT id FROM accounts WHERE account_id = ? LIMIT 1",
            (account_id_text,),
        ).fetchone()
        if row:
            return row["id"]
    # 再用账号名称匹配
    if account_name:
        row = conn.execute(
            "SELECT id FROM accounts WHERE account_name = ? LIMIT 1",
            (account_name,),
        ).fetchone()
        if row:
            return row["id"]
    return None


def add_rental(data):
    """新增出租记录"""
    conn = get_db()
    linked_account_id = _link_rental_to_account(conn, data)

    cursor = conn.execute(
        """
        INSERT INTO account_rentals (account_id, owner_name, account_name, binding_detail,
            account_id_text, start_date, duration_days, end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            linked_account_id,
            data.get("owner_name", ""),
            data.get("account_name", ""),
            data.get("binding_detail", ""),
            data.get("account_id_text", ""),
            data.get("start_date"),
            data.get("duration_days"),
            data.get("end_date"),
        ),
    )
    rental_id = cursor.lastrowid
    conn.commit()
    conn.close()
    log_operation("新增出租", "rental", rental_id, f"新增出租: {data.get('account_name', '')}")
    return rental_id


def update_rental(rental_id, data):
    """更新出租记录"""
    conn = get_db()
    linked_account_id = _link_rental_to_account(conn, data)
    if linked_account_id is not None:
        data["account_id"] = linked_account_id

    fields = []
    params = []
    for key in [
        "account_id", "owner_name", "account_name", "binding_detail",
        "account_id_text", "start_date", "duration_days", "end_date",
    ]:
        if key in data:
            fields.append(f"{key} = ?")
            params.append(data[key])

    fields.append("updated_at = datetime('now', 'localtime')")
    params.append(rental_id)

    conn.execute(f"UPDATE account_rentals SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    log_operation("修改出租", "rental", rental_id, f"修改出租: {data.get('account_name', '')}")


def delete_rental(rental_id):
    """删除出租记录"""
    conn = get_db()
    rental = conn.execute(
        "SELECT account_name FROM account_rentals WHERE id = ?", (rental_id,)
    ).fetchone()
    conn.execute("DELETE FROM account_rentals WHERE id = ?", (rental_id,))
    conn.commit()
    conn.close()
    name = rental["account_name"] if rental else ""
    log_operation("删除出租", "rental", rental_id, f"删除出租: {name}")


# ==================== 起号管理 ====================

def get_raising_accounts(filters=None):
    """获取起号账户（有设备编号的账号），支持筛选。

    优化点（2026-11-16）：
    - 排除空字符串设备号（历史脏数据曾让普通账号误入起号列表）；
    - 为每条记录补充起号进度字段 progress_pct / th_gap / remaining，
      供前端进度可视化使用，不改变原有字段契约。
    """
    conn = get_db()
    # 同时排除 NULL 与 ''，避免空设备号的普通账号混进起号列表
    query = "SELECT * FROM accounts WHERE device_number IS NOT NULL AND device_number != ''"
    params = []

    if filters:
        if filters.get("search"):
            search = f"%{filters['search']}%"
            query += """ AND (account_name LIKE ? OR account_id LIKE ?
                       OR binding_detail LIKE ? OR owner_name LIKE ?)"""
            params.extend([search, search, search, search])
        if filters.get("target_th_level") is not None:
            query += " AND target_th_level = ?"
            params.append(filters["target_th_level"])

    # 有自定义序号的按序号升序排在前面，未填序号的按设备号排后面
    query += " ORDER BY (raising_seq IS NULL), raising_seq, CAST(device_number AS INTEGER), device_number"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        cur = d.get("town_hall_level") or 0
        target = d.get("target_th_level") or 0
        # 进度：以当前本/目标本为百分比；差距为还差多少本
        if target > 0:
            pct = int(min(100, max(0, round(cur / target * 100))))
            gap = max(0, target - cur)
        else:
            pct = 0
            gap = 0
        d["progress_pct"] = pct
        d["th_gap"] = gap
        d["remaining"] = gap  # 语义别名，前端展示用
        result.append(d)
    return result


def update_raising_account(account_id, data):
    """更新起号数据，同步到账号主表。

    优化点（2026-11-16）：
    - 起号设备号必须唯一：若把设备号改成他人已占用的值，拒绝更新（返回 False），
      避免出现两个起号共用一个设备号导致管理混乱。
    - 校验目标等级合法性（0-18），非法值拒绝。
    """
    conn = get_db()

    # 校验是否为起号账户
    account = conn.execute(
        "SELECT id, account_name FROM accounts WHERE id = ? AND device_number IS NOT NULL",
        (account_id,)
    ).fetchone()
    if not account:
        conn.close()
        return False

    # 起号设备号唯一性校验（排除自身）
    if "device_number" in data and data["device_number"] not in (None, ""):
        dev = str(data["device_number"]).strip()
        dup = conn.execute(
            "SELECT id FROM accounts WHERE device_number = ? AND id != ?",
            (dev, account_id)
        ).fetchone()
        if dup:
            conn.close()
            return False
        data = dict(data)
        data["device_number"] = dev

    # 目标等级合法性校验（0-18）
    if "target_th_level" in data and data["target_th_level"] not in (None, ""):
        try:
            tv = int(data["target_th_level"])
            if tv < 0 or tv > 18:
                conn.close()
                return False
            data = dict(data)
            data["target_th_level"] = tv
        except (ValueError, TypeError):
            conn.close()
            return False

    # 起号序号：可人工编辑，但起号范围内不允许重复（空值可重复/不参与）
    if "raising_seq" in data:
        data = dict(data)
        raw_seq = data["raising_seq"]
        if raw_seq in (None, ""):
            data["raising_seq"] = None
        else:
            try:
                seq = int(raw_seq)
            except (ValueError, TypeError):
                conn.close()
                return False
            if seq < 0:
                conn.close()
                return False
            dup = conn.execute(
                "SELECT id FROM accounts WHERE raising_seq = ? AND id != ? "
                "AND device_number IS NOT NULL AND device_number != ''",
                (seq, account_id)
            ).fetchone()
            if dup:
                conn.close()
                return False
            data["raising_seq"] = seq

    # 允许在起号子界面修改的字段
    allowed_fields = [
        "owner_name", "account_name", "binding_detail", "account_id",
        "town_hall_level", "target_th_level", "device_number", "last_login_date",
        "raising_seq",
    ]

    fields = []
    params = []
    for key in allowed_fields:
        if key in data:
            fields.append(f"{key} = ?")
            params.append(data[key])

    if not fields:
        conn.close()
        return False

    fields.append("updated_at = datetime('now', 'localtime')")
    params.append(account_id)

    conn.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()

    log_operation(
        "修改起号",
        "account",
        account_id,
        f"在起号子界面修改: {data.get('account_name', '')}"
    )
    return True


if __name__ == "__main__":
    init_db()
