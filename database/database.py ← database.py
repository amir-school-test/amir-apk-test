import os
import re
import hmac
import sqlite3
import logging
import hashlib
import secrets

from contextlib import contextmanager
from datetime import datetime

try:
    from kivy.app import App
except ImportError:
    App = None


# ============================================================
# CONFIGURATION
# ============================================================

DATABASE_FILENAME = "amir_school_system.db"

CREATE_DEMO_DATA = False

# رقم نسخة هيكل قاعدة البيانات (يُحفظ في PRAGMA user_version).
# ارفعه عند أي تغيير في الهيكل، لنعرف أي قاعدة قديمة تحتاج ترقية.
SCHEMA_VERSION = 2

DATABASE_TIMEOUT = 10
DATABASE_BUSY_TIMEOUT_MS = 10000

VALID_ADMIN_MODES = (
    "EXAM",
    "SICK",
    "SCHOOL_APPROVAL",
)

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE PATH
# ============================================================

def _is_android():
    return (
        "ANDROID_ARGUMENT" in os.environ
        or "ANDROID_PRIVATE" in os.environ
    )


def get_db_path():
    """
    مسار قاعدة البيانات.

    داخل تطبيق Kivy: مجلد بيانات التطبيق.
    على أندرويد بدون تطبيق شغّال: خطأ صريح، حتى لا تُنشأ
    قاعدة ثانية فارغة في مكان خاطئ.
    على سطح المكتب (تطوير/اختبار): المجلد الحالي.
    """

    if App is not None:
        try:
            app = App.get_running_app()

            if app is not None:
                user_data_dir = getattr(app, "user_data_dir", None)

                if user_data_dir:
                    os.makedirs(user_data_dir, exist_ok=True)
                    return os.path.join(user_data_dir, DATABASE_FILENAME)

        except Exception:
            logger.exception("Could not determine Kivy database directory.")

    if _is_android():
        raise RuntimeError(
            "Database path is unavailable: the Kivy app is not running yet. "
            "Refusing to create a database in an unknown location."
        )

    return os.path.abspath(DATABASE_FILENAME)


# ============================================================
# CONNECTION MANAGEMENT
# ============================================================

@contextmanager
def get_connection():
    db_path = get_db_path()
    connection = None

    try:
        parent_dir = os.path.dirname(db_path)

        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        connection = sqlite3.connect(db_path, timeout=DATABASE_TIMEOUT)
        connection.row_factory = sqlite3.Row

        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {DATABASE_BUSY_TIMEOUT_MS}")

        yield connection

        connection.commit()

    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                logger.exception("Database rollback failed.")
        raise

    finally:
        if connection is not None:
            connection.close()


# ============================================================
# GENERAL HELPERS
# ============================================================

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _table_exists(cursor, table_name):
    row = cursor.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (table_name,)
    ).fetchone()

    return row is not None


def _quote_identifier(identifier):
    if not isinstance(identifier, str):
        raise ValueError("SQL identifier must be a string.")
    return '"' + identifier.replace('"', '""') + '"'


def _get_table_columns(cursor, table_name):
    if not _table_exists(cursor, table_name):
        return set()

    safe_name = _quote_identifier(table_name)
    rows = cursor.execute(f"PRAGMA table_info({safe_name})").fetchall()

    return {row["name"] for row in rows}


def _ensure_column(cursor, table_name, column_name, column_definition):
    if not _table_exists(cursor, table_name):
        return False

    if column_name in _get_table_columns(cursor, table_name):
        return False

    safe_table = _quote_identifier(table_name)
    safe_column = _quote_identifier(column_name)

    cursor.execute(
        f"ALTER TABLE {safe_table} ADD COLUMN {safe_column} {column_definition}"
    )

    return True


def _normalize_optional_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def _normalize_required_text(value):
    if value is None:
        return ""
    return str(value).strip()


