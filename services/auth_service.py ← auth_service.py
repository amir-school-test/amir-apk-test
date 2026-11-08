import sqlite3
import hashlib
import hmac
import secrets
import logging
import time

from database.database import get_db_path


# =========================================================
# إعدادات المصادقة
# =========================================================

ADMIN_PASSWORD_KEY = "admin_password"

# كلمة المرور الافتراضية للتوافق مع النظام الحالي.
#
# مهمة:
# يجب إجبار المسؤول على تغييرها بعد أول تسجيل دخول.
DEFAULT_ADMIN_PASSWORD = "9999"


# =========================================================
# PBKDF2
# =========================================================

PASSWORD_PREFIX = "PBKDF2_SHA256"

# عدد الدورات الجديد.
#
# PBKDF2-HMAC-SHA256 مع 600,000 دورة هو المستوى
# الذي نستخدمه هنا كإعداد أمان قوي.
PBKDF2_ITERATIONS = 600_000

# الحد الأعلى لمنع Hash مزور يحتوي على عدد دورات
# ضخم جدًا يسبب استهلاكًا غير ضروري للمعالج.
MAX_PBKDF2_ITERATIONS = 1_000_000


# =========================================================
# سياسة كلمة المرور
# =========================================================

MIN_PASSWORD_LENGTH = 6

# حد أعلى عملي لمنع إدخال كلمة مرور ضخمة جدًا
# تسبب استهلاكًا غير ضروري للموارد.
MAX_PASSWORD_LENGTH = 256


# =========================================================
# حماية من Brute Force
# =========================================================

MAX_FAILED_ATTEMPTS = 5

LOCKOUT_SECONDS = 60

_failed_attempts = 0
_locked_until = 0.0


# =========================================================
# الاتصال بقاعدة البيانات
# =========================================================

def _get_connection():
    """
    فتح اتصال بقاعدة بيانات AMIR SYSTEM.
    """

    db_path = get_db_path()

    conn = sqlite3.connect(
        db_path
    )

    try:
        conn.execute(
            "PRAGMA foreign_keys = ON;"
        )
    except Exception as e:
        logging.debug(
            f"Could not enable foreign keys: {e}"
        )

    return conn


# =========================================================
# التحقق من طول كلمة المرور
# =========================================================

def _validate_password_length(password):
    """
    التحقق من أن كلمة المرور ضمن الحجم المسموح.
    """

    if password is None:
        return False

    password = str(password)

    if not password:
        return False

    if len(password) > MAX_PASSWORD_LENGTH:
        return False

    return True


# =========================================================
# إنشاء Hash آمن
# =========================================================

def _create_password_hash(password):
    """
    إنشاء Hash آمن باستخدام:

    PBKDF2-HMAC-SHA256 + Salt عشوائي.

    الصيغة المخزنة:

    PBKDF2_SHA256$iterations$salt$hash
    """

    password = str(password)

    salt = secrets.token_bytes(
        32
    )

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS
    )

    return (
        f"{PASSWORD_PREFIX}$"
        f"{PBKDF2_ITERATIONS}$"
        f"{salt.hex()}$"
        f"{password_hash.hex()}"
    )


# =========================================================
# تحليل PBKDF2 Hash
# =========================================================

def _parse_pbkdf2_hash(stored_hash):
    """
    تحليل Hash المخزن والتحقق من بنيته.

    يرجع:

        (iterations, salt, digest)

    أو:

        None
    """

    try:

        parts = str(
            stored_hash
        ).split("$")

        if len(parts) != 4:
            return None

        prefix = parts[0]

        if prefix != PASSWORD_PREFIX:
            return None

        iterations = int(
            parts[1]
        )

        if (
            iterations <= 0
            or iterations > MAX_PBKDF2_ITERATIONS
        ):
            return None

        salt_hex = parts[2]
        digest_hex = parts[3]

        salt = bytes.fromhex(
            salt_hex
        )

        digest = bytes.fromhex(
            digest_hex
        )

        # SHA-256 يعطي 32 bytes.
        if len(digest) != 32:
            return None

        # يجب أن يكون Salt غير فارغ.
        if len(salt) < 16:
            return None

        return (
            iterations,
            salt,
            digest
        )

    except (
        ValueError,
        TypeError,
        UnicodeError
    ):

        return None

    except Exception as e:

        logging.error(
            f"PBKDF2 hash parsing error: {e}"
        )

        return None


