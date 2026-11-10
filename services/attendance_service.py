import sqlite3
import logging
import hashlib
import hmac
from datetime import datetime

# ============================================================
# DATABASE IMPORT
# ============================================================

try:
    from database.database import get_db_path
except ImportError:
    try:
        from database.data import get_db_path
    except ImportError:
        try:
            from data import get_db_path
        except ImportError as exc:
            raise ImportError(
                "Cannot import get_db_path(). "
                "Check the location and name of your database file."
            ) from exc


# ============================================================
# QR PREFIXES
# ============================================================

STUDENT_QR_PREFIX = "STUDENT:"
ADMIN_QR_PREFIX = "ADMIN:"


# ============================================================
# SUPPORTED MODES
# ============================================================

EXAM_MODE = "EXAM"
SICK_MODE = "SICK"
SCHOOL_APPROVAL_MODE = "SCHOOL_APPROVAL"

SUPPORTED_ADMIN_MODES = {
    EXAM_MODE,
    SICK_MODE,
    SCHOOL_APPROVAL_MODE,
}

SPECIAL_EXIT_MODES = {
    EXAM_MODE,
    SICK_MODE,
    SCHOOL_APPROVAL_MODE,
}

WEEKEND_DAYS = {
    "Saturday",
    "Sunday",
}

# مدة (بالثواني) نعتبر فيها المسح المتكرر لنفس الطالب مسحًا مزدوجًا
# عن طريق الخطأ، فلا يُسجَّل شيء ولا يظهر تحذير كاذب.
# ضع 0 لتعطيل هذه الحماية.
DUPLICATE_SCAN_WINDOW_SECONDS = 30

# رقم هاتف ولي الأمر ليس هوية للطالب: يعرفه الأهل وقد يتكرر بين الإخوة،
# فلا يجوز أن يسمح بتسجيل دخول أو خروج. الاحتياط الآمن هو كتابة
# Student ID يدويًا. غيّره إلى True فقط إن قررت العكس عن علم.
ALLOW_PHONE_LOOKUP = False

NORMAL_EXIT_TIME = "15:00:00"
# أي دخول بعد هذا الوقت يُسجَّل "متأخر" (Late). الطالب يدخل ولا يُعتبر غائبًا.
ON_TIME_LIMIT = "08:00:00"


# ============================================================
# COLORS
# ============================================================

COLOR_SUCCESS = (0.2, 0.8, 0.4, 1)
COLOR_WARNING = (0.9, 0.6, 0.2, 1)
COLOR_ERROR = (0.9, 0.3, 0.3, 1)
COLOR_INFO = (0.3, 0.6, 0.9, 1)


# ============================================================
# BASIC HELPERS
# ============================================================

def _normalize_input(value):
    """تحويل المدخل إلى نص وتنظيف المسافات."""

    if value is None:
        return ""

    return str(value).strip()


def _get_today_info():
    """الحصول على التاريخ والوقت واسم اليوم."""

    now = datetime.now()

    return (
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        now.strftime("%A"),
    )


def _hash_token(token):
    """إنشاء SHA-256 hash للرمز الإداري."""

    return hashlib.sha256(
        str(token).encode("utf-8")
    ).hexdigest()


def _is_school_day(day_name):
    """أيام الدراسة المعتادة في إثيوبيا: الاثنين إلى الجمعة."""

    return day_name not in WEEKEND_DAYS


def _is_weekend(day_name):
    """السبت والأحد عطلة أسبوعية."""

    return day_name in WEEKEND_DAYS


class AttendanceResult(tuple):
    """
    نتيجة المسح. تتصرف تمامًا كـ tuple من 4 عناصر:

        success, message, title, color = result

    لذلك لا يتأثر الكود القديم. وتحمل معلومات إضافية
    لربط SMS والتدقيق بالسجل المحدد:

        result.attendance_id   رقم سجل الحضور الذي كُتب (أو None)
        result.student_id      رقم الطالب (أو None)
        result.event           CHECK_IN / CHECK_OUT / EXAM_EXIT /
                               SICK_EXIT / SCHOOL_APPROVED_EXIT /
                               EARLY_EXIT_WARNING (أو None)
    """

    def __new__(
        cls,
        success,
        message,
        title,
        color,
        attendance_id=None,
        student_id=None,
        event=None,
    ):
        obj = super().__new__(
            cls,
            (success, message, title, color),
        )
        obj.attendance_id = attendance_id
        obj.student_id = student_id
        obj.event = event
        return obj


SPECIAL_EXIT_EVENTS = {
    EXAM_MODE: "EXAM_EXIT",
    SICK_MODE: "SICK_EXIT",
    SCHOOL_APPROVAL_MODE: "SCHOOL_APPROVED_EXIT",
}