# ============================================================
# GRADE / SECTION NORMALIZATION
# ============================================================
#
# القاعدة الموحدة في كل المشروع:
#   grade   = رقم فقط، مثل "12"  (يُعرض "Grade 12" في التقارير)
#   section = حرف كبير، مثل "A"
# ============================================================

def normalize_grade(value):
    """
    "Grade 12" -> "12"
    "Gr 9"     -> "9"
    "12"       -> "12"
    قيمة غير رقمية (مثل KG) تبقى كما هي.
    """

    text = _normalize_optional_text(value)

    if text is None:
        return None

    match = re.search(r"\d{1,2}", text)

    if match:
        return str(int(match.group()))

    return text


def normalize_section(value):
    text = _normalize_optional_text(value)

    if text is None:
        return None

    return text.upper()


def _extract_legacy_grade_and_section(name):
    """
    استخراج الصف والشعبة من اسم قديم مثل:
    Amir (Gr12) / Amir (Grade 12 A)
    الصف يرجع رقمًا فقط.
    """

    if not name:
        return None, None

    text = str(name).strip()

    patterns = [
        r"\bGrade\s*(\d{1,2})\s*(?:[-,/ ]\s*(?:Section\s*)?([A-Za-z]))?\b",
        r"\bGr\s*(\d{1,2})\s*(?:[-,/ ]\s*([A-Za-z]))?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            grade = str(int(match.group(1)))
            section = match.group(2)

            if section:
                section = section.upper()

            return grade, section

    return None, None


# ============================================================
# STUDENTS TABLE MIGRATION
# ============================================================

def _students_table_needs_migration(cursor):
    if not _table_exists(cursor, "students"):
        return False

    rows = cursor.execute('PRAGMA table_info("students")').fetchall()
    column_info = {row["name"]: row for row in rows}

    required_columns = {"student_id", "phone", "name", "grade", "section"}

    if not required_columns.issubset(set(column_info)):
        return True

    if column_info["student_id"]["pk"] != 1:
        return True

    # TEXT PRIMARY KEY يقبل NULL في SQLite ما لم يُكتب NOT NULL صراحة.
    if column_info["student_id"]["notnull"] != 1:
        return True

    if column_info["phone"]["pk"] != 0:
        return True

    indexes = cursor.execute('PRAGMA index_list("students")').fetchall()

    for index in indexes:
        if not index["unique"]:
            continue

        safe_index = _quote_identifier(index["name"])
        index_columns = cursor.execute(f"PRAGMA index_info({safe_index})").fetchall()
        indexed_columns = [item["name"] for item in index_columns]

        if indexed_columns == ["phone"]:
            return True

    return False


def _migrate_students_table(cursor):
    if not _table_exists(cursor, "students"):
        return

    columns = _get_table_columns(cursor, "students")

    if "student_id" not in columns:
        raise RuntimeError("Cannot safely migrate students: student_id column is missing.")

    rows = cursor.execute('SELECT * FROM "students"').fetchall()
    students = []
    seen_ids = set()

    for row in rows:
        row_data = dict(row)
        student_id = _normalize_required_text(row_data.get("student_id"))

        if not student_id:
            raise RuntimeError("Student migration stopped: an empty student_id was found.")
        if student_id in seen_ids:
            raise RuntimeError(f"Student migration stopped: duplicate student_id found: {student_id}")

        seen_ids.add(student_id)

        phone = _normalize_optional_text(row_data.get("phone"))
        name = _normalize_required_text(row_data.get("name"))
        grade = normalize_grade(row_data.get("grade"))
        section = normalize_section(row_data.get("section"))

        if not grade or not section:
            inferred_grade, inferred_section = _extract_legacy_grade_and_section(name)
            grade = grade or inferred_grade
            section = section or inferred_section

        active = 0 if row_data.get("active") == 0 else 1

        students.append((student_id, phone, name, grade, section, active))

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS students_migration_backup (
            student_id TEXT PRIMARY KEY NOT NULL,
            phone TEXT,
            name TEXT,
            grade TEXT,
            section TEXT,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cursor.execute("DELETE FROM students_migration_backup")
    cursor.executemany(
        """
        INSERT INTO students_migration_backup
            (student_id, phone, name, grade, section, active)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        students
    )

    cursor.execute('DROP TABLE "students"')
    cursor.execute(
        """
        CREATE TABLE students (
            student_id TEXT PRIMARY KEY NOT NULL,
            phone TEXT,
            name TEXT NOT NULL,
            grade TEXT,
            section TEXT,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO students (student_id, phone, name, grade, section, active)
        SELECT student_id, phone, COALESCE(name, ''), grade, section, active
        FROM students_migration_backup
        """
    )
    cursor.execute("DROP TABLE students_migration_backup")


# ============================================================
# SETTINGS TABLE (key / value) - يطابق auth_service.py
# ============================================================

def _settings_needs_rebuild(cursor):
    if not _table_exists(cursor, "settings"):
        return False

    rows = cursor.execute('PRAGMA table_info("settings")').fetchall()
    info = {row["name"]: row for row in rows}

    if "key" not in info or "value" not in info:
        return True

    # بقايا النسخة الخاطئة السابقة.
    if "setting_key" in info or "setting_value" in info:
        return True

    if info["key"]["pk"] != 1:
        return True

    return False


def _rebuild_settings_table(cursor):
    """
    إعادة بناء settings إلى الشكل:
        key TEXT PRIMARY KEY NOT NULL, value TEXT
    مع نقل أي بيانات موجودة من key/value أو setting_key/setting_value.
    """

    rows = cursor.execute('SELECT * FROM "settings"').fetchall()
    settings = {}

    for row in rows:
        data = dict(row)

        key = _normalize_optional_text(
            data.get("key") or data.get("setting_key")
        )

        if not key:
            continue

        value = data.get("value")

        if value is None:
            value = data.get("setting_value")

        settings[key] = value

    cursor.execute("DROP TABLE IF EXISTS settings_new")
    cursor.execute(
        """
        CREATE TABLE settings_new (
            key TEXT PRIMARY KEY NOT NULL,
            value TEXT
        )
        """
    )
    cursor.executemany(
        "INSERT INTO settings_new (key, value) VALUES (?, ?)",
        list(settings.items())
    )
    cursor.execute('DROP TABLE "settings"')
    cursor.execute("ALTER TABLE settings_new RENAME TO settings")


def _ensure_settings_table(cursor):
    if _settings_needs_rebuild(cursor):
        _rebuild_settings_table(cursor)
        return

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY NOT NULL,
            value TEXT
        )
        """
    )


# ============================================================
# TABLE CREATION
# ============================================================

def _create_tables(cursor):
    # STUDENTS
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY NOT NULL,
            phone TEXT,
            name TEXT NOT NULL,
            grade TEXT,
            section TEXT,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    # active = 0 للطالب الذي غادر المدرسة: لا يُحذف (سجلاته تبقى)،
    # لكنه لا يُسجَّل غائبًا ولا يمر من البوابة.
    _ensure_column(cursor, "students", "active", "INTEGER NOT NULL DEFAULT 1")

    # ATTENDANCE
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            date_val TEXT NOT NULL,
            time_val TEXT NOT NULL,
            record_type TEXT NOT NULL,
            status TEXT NOT NULL,
            day_name TEXT,
            FOREIGN KEY (student_id)
                REFERENCES students(student_id)
                ON DELETE RESTRICT
        )
        """
    )

    attendance_columns = _get_table_columns(cursor, "attendance")
    required_attendance_columns = {"id", "student_id", "date_val", "time_val", "record_type", "status"}

    missing_attendance_columns = required_attendance_columns - attendance_columns

    if missing_attendance_columns:
        raise RuntimeError(
            "The existing attendance table is missing required columns: "
            + ", ".join(sorted(missing_attendance_columns))
        )

    _ensure_column(cursor, "attendance", "day_name", "TEXT")

    # إلغاء سجل (مثل غياب خاطئ) بدون حذفه: يبقى للتدقيق.
    _ensure_column(cursor, "attendance", "voided_at", "TEXT")
    _ensure_column(cursor, "attendance", "voided_by", "TEXT")
    _ensure_column(cursor, "attendance", "void_reason", "TEXT")

    # SETTINGS (key/value)
    _ensure_settings_table(cursor)

    # PASSCODES (legacy)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS passcodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            name TEXT,
            passcode_hash TEXT,
            created_at TEXT
        )
        """
    )

    _ensure_column(cursor, "passcodes", "code", "TEXT")
    _ensure_column(cursor, "passcodes", "active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(cursor, "passcodes", "name", "TEXT")
    _ensure_column(cursor, "passcodes", "passcode_hash", "TEXT")
    _ensure_column(cursor, "passcodes", "created_at", "TEXT")

    # SYSTEM MODES
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_modes (
            mode_name TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0,
            opened_at TEXT,
            opened_by TEXT,
            expires_at TEXT
        )
        """
    )

    _ensure_column(cursor, "system_modes", "active", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(cursor, "system_modes", "opened_at", "TEXT")
    _ensure_column(cursor, "system_modes", "opened_by", "TEXT")
    _ensure_column(cursor, "system_modes", "expires_at", "TEXT")

    # ADMIN QR TOKENS
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_qr_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode_name TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            FOREIGN KEY (mode_name)
                REFERENCES system_modes(mode_name)
        )
        """
    )

    _ensure_column(cursor, "admin_qr_tokens", "mode_name", "TEXT")
    _ensure_column(cursor, "admin_qr_tokens", "token_hash", "TEXT")
    _ensure_column(cursor, "admin_qr_tokens", "active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(cursor, "admin_qr_tokens", "created_at", "TEXT")

    # SYSTEM EVENT LOGS
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_event_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT,
            event_type TEXT NOT NULL,
            student_id TEXT,
            details TEXT,
            success INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    _ensure_column(cursor, "system_event_logs", "event_time", "TEXT")
    _ensure_column(cursor, "system_event_logs", "event_type", "TEXT")
    _ensure_column(cursor, "system_event_logs", "student_id", "TEXT")
    _ensure_column(cursor, "system_event_logs", "details", "TEXT")
    _ensure_column(cursor, "system_event_logs", "success", "INTEGER NOT NULL DEFAULT 1")

    # SMS LOGS
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            student_id TEXT,
            phone TEXT,
            message_type TEXT,
            result TEXT,
            details TEXT
        )
        """
    )

    _ensure_column(cursor, "sms_logs", "created_at", "TEXT")
    _ensure_column(cursor, "sms_logs", "student_id", "TEXT")
    _ensure_column(cursor, "sms_logs", "phone", "TEXT")
    _ensure_column(cursor, "sms_logs", "message_type", "TEXT")
    _ensure_column(cursor, "sms_logs", "result", "TEXT")
    _ensure_column(cursor, "sms_logs", "details", "TEXT")
    _ensure_column(cursor, "sms_logs", "attendance_id", "INTEGER")


# ============================================================
# NORMALIZE EXISTING STUDENT DATA
# ============================================================

def _normalize_existing_students(cursor):
    """
    توحيد grade/section للطلاب الموجودين:
        "Grade 12" -> "12"،  "a" -> "A"
    لا يغيّر أي بيانات أخرى.
    """

    rows = cursor.execute(
        "SELECT student_id, grade, section FROM students"
    ).fetchall()

    for row in rows:
        new_grade = normalize_grade(row["grade"])
        new_section = normalize_section(row["section"])

        if new_grade != row["grade"] or new_section != row["section"]:
            cursor.execute(
                """
                UPDATE students
                SET grade = ?, section = ?
                WHERE student_id = ?
                """,
                (new_grade, new_section, row["student_id"])
            )


# ============================================================
# AUDIT PROTECTION (triggers)
# ============================================================
#
# سجلات الحضور وسجل الأحداث دليل قانوني: لا تُحذف ولا تُعدَّل.
# الاستثناء الوحيد: إلغاء سجل (voided_*) عبر void_absence_record.
# لحذف بيانات التجربة أثناء التطوير: احذف ملف قاعدة البيانات نفسه.
# ============================================================

def _create_triggers(cursor):
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_attendance_no_delete
        BEFORE DELETE ON attendance
        BEGIN
            SELECT RAISE(ABORT, 'Attendance records cannot be deleted. Void them instead.');
        END
        """
    )

    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_attendance_protect_update
        BEFORE UPDATE ON attendance
        WHEN OLD.voided_at IS NOT NULL
          OR NEW.id IS NOT OLD.id
          OR NEW.student_id IS NOT OLD.student_id
          OR NEW.date_val IS NOT OLD.date_val
          OR NEW.time_val IS NOT OLD.time_val
          OR NEW.record_type IS NOT OLD.record_type
          OR NEW.status IS NOT OLD.status
          OR NEW.day_name IS NOT OLD.day_name
        BEGIN
            SELECT RAISE(ABORT, 'Attendance records cannot be modified.');
        END
        """
    )

    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_event_logs_no_delete
        BEFORE DELETE ON system_event_logs
        BEGIN
            SELECT RAISE(ABORT, 'Event logs cannot be deleted.');
        END
        """
    )

    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_event_logs_no_update
        BEFORE UPDATE ON system_event_logs
        BEGIN
            SELECT RAISE(ABORT, 'Event logs cannot be modified.');
        END
        """
    )


# ============================================================
# INDEXES
# ============================================================

def _create_indexes(cursor):
    indexes = [
        ("idx_students_phone", "students", "phone"),
        ("idx_students_grade_section", "students", "grade, section"),
        ("idx_students_active", "students", "active"),
        ("idx_attendance_student_date", "attendance", "student_id, date_val"),
        ("idx_attendance_date", "attendance", "date_val"),
        ("idx_admin_qr_mode_active", "admin_qr_tokens", "mode_name, active"),
        ("idx_event_logs_time", "system_event_logs", "event_time"),
        ("idx_event_logs_type", "system_event_logs", "event_type"),
        ("idx_sms_logs_time", "sms_logs", "created_at"),
        ("idx_sms_logs_student", "sms_logs", "student_id"),
        ("idx_sms_logs_result", "sms_logs", "result"),
        ("idx_sms_logs_attendance", "sms_logs", "attendance_id"),
    ]

    for index_name, table_name, columns in indexes:
        if not _table_exists(cursor, table_name):
            continue

        available_columns = _get_table_columns(cursor, table_name)
        requested_columns = [item.strip() for item in columns.split(",")]

        if not all(column in available_columns for column in requested_columns):
            continue

        safe_index = _quote_identifier(index_name)
        safe_table = _quote_identifier(table_name)
        safe_columns = ", ".join(_quote_identifier(column) for column in requested_columns)

        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {safe_index} ON {safe_table} ({safe_columns})"
        )


# ============================================================
# SYSTEM MODE INITIALIZATION
# ============================================================

def _initialize_system_modes(cursor):
    for mode_name in VALID_ADMIN_MODES:
        cursor.execute(
            """
            INSERT OR IGNORE INTO system_modes (mode_name, active, opened_at, opened_by, expires_at)
            VALUES (?, 0, NULL, NULL, NULL)
            """,
            (mode_name,)
        )


# ============================================================
# ADMIN QR TOKEN SECURITY
# ============================================================

def hash_admin_qr_token(token):
    if token is None:
        raise ValueError("Admin QR token cannot be empty.")

    token = str(token).strip()

    if not token:
        raise ValueError("Admin QR token cannot be empty.")

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_admin_qr_token(mode_name, token_length=32):
    if mode_name not in VALID_ADMIN_MODES:
        raise ValueError("Invalid admin mode.")

    try:
        token_length = int(token_length)
    except (TypeError, ValueError):
        raise ValueError("token_length must be an integer.")

    if not 16 <= token_length <= 128:
        raise ValueError("token_length must be between 16 and 128.")

    raw_token = secrets.token_urlsafe(token_length)
    token_hash = hash_admin_qr_token(raw_token)

    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("UPDATE admin_qr_tokens SET active = 0 WHERE mode_name = ?", (mode_name,))
        cursor.execute(
            """
            INSERT INTO admin_qr_tokens (mode_name, token_hash, active, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (mode_name, token_hash, _now())
        )

    return raw_token