# =========================================================
# التحقق من PBKDF2
# =========================================================

def _verify_pbkdf2_password(
    password,
    stored_hash
):
    """
    التحقق من كلمة المرور المخزنة بصيغة PBKDF2.

    يرجع:

        (valid, iterations)

    أو:

        (False, None)
    """

    try:

        parsed = _parse_pbkdf2_hash(
            stored_hash
        )

        if parsed is None:
            return False, None

        (
            iterations,
            salt,
            stored_digest
        ) = parsed

        calculated_digest = (
            hashlib.pbkdf2_hmac(
                "sha256",
                str(password).encode(
                    "utf-8"
                ),
                salt,
                iterations
            )
        )

        valid = hmac.compare_digest(
            calculated_digest,
            stored_digest
        )

        return (
            valid,
            iterations
        )

    except Exception as e:

        logging.error(
            f"PBKDF2 verification error: {e}"
        )

        return False, None


# =========================================================
# دعم SHA-256 القديم
# =========================================================

def _verify_legacy_sha256(
    password,
    stored_hash
):
    """
    التحقق من SHA-256 القديم.

    يستخدم فقط للتوافق مع قواعد البيانات القديمة.
    """

    try:

        calculated_hash = hashlib.sha256(
            str(password).encode(
                "utf-8"
            )
        ).hexdigest()

        return hmac.compare_digest(
            calculated_hash,
            str(stored_hash)
        )

    except Exception as e:

        logging.error(
            f"Legacy SHA-256 verification error: {e}"
        )

        return False


# =========================================================
# التأكد من جدول Settings
# =========================================================

def _ensure_settings_table(cursor):
    """
    التأكد من وجود جدول settings.
    """

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


# =========================================================
# حماية Brute Force
# =========================================================

def _is_login_locked():
    """
    التحقق هل تسجيل الدخول مقفل مؤقتًا.
    """

    global _locked_until

    current_time = time.monotonic()

    if current_time < _locked_until:
        return True

    if _locked_until != 0:
        _locked_until = 0.0

    return False


def _record_failed_attempt():
    """
    تسجيل محاولة دخول فاشلة.
    """

    global _failed_attempts
    global _locked_until

    _failed_attempts += 1

    if _failed_attempts >= MAX_FAILED_ATTEMPTS:

        _locked_until = (
            time.monotonic()
            + LOCKOUT_SECONDS
        )

        _failed_attempts = 0

        logging.warning(
            "Admin login temporarily locked "
            "after too many failed attempts."
        )


def _record_successful_login():
    """
    تصفير عداد المحاولات بعد تسجيل دخول ناجح.
    """

    global _failed_attempts
    global _locked_until

    _failed_attempts = 0
    _locked_until = 0.0


# =========================================================
# تهيئة كلمة مرور الأدمن
# =========================================================