def _result(
    success,
    message,
    title,
    color=None,
    attendance_id=None,
    student_id=None,
    event=None,
):
    """إنشاء نتيجة موحدة متوافقة مع واجهة التطبيق."""

    if color is None:
        color = COLOR_SUCCESS if success else COLOR_ERROR

    return AttendanceResult(
        success,
        message,
        title,
        color,
        attendance_id=attendance_id,
        student_id=student_id,
        event=event,
    )


# ============================================================
# OPTIONAL SYSTEM EVENT LOGGING
# ============================================================

def _log_system_event(
    cursor,
    event_type,
    message,
    student_id=None,
):
    """
    تسجيل الحدث إذا كان جدول system_event_logs موجودًا.

    لا نسمح لفشل السجل الاختياري بإفساد عملية الحضور.
    """

    try:
        cursor.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'system_event_logs'
            LIMIT 1
            """
        )

        if cursor.fetchone() is None:
            return

        cursor.execute(
            """
            PRAGMA table_info(system_event_logs)
            """
        )

        columns = {
            row[1]
            for row in cursor.fetchall()
        }

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # دعم الأعمدة المعروفة فقط.
        available = {
            "event_type": event_type,
            "details": message,
            "message": message,
            "student_id": student_id,
            "created_at": now,
            "event_time": now,
        }

        selected = [
            name
            for name in available
            if name in columns
        ]

        if not selected:
            return

        placeholders = ", ".join(
            "?" for _ in selected
        )

        column_sql = ", ".join(selected)

        values = [
            available[name]
            for name in selected
        ]

        cursor.execute(
            f"""
            INSERT INTO system_event_logs
            ({column_sql})
            VALUES ({placeholders})
            """,
            values,
        )

    except sqlite3.Error:
        # سجل الأحداث لا ينبغي أن يعطل الحضور.
        logging.exception(
            "Could not write optional system event log."
        )


# ============================================================
# STUDENT RESOLUTION
# ============================================================

def _find_student(cursor, user_input):
    """
    البحث عن الطالب.

    الأولوية:
    1. Student ID
    2. Phone إذا كان مرتبطًا بطالب واحد فقط.

    رقم الهاتف ليس معرفًا فريدًا للطالب.
    """

    user_input = _normalize_input(
        user_input
    )

    if not user_input:
        return None, "EMPTY"

    cursor.execute(
        """
        SELECT student_id, name, phone, active
        FROM students
        WHERE student_id = ?
        LIMIT 1
        """,
        (user_input,),
    )

    student = cursor.fetchone()

    if student:
        return student, "ID"

    if not ALLOW_PHONE_LOOKUP:
        return None, "NOT_FOUND"

    cursor.execute(
        """
        SELECT student_id, name, phone, active
        FROM students
        WHERE phone = ?
        ORDER BY student_id
        """,
        (user_input,),
    )

    students = cursor.fetchall()

    if not students:
        return None, "NOT_FOUND"

    if len(students) > 1:
        return students, "DUPLICATE_PHONE"

    return students[0], "PHONE"


# ============================================================
# INPUT PARSING
# ============================================================

def _parse_qr_input(raw_input):
    """
    صيغ الإدخال المدعومة:

    STUDENT:12345

    ADMIN:EXAM:<token>
    ADMIN:SICK:<token>
    ADMIN:SCHOOL_APPROVAL:<token>

    ويمكن إدخال Student ID مباشرة.
    """

    input_str = _normalize_input(
        raw_input
    )

    if not input_str:
        return {
            "type": "EMPTY",
        }

    upper_input = input_str.upper()

    # --------------------------------------------------------
    # STUDENT QR
    # --------------------------------------------------------

    if upper_input.startswith(
        STUDENT_QR_PREFIX
    ):

        student_id = input_str[
            len(STUDENT_QR_PREFIX):
        ].strip()

        if not student_id:
            return {
                "type": "INVALID",
            }

        return {
            "type": "STUDENT",
            "student_id": student_id,
        }

    # --------------------------------------------------------
    # ADMIN QR
    # --------------------------------------------------------

    if upper_input.startswith(
        ADMIN_QR_PREFIX
    ):

        parts = input_str.split(":", 2)

        if len(parts) != 3:
            return {
                "type": "INVALID",
            }

        mode_name = parts[1].strip().upper()
        token = parts[2].strip()

        if mode_name not in SUPPORTED_ADMIN_MODES:
            return {
                "type": "INVALID",
            }

        if not token:
            return {
                "type": "INVALID",
            }

        return {
            "type": "ADMIN",
            "mode": mode_name,
            "token": token,
        }

    # --------------------------------------------------------
    # MANUAL STUDENT ID
    # --------------------------------------------------------

    return {
        "type": "STUDENT",
        "student_id": input_str,
    }


# ============================================================
# SYSTEM MODE HELPERS
# ============================================================

def _get_mode_state(cursor, mode_name):
    """الحصول على حالة وضع إداري."""

    cursor.execute(
        """
        SELECT active, opened_at, opened_by
        FROM system_modes
        WHERE mode_name = ?
        LIMIT 1
        """,
        (mode_name,),
    )

    row = cursor.fetchone()

    if not row:
        return {
            "exists": False,
            "active": False,
            "opened_at": None,
            "opened_by": None,
        }

    return {
        "exists": True,
        "active": bool(row[0]),
        "opened_at": row[1],
        "opened_by": row[2],
    }


def _get_active_special_mode(cursor, current_date=None):
    """
    معرفة الوضع الخاص المفتوح حاليًا.

    لا يُفترض تشغيل وضعين معًا.
    """

    active_modes = []

    for mode_name in (
        EXAM_MODE,
        SICK_MODE,
        SCHOOL_APPROVAL_MODE,
    ):

        state = _get_mode_state(
            cursor,
            mode_name,
        )

        if state["active"]:

            # وضع فُتح في يوم سابق ونُسي مفتوحًا: ننهيه تلقائيًا.
            # وإلا سيمنع كل طالب من تسجيل الدخول صباح اليوم التالي،
            # لأن الوضع الخاص يقبل الخروج فقط.
            if current_date:

                opened_date = str(
                    state["opened_at"] or ""
                )[:10]

                if opened_date != current_date:

                    cursor.execute(
                        """
                        UPDATE system_modes
                        SET active = 0,
                            opened_at = NULL,
                            opened_by = NULL
                        WHERE mode_name = ?
                        """,
                        (mode_name,),
                    )

                    _log_system_event(
                        cursor,
                        "SPECIAL_MODE_EXPIRED",
                        (
                            f"Mode {mode_name} opened at "
                            f"{state['opened_at']} was closed "
                            "automatically on a new day."
                        ),
                    )

                    continue

            active_modes.append(mode_name)

    if len(active_modes) > 1:
        logging.critical(
            "Multiple special modes are active: %s",
            active_modes,
        )

        raise RuntimeError(
            "Multiple special modes are active."
        )

    if active_modes:
        return active_modes[0]

    return None


# ============================================================
# ADMIN QR VALIDATION
# ============================================================

def _validate_admin_qr(
    cursor,
    mode_name,
    token,
):
    """
    التحقق من رمز الإدارة.

    نقارن hash الرمز بالقيمة المخزنة في قاعدة البيانات.
    """

    mode_name = _normalize_input(
        mode_name
    ).upper()

    token = _normalize_input(token)

    if mode_name not in SUPPORTED_ADMIN_MODES:
        return False

    if not token:
        return False

    token_hash = _hash_token(token)

    cursor.execute(
        """
        SELECT token_hash
        FROM admin_qr_tokens
        WHERE mode_name = ?
          AND token_hash = ?
          AND active = 1
        LIMIT 1
        """,
        (
            mode_name,
            token_hash,
        ),
    )

    row = cursor.fetchone()

    if not row:
        return False

    # مقارنة ثابتة الزمن للقيم المخزنة.
    return hmac.compare_digest(
        str(row[0]),
        token_hash,
    )


# ============================================================
# TOGGLE SPECIAL MODE
# ============================================================

def _toggle_special_mode(
    cursor,
    mode_name,
    current_date,
    current_time,
):
    """
    تشغيل أو إغلاق وضع إداري.

    أول مسح: ON
    ثاني مسح للرمز نفسه: OFF

    لا يوجد مؤقت تلقائي لـ SCHOOL_APPROVAL.
    """

    if mode_name not in SUPPORTED_ADMIN_MODES:
        raise ValueError(
            "Unsupported special mode."
        )

    current_state = _get_mode_state(
        cursor,
        mode_name,
    )

    if not current_state["exists"]:
        raise RuntimeError(
            f"Mode is missing from system_modes: {mode_name}"
        )

    # --------------------------------------------------------
    # CLOSE CURRENT MODE
    # --------------------------------------------------------

    if current_state["active"]:

        cursor.execute(
            """
            UPDATE system_modes
            SET active = 0,
                opened_at = NULL,
                opened_by = NULL
            WHERE mode_name = ?
            """,
            (mode_name,),
        )

        return False

    # --------------------------------------------------------
    # OPEN MODE
    # --------------------------------------------------------

    # إغلاق جميع الأوضاع الأخرى.
    cursor.execute(
        """
        UPDATE system_modes
        SET active = 0,
            opened_at = NULL,
            opened_by = NULL
        WHERE mode_name != ?
        """,
        (mode_name,),
    )

    opened_at = (
        f"{current_date} {current_time}"
    )

    cursor.execute(
        """
        UPDATE system_modes
        SET active = 1,
            opened_at = ?,
            opened_by = 'ADMIN_QR'
        WHERE mode_name = ?
        """,
        (
            opened_at,
            mode_name,
        ),
    )

    if cursor.rowcount != 1:
        raise RuntimeError(
            f"Could not activate mode: {mode_name}"
        )

    return True


# ============================================================
# PROCESS ADMIN QR
# ============================================================

def _process_admin_qr(
    cursor,
    mode_name,
    token,
    current_date,
    current_time,
):
    """معالجة بطاقة المدير."""

    if not _validate_admin_qr(
        cursor,
        mode_name,
        token,
    ):

        _log_system_event(
            cursor,
            "INVALID_ADMIN_QR",
            "Invalid admin QR was scanned.",
        )

        return _result(
            False,
            "Invalid Admin QR!",
            "Security Error",
            COLOR_ERROR,
        )

    mode_opened = _toggle_special_mode(
        cursor,
        mode_name,
        current_date,
        current_time,
    )

    if mode_opened:

        _log_system_event(
            cursor,
            "SPECIAL_MODE_OPENED",
            f"Mode opened: {mode_name}",
        )

        if mode_name == EXAM_MODE:
            message = "EXAM MODE ON"
            title = "Exam Mode"

        elif mode_name == SICK_MODE:
            message = "SICK MODE ON"
            title = "Sick Mode"

        else:
            message = "SCHOOL APPROVAL ON"
            title = "School Approval"

        return _result(
            True,
            message,
            title,
            COLOR_SUCCESS,
        )

    _log_system_event(
        cursor,
        "SPECIAL_MODE_CLOSED",
        f"Mode closed: {mode_name}",
    )

    if mode_name == EXAM_MODE:
        message = "EXAM MODE OFF"
        title = "Exam Mode"

    elif mode_name == SICK_MODE:
        message = "SICK MODE OFF"
        title = "Sick Mode"

    else:
        message = "SCHOOL APPROVAL OFF"
        title = "School Approval"

    return _result(
        True,
        message,
        title,
        COLOR_WARNING,
    )


# ============================================================
# ATTENDANCE STATE
# ============================================================

def _get_student_day_state(
    cursor,
    student_id,
    current_date,
):
    """قراءة سجلات الطالب لهذا اليوم."""

    cursor.execute(
        """
        SELECT record_type, status
        FROM attendance
        WHERE student_id = ?
          AND date_val = ?
          AND voided_at IS NULL
        ORDER BY id ASC
        """,
        (
            student_id,
            current_date,
        ),
    )

    rows = cursor.fetchall()

    state = {
        "absent": False,
        "checked_in": False,
        "checked_out": False,
        "special": False,
        "special_type": None,
        "early_exit_warning": False,
    }

    for record_type, status in rows:

        record_type = _normalize_input(
            record_type
        ).upper()

        status = _normalize_input(
            status
        )

        status_upper = status.upper()
        status_lower = status.lower()

        # ----------------------------------------------------
        # ABSENCE
        # ----------------------------------------------------

        if (
            record_type in (
                "ABSENT",
                "ABSENT-RECORD",
            )
            or status_upper == "ABSENT"
        ):
            state["absent"] = True

        # ----------------------------------------------------
        # CHECK-IN
        # ----------------------------------------------------

        if (
            record_type in (
                "CHECK-IN",
                "PRESENT",
            )
            or "checked in" in status_lower
        ):
            state["checked_in"] = True

        # ----------------------------------------------------
        # CHECK-OUT
        # ----------------------------------------------------

        if record_type in (
            "CHECK-OUT",
            "EXIT",
        ):
            state["checked_out"] = True

        elif (
            "checked out" in status_lower
            and record_type != "EARLY-EXIT-WARNING"
        ):
            state["checked_out"] = True

        # ----------------------------------------------------
        # SPECIAL EXIT
        # ----------------------------------------------------

        if record_type in (
            "EXAM-EXIT",
            "SICK-EXIT",
            "SCHOOL-APPROVED-EXIT",
            "SPECIAL-ENTRY-EXIT",
        ):

            state["special"] = True

            if (
                record_type == "EXAM-EXIT"
                or "exam" in status_lower
            ):
                state["special_type"] = EXAM_MODE

            elif (
                record_type == "SICK-EXIT"
                or "sick" in status_lower
            ):
                state["special_type"] = SICK_MODE

            elif (
                record_type == "SCHOOL-APPROVED-EXIT"
                or "school approval" in status_lower
            ):
                state["special_type"] = SCHOOL_APPROVAL_MODE

            else:
                state["special_type"] = "SPECIAL"

        # ----------------------------------------------------
        # EARLY EXIT WARNING
        # ----------------------------------------------------

        if record_type == "EARLY-EXIT-WARNING":
            state["early_exit_warning"] = True

    return state


# ============================================================
# DUPLICATE SCAN GUARD
# ============================================================

def _seconds_since_last_scan(
    cursor,
    student_id,
    current_date,
    current_time,
):
    """
    كم ثانية مرت على آخر مسح مسجَّل لهذا الطالب اليوم.

    تُتجاهل سجلات الغياب التي أنشأها المدير (ABSENT-RECORD)،
    لأنها ليست مسحًا على البوابة، وكذلك السجلات الملغاة.

    ترجع None إذا لم يوجد مسح سابق.
    """

    cursor.execute(
        """
        SELECT time_val
        FROM attendance
        WHERE student_id = ?
          AND date_val = ?
          AND voided_at IS NULL
          AND record_type != 'ABSENT-RECORD'
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            student_id,
            current_date,
        ),
    )

    row = cursor.fetchone()

    if not row or not row[0]:
        return None

    try:
        last = datetime.strptime(str(row[0]), "%H:%M:%S")
        now = datetime.strptime(current_time, "%H:%M:%S")
    except ValueError:
        return None

    return (now - last).total_seconds()