def validate_admin_qr_token(mode_name, token):
    if mode_name not in VALID_ADMIN_MODES or token is None:
        return False

    token = str(token).strip()

    if not token:
        return False

    try:
        token_hash = hash_admin_qr_token(token)

        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT token_hash
                FROM admin_qr_tokens
                WHERE mode_name = ? AND active = 1
                """,
                (mode_name,)
            ).fetchall()

        return any(
            hmac.compare_digest(str(row["token_hash"] or ""), token_hash)
            for row in rows
        )

    except Exception:
        logger.exception("Admin QR token validation failed.")
        return False


# ============================================================
# SYSTEM EVENT LOGGING
# ============================================================

def log_system_event(event_type, student_id=None, details=None, success=True):
    event_type = _normalize_required_text(event_type)

    if not event_type:
        raise ValueError("event_type is required.")

    student_id = _normalize_optional_text(student_id)
    details = _normalize_optional_text(details)

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO system_event_logs (event_time, event_type, student_id, details, success)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_now(), event_type, student_id, details, 1 if success else 0)
        )


# ============================================================
# PHONE PRIVACY
# ============================================================

def _mask_phone(phone):
    if phone is None:
        return None

    digits = re.sub(r"\D", "", str(phone))

    if not digits:
        return None

    if len(digits) <= 2:
        return "*" * len(digits)

    return "*" * (len(digits) - 2) + digits[-2:]


# ============================================================
# SMS RESULT LOGGING
# ============================================================

def log_sms_result(message_type, result, student_id=None, phone=None, details=None, attendance_id=None):
    message_type = _normalize_required_text(message_type)
    result = _normalize_required_text(result)

    if not message_type:
        raise ValueError("message_type is required.")
    if not result:
        raise ValueError("result is required.")

    student_id = _normalize_optional_text(student_id)
    details = _normalize_optional_text(details)

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sms_logs
                (created_at, student_id, phone, message_type, result, details, attendance_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_now(), student_id, _mask_phone(phone), message_type, result, details, attendance_id)
        )


# ============================================================
# STUDENT LISTS (ترتيب موحد لكل الشاشات والتقارير)
# ============================================================
#
# الترتيب: الصف رقميًا (9 قبل 12)، ثم الشعبة، ثم الاسم.
# الطالب بلا صف أو شعبة يظهر في آخر القائمة ولا يختفي.
# ============================================================

def grade_section_label(grade, section):
    """
    ("12", "A") -> "Grade 12 - Section A"
    (None, None) -> "Other"
    """

    grade = normalize_grade(grade)
    section = normalize_section(section)

    if not grade:
        return "Other"

    label = f"Grade {grade}" if grade.isdigit() else grade

    if section:
        label += f" - Section {section}"

    return label


def get_students_ordered(active_only=True):
    """
    قائمة dict: student_id, phone, name, grade, section, active
    مرتبة ترتيبًا صحيحًا للعرض والتقارير.
    """

    where = "WHERE active = 1" if active_only else ""

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT student_id, phone, name, grade, section, active
            FROM students
            {where}
            ORDER BY
                CASE WHEN grade GLOB '[0-9]*'
                     THEN CAST(grade AS INTEGER)
                     ELSE 9999 END,
                UPPER(COALESCE(section, '~')),
                name COLLATE NOCASE,
                student_id
            """
        ).fetchall()

    return [dict(row) for row in rows]