def initialize_admin_password():
    """
    التأكد من وجود كلمة مرور للأدمن.

    إذا لم تكن موجودة:
    يتم إنشاء كلمة المرور الافتراضية
    وتخزين Hash فقط.

    لا يتم تخزين كلمة المرور نفسها.
    """

    try:

        with _get_connection() as conn:

            cursor = conn.cursor()

            _ensure_settings_table(
                cursor
            )

            cursor.execute(
                """
                SELECT value
                FROM settings
                WHERE key = ?
                LIMIT 1
                """,
                (
                    ADMIN_PASSWORD_KEY,
                )
            )

            row = cursor.fetchone()

            if row is not None:
                return True

            default_hash = (
                _create_password_hash(
                    DEFAULT_ADMIN_PASSWORD
                )
            )

            cursor.execute(
                """
                INSERT INTO settings
                (
                    key,
                    value
                )
                VALUES (?, ?)
                """,
                (
                    ADMIN_PASSWORD_KEY,
                    default_hash
                )
            )

            conn.commit()

        logging.warning(
            "Default admin password was created. "
            "It must be changed immediately."
        )

        return True

    except sqlite3.Error as e:

        logging.error(
            f"Admin password initialization "
            f"database error: {e}"
        )

        return False

    except Exception as e:

        logging.error(
            f"Admin password initialization error: {e}"
        )

        return False


# =========================================================
# Hash Password - دالة عامة
# =========================================================

def hash_password(password):
    """
    إنشاء Hash آمن لكلمة المرور.

    تستخدمها بقية أجزاء النظام عند الحاجة.

    ملاحظة:
    هذه الدالة لا تحفظ كلمة المرور في قاعدة البيانات.
    """

    if not _validate_password_length(
        password
    ):
        raise ValueError(
            "Invalid password length."
        )

    return _create_password_hash(
        password
    )


# =========================================================
# التحقق من كلمة مرور الأدمن
# =========================================================

def verify_admin_password(
    entered_password,
    app=None
):
    """
    التحقق من كلمة مرور الأدمن.

    يدعم:

    1. PBKDF2 الجديد.
    2. SHA-256 القديم.

    إذا كانت قاعدة البيانات تحتوي على SHA-256
    قديم، يتم ترقيته تلقائيًا إلى PBKDF2.

    إذا كان PBKDF2 صحيحًا لكنه يستخدم عدد دورات
    أقدم من الإعداد الحالي، يتم ترقيته أيضًا.

    app موجود للتوافق مع النظام القديم.
    """

    if _is_login_locked():

        logging.warning(
            "Admin login attempt blocked "
            "during temporary lockout."
        )

        return False

    try:

        if not _validate_password_length(
            entered_password
        ):
            _record_failed_attempt()
            return False

        entered_password = str(
            entered_password
        )

        with _get_connection() as conn:

            cursor = conn.cursor()

            _ensure_settings_table(
                cursor
            )

            cursor.execute(
                """
                SELECT value
                FROM settings
                WHERE key = ?
                LIMIT 1
                """,
                (
                    ADMIN_PASSWORD_KEY,
                )
            )

            row = cursor.fetchone()

            # -------------------------------------------------
            # لا توجد كلمة مرور بعد
            # -------------------------------------------------

            if row is None:

                default_hash = (
                    _create_password_hash(
                        DEFAULT_ADMIN_PASSWORD
                    )
                )

                try:

                    cursor.execute(
                        """
                        INSERT INTO settings
                        (
                            key,
                            value
                        )
                        VALUES (?, ?)
                        """,
                        (
                            ADMIN_PASSWORD_KEY,
                            default_hash
                        )
                    )

                    conn.commit()

                    stored_hash = (
                        default_hash
                    )

                except sqlite3.IntegrityError:

                    # حالة نادرة إذا قام اتصال آخر
                    # بإنشاء كلمة المرور في نفس الوقت.

                    cursor.execute(
                        """
                        SELECT value
                        FROM settings
                        WHERE key = ?
                        LIMIT 1
                        """,
                        (
                            ADMIN_PASSWORD_KEY,
                        )
                    )

                    row = cursor.fetchone()

                    if row is None:
                        _record_failed_attempt()
                        return False

                    stored_hash = str(
                        row[0]
                    )

            else:

                stored_hash = str(
                    row[0]
                )

            # -------------------------------------------------
            # PBKDF2 الجديد
            # -------------------------------------------------

            if stored_hash.startswith(
                PASSWORD_PREFIX + "$"
            ):

                (
                    valid,
                    iterations
                ) = _verify_pbkdf2_password(
                    entered_password,
                    stored_hash
                )

                if not valid:

                    _record_failed_attempt()

                    return False

                # ---------------------------------------------
                # ترقية عدد الدورات إذا كان قديمًا
                # ---------------------------------------------

                if (
                    iterations is not None
                    and iterations
                    < PBKDF2_ITERATIONS
                ):

                    upgraded_hash = (
                        _create_password_hash(
                            entered_password
                        )
                    )

                    cursor.execute(
                        """
                        UPDATE settings
                        SET value = ?
                        WHERE key = ?
                        """,
                        (
                            upgraded_hash,
                            ADMIN_PASSWORD_KEY
                        )
                    )

                    conn.commit()

                    logging.info(
                        "Admin password PBKDF2 "
                        "work factor was upgraded."
                    )

                _record_successful_login()

                return True

            # -------------------------------------------------
            # SHA-256 القديم
            # -------------------------------------------------

            if (
                len(stored_hash) == 64
                and all(
                    c in
                    "0123456789abcdefABCDEF"
                    for c in stored_hash
                )
            ):

                valid = (
                    _verify_legacy_sha256(
                        entered_password,
                        stored_hash
                    )
                )

                if not valid:

                    _record_failed_attempt()

                    return False

                # ---------------------------------------------
                # ترقية SHA-256 إلى PBKDF2
                # ---------------------------------------------

                new_hash = (
                    _create_password_hash(
                        entered_password
                    )
                )

                cursor.execute(
                    """
                    UPDATE settings
                    SET value = ?
                    WHERE key = ?
                    """,
                    (
                        new_hash,
                        ADMIN_PASSWORD_KEY
                    )
                )

                conn.commit()

                logging.info(
                    "Legacy admin password hash "
                    "was upgraded to PBKDF2."
                )

                _record_successful_login()

                return True

            # -------------------------------------------------
            # Hash غير معروف أو تالف
            # -------------------------------------------------

            logging.error(
                "Unknown or invalid admin "
                "password hash format."
            )

            _record_failed_attempt()

            return False

    except sqlite3.Error as e:

        logging.error(
            f"Admin password database error: {e}"
        )

        return False

    except Exception as e:

        logging.error(
            f"Admin password verification error: {e}"
        )

        return False