# ============================================================
# DATABASE INSERT
# ============================================================

def _insert_attendance(
    cursor,
    student_id,
    current_date,
    current_time,
    day_name,
    record_type,
    status,
):
    """إدخال سجل حضور."""

    cursor.execute(
        """
        INSERT INTO attendance
        (
            student_id,
            date_val,
            time_val,
            record_type,
            status,
            day_name
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            current_date,
            current_time,
            record_type,
            status,
            day_name,
        ),
    )

    return cursor.lastrowid


# ============================================================
# SPECIAL MODE EXIT
# ============================================================

def _process_special_mode_exit(
    cursor,
    student_id,
    student_name,
    mode_name,
    current_date,
    current_time,
    day_name,
):
    """
    تسجيل الخروج في أحد الأوضاع:

    EXAM
    SICK
    SCHOOL_APPROVAL
    """

    state = _get_student_day_state(
        cursor,
        student_id,
        current_date,
    )

    # --------------------------------------------------------
    # ALREADY CHECKED OUT
    # --------------------------------------------------------

    if state["checked_out"]:

        return _result(
            True,
            "Status: Already Checked Out Today!",
            student_name,
            COLOR_WARNING,
        )

    # --------------------------------------------------------
    # MUST HAVE CHECKED IN
    # --------------------------------------------------------

    if not state["checked_in"]:

        _log_system_event(
            cursor,
            "SPECIAL_EXIT_WITHOUT_CHECKIN",
            f"Special exit denied for student {student_id}.",
            student_id,
        )

        return _result(
            False,
            "Student Has Not Checked In Today!",
            student_name,
            COLOR_ERROR,
        )

    # --------------------------------------------------------
    # PREVENT DUPLICATE SPECIAL EXIT
    # --------------------------------------------------------

    if state["special"]:

        return _result(
            True,
            "Special Exit Already Recorded!",
            student_name,
            COLOR_WARNING,
        )

    # --------------------------------------------------------
    # SELECT EXIT TYPE
    # --------------------------------------------------------

    if mode_name == EXAM_MODE:

        exit_record_type = "EXAM-EXIT"
        exit_status = "Checked Out (Exam)"

    elif mode_name == SICK_MODE:

        exit_record_type = "SICK-EXIT"
        exit_status = "Checked Out (Sick)"

    elif mode_name == SCHOOL_APPROVAL_MODE:

        exit_record_type = "SCHOOL-APPROVED-EXIT"
        exit_status = "Checked Out (School Approval)"

    else:
        raise ValueError(
            "Unsupported special exit mode."
        )

    # --------------------------------------------------------
    # RECORD SPECIAL EXIT
    # --------------------------------------------------------

    exit_attendance_id = _insert_attendance(
        cursor,
        student_id,
        current_date,
        current_time,
        day_name,
        exit_record_type,
        exit_status,
    )

    # --------------------------------------------------------
    # RECORD NORMAL CHECK-OUT FOR COMPATIBILITY
    # --------------------------------------------------------

    _insert_attendance(
        cursor,
        student_id,
        current_date,
        current_time,
        day_name,
        "CHECK-OUT",
        exit_status,
    )

    _log_system_event(
        cursor,
        "SPECIAL_EXIT",
        f"{mode_name} exit recorded for student {student_id}.",
        student_id,
    )

    return _result(
        True,
        exit_status,
        student_name,
        COLOR_SUCCESS,
        attendance_id=exit_attendance_id,
        student_id=student_id,
        event=SPECIAL_EXIT_EVENTS[mode_name],
    )


# ============================================================
# NORMAL ATTENDANCE
# ============================================================

def _process_normal_attendance(
    cursor,
    student_id,
    student_name,
    current_date,
    current_time,
    day_name,
):
    """
    معالجة الدخول والخروج الطبيعي.

    أيام الدراسة:
        Monday-Friday

    عطلة نهاية الأسبوع:
        Saturday-Sunday

    قبل 15:00 في يوم دراسي:
        محاولة الانصراف لا تُسجَّل كخروج عادي.
    """

    state = _get_student_day_state(
        cursor,
        student_id,
        current_date,
    )

    is_absent = state["absent"]
    has_checked_in = state["checked_in"]
    has_checked_out = state["checked_out"]

    school_day = _is_school_day(
        day_name
    )

    # ========================================================
    # ALREADY CHECKED OUT
    # ========================================================

    if has_checked_out:

        return _result(
            True,
            "Status: Already Checked Out Today!",
            student_name,
            COLOR_WARNING,
        )

    # ========================================================
    # ABSENT STUDENT
    # ========================================================

    if is_absent and not has_checked_in:

        status = (
            "Status: Error "
            "(Marked Absent Today!)"
        )

        _insert_attendance(
            cursor,
            student_id,
            current_date,
            current_time,
            day_name,
            "ABSENT-ATTEMPT",
            status,
        )

        _log_system_event(
            cursor,
            "ABSENT_STUDENT_ATTEMPT",
            f"Attendance attempt by absent student {student_id}.",
            student_id,
        )

        return _result(
            False,
            status,
            student_name,
            COLOR_ERROR,
        )

    # ========================================================
    # ALREADY CHECKED IN
    # ========================================================

    if has_checked_in:

        # ----------------------------------------------------
        # SCHOOL DAY: BEFORE NORMAL EXIT TIME
        # ----------------------------------------------------

        if (
            school_day
            and current_time < NORMAL_EXIT_TIME
        ):

            status = (
                "Unauthorized Early Exit Attempt"
            )

            warning_id = _insert_attendance(
                cursor,
                student_id,
                current_date,
                current_time,
                day_name,
                "EARLY-EXIT-WARNING",
                status,
            )

            _log_system_event(
                cursor,
                "EARLY_EXIT_WARNING",
                (
                    "Early exit attempt for student "
                    f"{student_id} at {current_time}."
                ),
                student_id,
            )

            # مهم:
            # لا ننشئ CHECK-OUT هنا.
            # ولا نعتبر الطالب خارج المدرسة.
            return _result(
                False,
                "WARNING: Early Exit Not Authorized!",
                student_name,
                COLOR_ERROR,
                attendance_id=warning_id,
                student_id=student_id,
                event="EARLY_EXIT_WARNING",
            )

        # ----------------------------------------------------
        # WEEKEND OR NORMAL EXIT TIME
        # ----------------------------------------------------

        checkout_id = _insert_attendance(
            cursor,
            student_id,
            current_date,
            current_time,
            day_name,
            "CHECK-OUT",
            "Checked Out",
        )

        _log_system_event(
            cursor,
            "NORMAL_CHECKOUT",
            f"Normal checkout for student {student_id}.",
            student_id,
        )

        return _result(
            True,
            "Checked Out",
            student_name,
            COLOR_SUCCESS,
            attendance_id=checkout_id,
            student_id=student_id,
            event="CHECK_OUT",
        )

    # ========================================================
    # FIRST CHECK-IN
    # ========================================================

    if current_time <= ON_TIME_LIMIT:

        status = "Checked In (On Time)"

    else:

        # قرار المدرسة: المتأخر يدخل ويُسجَّل Late، ولا يُحوَّل إلى غائب.
        status = "Checked In (Late)"

    checkin_id = _insert_attendance(
        cursor,
        student_id,
        current_date,
        current_time,
        day_name,
        "CHECK-IN",
        status,
    )

    _log_system_event(
        cursor,
        "CHECKIN",
        (
            f"Student {student_id} checked in "
            f"with status: {status}."
        ),
        student_id,
    )

    return _result(
        True,
        status,
        student_name,
        COLOR_SUCCESS,
        attendance_id=checkin_id,
        student_id=student_id,
        event="CHECK_IN",
    )


# ============================================================
# MAIN ATTENDANCE PROCESSOR
# ============================================================

def process_attendance(raw_input):
    """
    المعالج الرئيسي للحضور والانصراف.

    يدعم:

        ADMIN:EXAM:<token>
        ADMIN:SICK:<token>
        ADMIN:SCHOOL_APPROVAL:<token>

        STUDENT:<student_id>

        Student ID مباشرة
    """

    parsed = _parse_qr_input(
        raw_input
    )

    input_type = parsed.get(
        "type"
    )

    if input_type in (
        "EMPTY",
        "INVALID",
    ):

        return _result(
            False,
            "Please Scan a Valid QR Code",
            "Input Error",
            COLOR_ERROR,
        )

    conn = None

    try:
        db_path = get_db_path()

        conn = sqlite3.connect(
            db_path,
            timeout=15,
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        conn.execute(
            "PRAGMA busy_timeout = 15000"
        )

        # نبدأ معاملة صريحة.
        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = conn.cursor()

        (
            current_date,
            current_time,
            day_name,
        ) = _get_today_info()

        # ====================================================
        # ADMIN QR
        # ====================================================

        if input_type == "ADMIN":

            result = _process_admin_qr(
                cursor,
                parsed["mode"],
                parsed["token"],
                current_date,
                current_time,
            )

            # لا نحفظ أي تعديل عند فشل التحقق.
            # أما نتيجة فتح/إغلاق الوضع فتُحفظ.
            if result[0]:
                conn.commit()
            else:
                conn.rollback()

            return result

        # ====================================================
        # STUDENT INPUT
        # ====================================================

        if input_type != "STUDENT":

            conn.rollback()

            return _result(
                False,
                "Invalid Input",
                "Input Error",
                COLOR_ERROR,
            )

        user_input = parsed[
            "student_id"
        ]

        student, lookup_type = _find_student(
            cursor,
            user_input,
        )

        # ----------------------------------------------------
        # NOT REGISTERED
        # ----------------------------------------------------

        if lookup_type == "NOT_FOUND":

            conn.rollback()

            return _result(
                False,
                "Student Not Registered!",
                "Not Registered",
                COLOR_ERROR,
            )

        # ----------------------------------------------------
        # DUPLICATE PHONE
        # ----------------------------------------------------

        if lookup_type == "DUPLICATE_PHONE":

            conn.rollback()

            return _result(
                False,
                (
                    "Phone belongs to multiple students. "
                    "Use Student ID or QR."
                ),
                "Ambiguous Student",
                COLOR_WARNING,
            )

        if not student:

            conn.rollback()

            return _result(
                False,
                "Student Not Registered!",
                "Not Registered",
                COLOR_ERROR,
            )

        student_id = student[0]
        student_name = student[1]

        # طالب غادر المدرسة (active = 0): لا يمر من البوابة.
        if len(student) > 3 and student[3] == 0:

            conn.rollback()

            return _result(
                False,
                "Student Is Not Active!",
                student_name,
                COLOR_ERROR,
            )

        # ====================================================
        # DUPLICATE SCAN GUARD
        # ====================================================

        if DUPLICATE_SCAN_WINDOW_SECONDS > 0:

            elapsed = _seconds_since_last_scan(
                cursor,
                student_id,
                current_date,
                current_time,
            )

            if (
                elapsed is not None
                and 0 <= elapsed < DUPLICATE_SCAN_WINDOW_SECONDS
            ):

                conn.rollback()

                return _result(
                    True,
                    "Already Scanned Moments Ago",
                    student_name,
                    COLOR_WARNING,
                    student_id=student_id,
                )

        # ====================================================
        # ACTIVE SPECIAL MODE
        # ====================================================

        active_mode = _get_active_special_mode(
            cursor,
            current_date,
        )

        if active_mode in SPECIAL_EXIT_MODES:

            result = _process_special_mode_exit(
                cursor,
                student_id,
                student_name,
                active_mode,
                current_date,
                current_time,
                day_name,
            )

            # حفظ السجلات الناتجة عن العملية الناجحة.
            if result[0]:
                conn.commit()

            # نحفظ تحذيرات ABSENT-ATTEMPT أو الأحداث
            # المقصودة فقط؛ أما بقية حالات الرفض فلا تغيّر
            # حالة الحضور.
            elif result[1] == "Status: Error (Marked Absent Today!)":
                conn.commit()
            else:
                conn.rollback()

            return result

        # ====================================================
        # NORMAL ATTENDANCE
        # ====================================================

        result = _process_normal_attendance(
            cursor,
            student_id,
            student_name,
            current_date,
            current_time,
            day_name,
        )

        # تحذير الانصراف المبكر يجب أن يُحفظ كسجل تحذير،
        # لكنه لا ينشئ سجل CHECK-OUT.
        if (
            result[1]
            == "WARNING: Early Exit Not Authorized!"
        ):
            conn.commit()

        elif result[0]:
            conn.commit()

        elif (
            result[1]
            == "Status: Error (Marked Absent Today!)"
        ):
            conn.commit()

        else:
            conn.rollback()

        return result

    except sqlite3.Error:
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

        logging.exception(
            "Attendance database error."
        )

        return _result(
            False,
            "Database Error",
            "System Error",
            COLOR_ERROR,
        )

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

        logging.exception(
            "Unexpected error in process_attendance."
        )

        return _result(
            False,
            "System Error",
            "System Error",
            COLOR_ERROR,
        )

    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                logging.exception(
                    "Could not close attendance database."
                )


# ============================================================
# AUTOMATIC INPUT TRIGGER
# ============================================================

def check_auto_trigger(
    app,
    instance,
    text,
):
    """
    استقبال QR المكتمل من TextInput.

    الإدخال اليدوي لا يُعالج عند كل حرف.
    """

    text = _normalize_input(
        text
    )

    if not text:
        return

    parsed = _parse_qr_input(
        text
    )

    if parsed["type"] == "INVALID":
        return

    # لا نعالج ID اليدوي عند كل حرف.
    if parsed["type"] == "STUDENT":

        if not text.upper().startswith(
            STUDENT_QR_PREFIX
        ):
            return

    elif parsed["type"] == "ADMIN":

        if not parsed.get("token"):
            return

    else:
        return

    try:
        app.process_attendance(
            text
        )

    except Exception:
        logging.exception(
            "Automatic attendance trigger failed."
        )

    finally:
        if hasattr(instance, "text"):
            instance.text = ""


# ============================================================
# AUTOMATIC ABSENCE
# ============================================================

def mark_absent_for_missing_students():
    """
    تسجيل الغياب للطلاب الذين ليس لديهم سجل حضور اليوم.

    لا يسجل الغياب تلقائيًا يوم السبت أو الأحد.

    يجب استدعاء هذه الوظيفة في الوقت الذي تعتمده المدرسة،
    وليس عند تشغيل التطبيق عشوائيًا.

    ترجع:
        عدد الطلاب الذين سُجّل غيابهم (0 إن لم يكن هناك أحد
        أو كان اليوم عطلة)، أو None إذا حدث خطأ ولم يُحفظ شيء.
    """

    conn = None

    try:
        (
            current_date,
            current_time,
            day_name,
        ) = _get_today_info()

        # ----------------------------------------------------
        # WEEKEND: NO AUTOMATIC ABSENCE
        # ----------------------------------------------------

        if _is_weekend(day_name):
            logging.info(
                "Automatic absence skipped on weekend: %s",
                day_name,
            )
            return 0

        conn = sqlite3.connect(
            get_db_path(),
            timeout=15,
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        conn.execute(
            "PRAGMA busy_timeout = 15000"
        )

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = conn.cursor()

        # ----------------------------------------------------
        # STUDENTS WITH ANY RECORD TODAY
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT DISTINCT student_id
            FROM attendance
            WHERE date_val = ?
              AND voided_at IS NULL
            """,
            (current_date,),
        )

        already_processed = {
            row[0]
            for row in cursor.fetchall()
        }

        # ----------------------------------------------------
        # ALL REGISTERED STUDENTS
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT student_id
            FROM students
            WHERE active = 1
            ORDER BY student_id
            """
        )

        all_students = cursor.fetchall()

        marked_count = 0

        # ----------------------------------------------------
        # MARK MISSING STUDENTS
        # ----------------------------------------------------

        for (student_id,) in all_students:

            if student_id in already_processed:
                continue

            _insert_attendance(
                cursor,
                student_id,
                current_date,
                current_time,
                day_name,
                "ABSENT-RECORD",
                "ABSENT",
            )

            _log_system_event(
                cursor,
                "ABSENCE_RECORDED",
                (
                    "Automatic absence recorded for "
                    f"student {student_id}."
                ),
                student_id,
            )

            marked_count += 1

        conn.commit()

        return marked_count

    except sqlite3.Error:
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

        logging.exception(
            "Mark absent database error."
        )

        return None

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass

        logging.exception(
            "Unexpected mark absent error."
        )

        return None

    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                logging.exception(
                    "Could not close absence database."
    )