# ============================================================
# ABSENCE COUNTER (محسوب من السجلات - لا يوجد قاعدة فصل)
# ============================================================
#
# العدّاد معلومة للمدير فقط. لا يقرر شيئًا.
# حد الفصل تحدده كل مدرسة بنفسها (10 أو 20 أو 26...).
# العدّاد يحسب أيام غياب مختلفة، ولا يحسب السجلات الملغاة.
# ============================================================

_ABSENCE_CONDITION = (
    "voided_at IS NULL "
    "AND (record_type IN ('ABSENT-RECORD', 'ABSENT') "
    "OR UPPER(TRIM(status)) = 'ABSENT')"
)


def _date_filter(since, until):
    clause = ""
    params = []

    if since:
        clause += " AND date_val >= ?"
        params.append(str(since))

    if until:
        clause += " AND date_val <= ?"
        params.append(str(until))

    return clause, params


def get_absence_counts(since=None, until=None):
    """
    {student_id: عدد أيام الغياب}

    since / until بصيغة YYYY-MM-DD (اختياري)، لتحديد فترة
    مثل الفصل الدراسي. بدونهما يُحسب كل السجل.
    الطلاب بدون غياب لا يظهرون في النتيجة.
    """

    clause, params = _date_filter(since, until)

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT student_id, COUNT(DISTINCT date_val) AS days
            FROM attendance
            WHERE {_ABSENCE_CONDITION}{clause}
            GROUP BY student_id
            """,
            params
        ).fetchall()

    return {row["student_id"]: row["days"] for row in rows}


def get_student_absences(student_id, since=None, until=None):
    """
    سجلات الغياب الفعلية لطالب (مع id لإلغاء سجل خاطئ).
    ترجع قائمة dict: id, date_val, time_val.
    """

    student_id = _normalize_required_text(student_id)

    if not student_id:
        return []

    clause, params = _date_filter(since, until)

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT id, date_val, time_val
            FROM attendance
            WHERE student_id = ? AND {_ABSENCE_CONDITION}{clause}
            ORDER BY date_val DESC, id DESC
            """,
            [student_id] + params
        ).fetchall()

    return [dict(row) for row in rows]