# =========================================================
# تغيير كلمة مرور الأدمن
# =========================================================

def update_admin_password(
    new_password,
    app=None
):
    """
    تغيير كلمة مرور الأدمن.

    يتم تخزين PBKDF2 Hash فقط.

    يرجع:

        (True, message)

    أو:

        (False, message)
    """

    try:

        if new_password is None:

            return (
                False,
                "New password cannot be empty."
            )

        # -------------------------------------------------
        # لا نستخدم strip()
        # -------------------------------------------------
        #
        # المسافات يمكن أن تكون جزءًا من كلمة المرور.

        new_password = str(
            new_password
        )

        if not new_password:

            return (
                False,
                "New password cannot be empty."
            )

        if len(new_password) > (
            MAX_PASSWORD_LENGTH
        ):

            return (
                False,
                "Password is too long."
            )

        if len(new_password) < (
            MIN_PASSWORD_LENGTH
        ):

            return (
                False,
                "Password must be at least "
                f"{MIN_PASSWORD_LENGTH} characters."
            )

        # -------------------------------------------------
        # إنشاء Hash
        # -------------------------------------------------

        new_hash = (
            _create_password_hash(
                new_password
            )
        )

        # -------------------------------------------------
        # حفظ Hash
        # -------------------------------------------------

        with _get_connection() as conn:

            cursor = conn.cursor()

            _ensure_settings_table(
                cursor
            )

            cursor.execute(
                """
                INSERT INTO settings
                (
                    key,
                    value
                )
                VALUES (?, ?)

                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value
                """,
                (
                    ADMIN_PASSWORD_KEY,
                    new_hash
                )
            )

            conn.commit()

        # كلمة المرور الجديدة تعني أن محاولات
        # الدخول القديمة لا يجب أن تبقى مقفلة.
        _record_successful_login()

        logging.info(
            "Admin password updated successfully."
        )

        return (
            True,
            "Password updated successfully."
        )

    except sqlite3.Error as e:

        logging.error(
            f"Admin password database error: {e}"
        )

        return (
            False,
            "Database error while updating password."
        )

    except Exception as e:

        logging.error(
            f"Admin password update error: {e}"
        )

        return (
            False,
            "System error while updating password."
        )