def void_absence_record(attendance_id, voided_by, reason):
    """
    إلغاء سجل غياب خاطئ بدون حذفه.

    - يسمح فقط بسجلات الغياب (لا يمكن إلغاء دخول أو خروج).
    - السبب إجباري ويُسجل مع من ألغى ومتى.
    - يرجع (True/False, message).

    مهم: attendance_service والتقارير يجب أن يتجاهلوا
    السجلات التي voided_at فيها ليس NULL.
    """

    voided_by = _normalize_required_text(voided_by)
    reason = _normalize_required_text(reason)

    if not voided_by:
        return False, "Admin name is required."

    if len(reason) < 3:
        return False, "A reason is required."

    try:
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, student_id, record_type, status, voided_at
                FROM attendance
                WHERE id = ?
                """,
                (attendance_id,)
            ).fetchone()

            if row is None:
                return False, "Record not found."

            if row["voided_at"]:
                return False, "Record is already voided."

            is_absence = (
                str(row["record_type"]).upper() in ("ABSENT-RECORD", "ABSENT")
                or str(row["status"]).strip().upper() == "ABSENT"
            )

            if not is_absence:
                return False, "Only absence records can be voided."

            connection.execute(
                """
                UPDATE attendance
                SET voided_at = ?, voided_by = ?, void_reason = ?
                WHERE id = ?
                """,
                (_now(), voided_by, reason, attendance_id)
            )

            connection.execute(
                """
                INSERT INTO system_event_logs
                    (event_time, event_type, student_id, details, success)
                VALUES (?, 'ABSENCE_VOIDED', ?, ?, 1)
                """,
                (
                    _now(),
                    row["student_id"],
                    f"record {attendance_id} voided by {voided_by}: {reason}"
                )
            )

        return True, "Absence record voided."

    except Exception:
        logger.exception("Could not void absence record.")
        return False, "Database error while voiding the record."


# ============================================================
# OPTIONAL DEMO DATA
# ============================================================

def _insert_demo_data(cursor):
    if not CREATE_DEMO_DATA:
        return

    demo_students = [
        ("DEMO001", None, "Demo Student One", "12", "A"),
        ("DEMO002", None, "Demo Student Two", "11", "B"),
    ]

    for student in demo_students:
        cursor.execute(
            """
            INSERT OR IGNORE INTO students (student_id, phone, name, grade, section)
            VALUES (?, ?, ?, ?, ?)
            """,
            student
        )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_sqlite_db():
    db_path = get_db_path()
    parent_dir = os.path.dirname(db_path)

    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    connection = None
    transaction_started = False

    try:
        connection = sqlite3.connect(db_path, timeout=DATABASE_TIMEOUT)
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()

        cursor.execute(f"PRAGMA busy_timeout = {DATABASE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN IMMEDIATE")
        transaction_started = True

        if _students_table_needs_migration(cursor):
            _migrate_students_table(cursor)

        _create_tables(cursor)
        _create_triggers(cursor)
        _normalize_existing_students(cursor)
        _initialize_system_modes(cursor)
        _create_indexes(cursor)
        _insert_demo_data(cursor)

        foreign_key_errors = cursor.execute("PRAGMA foreign_key_check").fetchall()

        if foreign_key_errors:
            raise RuntimeError(
                f"Foreign-key integrity check failed: {len(foreign_key_errors)} violation(s) found."
            )

        cursor.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")

        connection.commit()
        transaction_started = False

        cursor.execute("PRAGMA foreign_keys = ON")
        fk_status = cursor.execute("PRAGMA foreign_keys").fetchone()

        if fk_status is None or fk_status[0] != 1:
            raise RuntimeError("Could not enable SQLite foreign keys.")

        logger.info("Database initialized successfully: %s", db_path)
        return True

    except Exception:
        if connection is not None and transaction_started:
            try:
                connection.rollback()
            except Exception:
                logger.exception("Initialization rollback failed.")
        logger.exception("Database initialization failed.")
        raise

    finally:
        if connection is not None:
            connection.close()


# ============================================================
# DATABASE INTEGRITY
# ============================================================

def check_database_integrity():
    try:
        with get_connection() as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
        return len(rows) == 1 and rows[0][0] == "ok"
    except Exception:
        logger.exception("Database integrity check failed.")
        return False


def check_foreign_keys():
    try:
        with get_connection() as connection:
            rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        errors = [dict(row) for row in rows]
        return len(errors) == 0, errors
    except Exception as exc:
        logger.exception("Foreign-key check failed.")
        return False, [str(exc)]


# ============================================================
# DATABASE INFORMATION
# ============================================================

def get_database_info():
    info = {
        "database_path": get_db_path(),
        "sqlite_version": sqlite3.sqlite_version,
        "schema_version": None,
        "student_count": 0,
        "attendance_count": 0,
    }

    try:
        with get_connection() as connection:
            cursor = connection.cursor()

            info["schema_version"] = cursor.execute(
                "PRAGMA user_version"
            ).fetchone()[0]

            if _table_exists(cursor, "students"):
                info["student_count"] = cursor.execute(
                    "SELECT COUNT(*) FROM students"
                ).fetchone()[0]

            if _table_exists(cursor, "attendance"):
                info["attendance_count"] = cursor.execute(
                    "SELECT COUNT(*) FROM attendance"
                ).fetchone()[0]

    except Exception:
        logger.exception("Could not collect database information.")
        raise

    return info


# ============================================================
# DIRECT EXECUTION (desktop testing only)
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        init_sqlite_db()
        print("Database initialization succeeded.")
        print("Database information:", get_database_info())
        print("Integrity check:", check_database_integrity())

        foreign_keys_ok, foreign_key_errors = check_foreign_keys()
        print("Foreign-key check:", foreign_keys_ok)

        if foreign_key_errors:
            print("Foreign-key errors:", foreign_key_errors)

    except Exception as exc:
        print("Database initialization failed:", exc)