# =========================================================
# فحص وجود كلمة مرور الأدمن
# =========================================================

def has_admin_password():
    """
    التحقق من وجود كلمة مرور للأدمن.
    """

    try:

        with _get_connection() as conn:

            cursor = conn.cursor()

            _ensure_settings_table(
                cursor
            )

            cursor.execute(
                """
                SELECT 1
                FROM settings
                WHERE key = ?
                LIMIT 1
                """,
                (
                    ADMIN_PASSWORD_KEY,
                )
            )

            return (
                cursor.fetchone()
                is not None
            )

    except sqlite3.Error as e:

        logging.error(
            f"Error checking admin password: {e}"
        )

        return False

    except Exception as e:

        logging.error(
            f"Error checking admin password: {e}"
        )

        return False


# =========================================================
# التحقق هل كلمة المرور الافتراضية ما زالت مستخدمة
# =========================================================

def is_default_admin_password(
    entered_password
):
    """
    التحقق من أن كلمة المرور المدخلة
    هي كلمة المرور الافتراضية الحالية للنظام.

    هذه الدالة لا تعتمد فقط على مقارنة النص،
    بل تتحقق أيضًا من أن قاعدة البيانات ما زالت
    تقبل كلمة المرور الافتراضية.

    تستخدم بعد نجاح تسجيل الدخول،
    حتى تستطيع الشاشة إجبار المسؤول على
    تغيير 9999.
    """

    if entered_password is None:
        return False

    entered_password = str(
        entered_password
    )

    if not hmac.compare_digest(
        entered_password,
        DEFAULT_ADMIN_PASSWORD
    ):
        return False

    try:

        with _get_connection() as conn:

            cursor = conn.cursor()

            _ensure_settings_table(
                cursor
            )

            cursor.execute(
                """
                SELECT value
                FROM settings
                WHERE key = ?
                LIMIT 1
                """,
                (
                    ADMIN_PASSWORD_KEY,
                )
            )

            row = cursor.fetchone()

            if row is None:
                return False

            stored_hash = str(
                row[0]
            )

            # PBKDF2
            if stored_hash.startswith(
                PASSWORD_PREFIX + "$"
            ):

                valid, _ = (
                    _verify_pbkdf2_password(
                        DEFAULT_ADMIN_PASSWORD,
                        stored_hash
                    )
                )

                return valid

            # SHA-256 القديم
            if (
                len(stored_hash) == 64
                and all(
                    c in
                    "0123456789abcdefABCDEF"
                    for c in stored_hash
                )
            ):

                return _verify_legacy_sha256(
                    DEFAULT_ADMIN_PASSWORD,
                    stored_hash
                )

            return False

    except Exception as e:

        logging.error(
            f"Error checking default admin password: {e}"
        )

        return False


# =========================================================
# الحصول على مدة القفل الحالية
# =========================================================

def get_login_lockout_remaining():
    """
    يرجع عدد الثواني المتبقية للقفل المؤقت.

    إذا لم يكن هناك قفل:
        0
    """

    if not _is_login_locked():
        return 0

    remaining = (
        _locked_until
        - time.monotonic()
    )

    return max(
        0,
        int(remaining)
          )
