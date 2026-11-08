"""
AMIR SYSTEM
SMS Service

وظيفة هذا الملف:
- إرسال SMS من شريحة SIM الموجودة في جهاز Android (بدون Wi-Fi أو Internet).
- تسجيل كل محاولة إرسال في جدول sms_logs مربوطة بسجل الحضور (attendance_id).
- منع تكرار نفس الرسالة (لنفس سجل الحضور، ولرسالة الغياب مرة واحدة يوميًا).
- معرفة الطلاب الذين لم يصلهم SMS، واقتراح الحل، وإعادة المحاولة.
- لا يحتوي على منطق الحضور نفسه، ولا يسجل الغياب.

الهوية الأساسية للطالب هي student_id. رقم الهاتف ليس هوية ويمكن أن يتكرر
بين الإخوة. لا يُسجَّل رقم الهاتف كاملًا في logs.

مهم جدًا:
- ACCEPTED تعني أن Android قبل طلب الإرسال فقط. لا تعني أن ولي الأمر
  استلم الرسالة. التأكد من الاستلام يحتاج إشعار تسليم (Delivery Report)
  وهو غير مضمون عند كل شركات الاتصال، وغير منفذ هنا.
- نظام Android نفسه قد يعرض تنبيهًا أو يمنع الإرسال عند إرسال عدد كبير
  من الرسائل في وقت قصير (حد تقريبي 30 رسالة / 30 دقيقة لكل تطبيق).
  ما رفضه النظام يظهر في قائمة get_students_without_sms() ويمكن إعادة
  محاولته بـ retry_missing_sms(). يجب اختبار هذا على جهاز المدرسة.
"""

import logging
from datetime import datetime

from database.database import get_connection, log_sms_result


# ============================================================
# CONFIGURATION
# ============================================================

MAX_SMS_MESSAGE_LENGTH = 2000

SMS_PERMISSION_REQUEST_CODE = 5001

# نتائج المحاولة (تُحفظ في sms_logs.result)
RESULT_ACCEPTED = "ACCEPTED"
RESULT_FAILED = "FAILED"
RESULT_NO_PHONE = "NO_PHONE"
RESULT_INVALID_PHONE = "INVALID_PHONE"
RESULT_NO_PERMISSION = "NO_PERMISSION"
RESULT_NOT_ATTEMPTED = "NOT_ATTEMPTED"
RESULT_ALREADY_SENT = "ALREADY_SENT"

# أنواع الرسائل (تُحفظ في sms_logs.message_type)
TYPE_CHECK_IN = "CHECK_IN"
TYPE_CHECK_OUT = "CHECK_OUT"
TYPE_EXAM_EXIT = "EXAM_EXIT"
TYPE_SICK_EXIT = "SICK_EXIT"
TYPE_SCHOOL_APPROVED_EXIT = "SCHOOL_APPROVED_EXIT"
TYPE_ABSENT = "ABSENT"
TYPE_CUSTOM = "CUSTOM"

# ربط حدث attendance_service بنوع الرسالة.
# EARLY_EXIT_WARNING غير موجود هنا عمدًا: لا نرسل SMS للأهل عن محاولة
# خروج مبكر غير مصرّح بها إلا إذا قررت المدرسة ذلك.
EVENT_TO_MESSAGE_TYPE = {
    "CHECK_IN": TYPE_CHECK_IN,
    "CHECK_OUT": TYPE_CHECK_OUT,
    "EXAM_EXIT": TYPE_EXAM_EXIT,
    "SICK_EXIT": TYPE_SICK_EXIT,
    "SCHOOL_APPROVED_EXIT": TYPE_SCHOOL_APPROVED_EXIT,
}

# ربط record_type في جدول attendance بنوع الرسالة (لقائمة من لم يصله SMS).
RECORD_TYPE_TO_MESSAGE_TYPE = {
    "CHECK-IN": TYPE_CHECK_IN,
    "CHECK-OUT": TYPE_CHECK_OUT,
    "EXAM-EXIT": TYPE_EXAM_EXIT,
    "SICK-EXIT": TYPE_SICK_EXIT,
    "SCHOOL-APPROVED-EXIT": TYPE_SCHOOL_APPROVED_EXIT,
    "ABSENT-RECORD": TYPE_ABSENT,
}

MESSAGE_TYPE_LABELS = {
    TYPE_CHECK_IN: "Check-in",
    TYPE_CHECK_OUT: "Check-out",
    TYPE_EXAM_EXIT: "Exam exit",
    TYPE_SICK_EXIT: "Sick exit",
    TYPE_SCHOOL_APPROVED_EXIT: "School-approved exit",
    TYPE_ABSENT: "Absence",
}

# اقتراح الحل لكل سبب (يظهر للمدير).
SUGGESTIONS = {
    RESULT_NOT_ATTEMPTED: (
        "SMS was never attempted. Press Retry."
    ),
    RESULT_NO_PHONE: (
        "No guardian phone number. Add it in Manage Students, then Retry."
    ),
    RESULT_INVALID_PHONE: (
        "Guardian phone number looks invalid. "
        "Correct it in Manage Students, then Retry."
    ),
    RESULT_NO_PERMISSION: (
        "SMS permission is not granted. Allow SMS for AMIR in the phone "
        "settings, then Retry."
    ),
    RESULT_FAILED: (
        "The phone could not send it. Check SIM, credit and signal, "
        "then Retry."
    ),
}


def describe_sms_problem(reason):
    """نص اقتراح الحل لسبب معين."""

    return SUGGESTIONS.get(
        reason,
        SUGGESTIONS[RESULT_FAILED]
    )


def _today():
    return datetime.now().strftime("%Y-%m-%d")


# ============================================================
# DATABASE - STUDENT CONTACT
# ============================================================

def _get_student_contact(student_id):
    """
    الحصول على بيانات الطالب من قاعدة البيانات.

    student_id هو الهوية الأساسية للطالب.

    يرجع:
        {"student_id": ..., "name": ..., "phone": ...}
        أو None.

    phone ليس معرفًا فريدًا: يمكن أن يستخدم نفس الرقم لأكثر من طالب.
    """

    if student_id is None:
        return None

    student_id = str(student_id).strip()

    if not student_id:
        logging.warning(
            "SMS Service: student_id is empty."
        )
        return None

    try:

        with get_connection() as connection:

            row = connection.execute(
                """
                SELECT student_id, name, phone
                FROM students
                WHERE student_id = ?
                LIMIT 1
                """,
                (student_id,)
            ).fetchone()

        if row is None:

            logging.warning(
                "SMS Service: Student not found: "
                f"{student_id}"
            )

            return None

        name = row["name"]
        phone = row["phone"]

        if name is not None:
            name = str(name).strip()

        if phone is not None:
            phone = str(phone).strip()

        return {
            "student_id": str(row["student_id"]).strip(),
            "name": name if name else None,
            "phone": phone if phone else None,
        }

    except Exception as e:

        logging.error(
            f"SMS Service student lookup error: {e}"
        )

        return None


# ============================================================
# PHONE / MESSAGE VALIDATION
# ============================================================

def _normalize_phone(phone):
    """
    تنظيف رقم الهاتف قبل الإرسال.

    يدعم:
        +251xxxxxxxxx
        09xxxxxxxx
    """

    if phone is None:
        return None

    phone = str(phone).strip()

    if not phone:
        return None

    if phone.startswith("+"):

        digits = "".join(
            character
            for character in phone[1:]
            if character.isdigit()
        )

        if not digits:
            return None

        return "+" + digits

    return "".join(
        character
        for character in phone
        if character.isdigit()
    )


def _validate_phone(phone):
    """
    تحقق عام: من 7 إلى 15 رقمًا، مع + اختيارية في البداية.
    لا نربط الخدمة بدولة واحدة.
    """

    if not phone:
        return False

    digits = phone[1:] if phone.startswith("+") else phone

    if not digits.isdigit():
        return False

    return 7 <= len(digits) <= 15


def _validate_message(message):

    if message is None:
        return None

    message = str(message).strip()

    if not message:
        return None

    if len(message) > MAX_SMS_MESSAGE_LENGTH:

        logging.warning(
            "SMS Service: Message is too long."
        )

        return None

    return message


def _mask_for_log(phone):
    """آخر رقمين فقط في logs."""

    if not phone:
        return "none"

    return "***" + str(phone)[-2:]


# ============================================================
# ANDROID (pyjnius)
# ============================================================

def _get_sms_manager():

    try:

        from jnius import autoclass

        SmsManager = autoclass(
            "android.telephony.SmsManager"
        )

        sms_manager = SmsManager.getDefault()

        if sms_manager is None:

            logging.error(
                "SMS Service: SmsManager.getDefault() "
                "returned None."
            )

            return None

        return sms_manager

    except ImportError:

        logging.error(
            "SMS Service: pyjnius is not available."
        )

        return None

    except Exception as e:

        logging.error(
            f"SMS Service: Cannot access SmsManager: {e}"
        )

        return None


def _get_android_activity():

    try:

        from jnius import autoclass

        PythonActivity = autoclass(
            "org.kivy.android.PythonActivity"
        )

        return PythonActivity.mActivity

    except Exception as e:

        logging.error(
            f"SMS Service: Android activity error: {e}"
        )

        return None


def _has_sms_permission():
    """التحقق من SEND_SMS permission."""

    try:

        activity = _get_android_activity()

        if activity is None:
            return False

        from jnius import autoclass

        PackageManager = autoclass(
            "android.content.pm.PackageManager"
        )

        result = activity.checkSelfPermission(
            "android.permission.SEND_SMS"
        )

        return result == PackageManager.PERMISSION_GRANTED

    except Exception as e:

        logging.warning(
            f"SMS Service: Could not check SMS permission: {e}"
        )

        return False


def request_sms_permission():
    """
    طلب SEND_SMS permission من Android. لا ترسل SMS.

    تنبيه: True تعني أن الطلب أُرسل، لا أن المستخدم وافق.
    تحقق بعد ذلك بـ sms_service_status().
    """

    try:

        activity = _get_android_activity()

        if activity is None:
            return False

        if _has_sms_permission():
            return True

        activity.requestPermissions(
            ["android.permission.SEND_SMS"],
            SMS_PERMISSION_REQUEST_CODE
        )

        logging.info(
            "SMS Service: SMS permission request sent."
        )

        return True

    except Exception as e:

        logging.error(
            f"SMS Service: SMS permission request failed: {e}"
        )

        return False


# ============================================================
# LOW-LEVEL SEND
# ============================================================

def _send_sms_detailed(phone, message):
    """
    إرسال SMS مع سبب واضح للنتيجة.

    يرجع (accepted: bool, result_code: str).

    ACCEPTED لا تعني أن الرسالة وصلت. انظر أعلى الملف.
    """

    phone = _normalize_phone(phone)

    if not _validate_phone(phone):
        return False, RESULT_INVALID_PHONE

    message = _validate_message(message)

    if message is None:
        return False, RESULT_FAILED

    if not _has_sms_permission():

        logging.warning(
            "SMS Service: SEND_SMS permission is not granted."
        )

        return False, RESULT_NO_PERMISSION

    sms_manager = _get_sms_manager()

    if sms_manager is None:
        return False, RESULT_FAILED

    try:

        parts = sms_manager.divideMessage(message)

        if parts is None or len(parts) == 0:

            logging.error(
                "SMS Service: Failed to divide SMS message."
            )

            return False, RESULT_FAILED

        if len(parts) == 1:

            sms_manager.sendTextMessage(
                phone,
                None,
                parts[0],
                None,
                None
            )

        else:

            sms_manager.sendMultipartTextMessage(
                phone,
                None,
                parts,
                None,
                None
            )

        logging.info(
            "SMS Service: SMS request accepted by Android "
            f"for destination {_mask_for_log(phone)}"
        )

        return True, RESULT_ACCEPTED

    except Exception as e:

        logging.error(
            f"SMS Service sending error: {e}"
        )

        return False, RESULT_FAILED


def send_sms(phone, message):
    """
    إرسال SMS إلى رقم محدد. يرجع True إذا قبل Android الطلب.

    تنبيه: هذه الدالة لا تسجل شيئًا في sms_logs. للرسائل المرتبطة
    بالطلاب استخدم دوال send_*_sms أو send_sms_to_student.
    """

    accepted, _ = _send_sms_detailed(phone, message)

    return accepted


# ============================================================
# LOGGING (فشل السجل لا يمنع الإرسال)
# ============================================================

def _log_attempt(
    message_type,
    result,
    student_id=None,
    phone=None,
    details=None,
    attendance_id=None,
):

    try:

        log_sms_result(
            message_type,
            result,
            student_id=student_id,
            phone=phone,
            details=details,
            attendance_id=attendance_id,
        )

    except Exception:

        logging.exception(
            "SMS Service: could not write sms_logs."
        )


def _accepted_exists(message_type, student_id, attendance_id):
    """
    هل أُرسلت (قُبلت) هذه الرسالة من قبل؟

    - الغياب: مرة واحدة لكل طالب في اليوم.
    - بقية الأنواع: مرة واحدة لكل سجل حضور (attendance_id).
    """

    try:

        with get_connection() as connection:

            if message_type == TYPE_ABSENT:

                row = connection.execute(
                    """
                    SELECT 1
                    FROM sms_logs
                    WHERE student_id = ?
                      AND message_type = ?
                      AND result = ?
                      AND substr(created_at, 1, 10) = ?
                    LIMIT 1
                    """,
                    (
                        student_id,
                        TYPE_ABSENT,
                        RESULT_ACCEPTED,
                        _today(),
                    )
                ).fetchone()

            elif attendance_id is not None:

                row = connection.execute(
                    """
                    SELECT 1
                    FROM sms_logs
                    WHERE attendance_id = ?
                      AND message_type = ?
                      AND result = ?
                    LIMIT 1
                    """,
                    (
                        attendance_id,
                        message_type,
                        RESULT_ACCEPTED,
                    )
                ).fetchone()

            else:
                return False

        return row is not None

    except Exception:

        logging.exception(
            "SMS Service: duplicate check failed."
        )

        # عند الشك: لا نمنع الإرسال.
        return False


# ============================================================
# MESSAGE BUILDERS
# ============================================================
#
# الوقت (time_text) يُضاف للرسالة لأن الرسالة قد تتأخر أو تُعاد
# محاولتها، فيحتاج ولي الأمر أن يعرف متى حدث الأمر فعلًا.
# ============================================================

def _at(time_text):
    return f" at {time_text}" if time_text else ""


def _build_check_in_message(
    student_name,
    is_late=False,
    time_text=None
):

    if is_late:

        return (
            f"AMIR SYSTEM: {student_name} "
            f"has checked in late today{_at(time_text)}."
        )

    return (
        f"AMIR SYSTEM: {student_name} "
        f"has checked in successfully{_at(time_text)}."
    )


def _build_check_out_message(student_name, time_text=None):

    return (
        f"AMIR SYSTEM: {student_name} "
        f"has checked out successfully{_at(time_text)}."
    )


def _build_exam_exit_message(student_name, time_text=None):

    return (
        f"AMIR SYSTEM: {student_name} "
        f"has left school for an exam{_at(time_text)}."
    )


def _build_sick_exit_message(student_name, time_text=None):

    return (
        f"AMIR SYSTEM: {student_name} "
        f"has left school because of illness{_at(time_text)}."
    )


def _build_school_approved_exit_message(
    student_name,
    time_text=None
):

    return (
        f"AMIR SYSTEM: {student_name} "
        f"has left school with school approval{_at(time_text)}."
    )


def _build_absent_message(student_name):

    return (
        f"AMIR SYSTEM: {student_name} "
        "did not check in at school today "
        "and has been marked absent."
    )


def _build_message(
    message_type,
    student_name,
    status=None,
    time_text=None
):

    if message_type == TYPE_CHECK_IN:

        is_late = (
            status is not None
            and "late" in str(status).strip().lower()
        )

        return _build_check_in_message(
            student_name,
            is_late=is_late,
            time_text=time_text
        )

    if message_type == TYPE_CHECK_OUT:
        return _build_check_out_message(student_name, time_text)

    if message_type == TYPE_EXAM_EXIT:
        return _build_exam_exit_message(student_name, time_text)

    if message_type == TYPE_SICK_EXIT:
        return _build_sick_exit_message(student_name, time_text)

    if message_type == TYPE_SCHOOL_APPROVED_EXIT:
        return _build_school_approved_exit_message(
            student_name,
            time_text
        )

    if message_type == TYPE_ABSENT:
        return _build_absent_message(student_name)

    return None


# ============================================================
# CORE: SEND ONE EVENT SMS (+ log + duplicate guard)
# ============================================================

def _send_event_sms(
    student_id,
    message_type,
    attendance_id=None,
    status=None,
    time_text=None,
):
    """
    إرسال رسالة حدث واحدة لولي أمر طالب، مع التسجيل ومنع التكرار.

    يرجع dict:
        {"sent": bool, "result": <RESULT_*>}

    result = ALREADY_SENT: أُرسلت سابقًا، ولم يُرسل شيء الآن.
    """

    student_id = str(student_id).strip() if student_id is not None else ""

    if not student_id:

        logging.warning(
            "SMS Service: student_id is empty."
        )

        return {"sent": False, "result": RESULT_FAILED}

    if _accepted_exists(message_type, student_id, attendance_id):

        return {"sent": False, "result": RESULT_ALREADY_SENT}

    contact = _get_student_contact(student_id)

    if not contact or not contact.get("name"):

        _log_attempt(
            message_type,
            RESULT_FAILED,
            student_id=student_id,
            details="Student or student name not found.",
            attendance_id=attendance_id,
        )

        return {"sent": False, "result": RESULT_FAILED}

    phone = _normalize_phone(contact.get("phone"))

    if not phone:

        _log_attempt(
            message_type,
            RESULT_NO_PHONE,
            student_id=student_id,
            details="No guardian phone number.",
            attendance_id=attendance_id,
        )

        return {"sent": False, "result": RESULT_NO_PHONE}

    message = _build_message(
        message_type,
        contact["name"],
        status=status,
        time_text=time_text,
    )

    if message is None:

        _log_attempt(
            message_type,
            RESULT_FAILED,
            student_id=student_id,
            phone=phone,
            details="Unknown message type.",
            attendance_id=attendance_id,
        )

        return {"sent": False, "result": RESULT_FAILED}

    accepted, code = _send_sms_detailed(phone, message)

    _log_attempt(
        message_type,
        code,
        student_id=student_id,
        phone=phone,
        attendance_id=attendance_id,
    )

    return {"sent": accepted, "result": code}


# ============================================================
# INTEGRATION WITH attendance_service
# ============================================================

def send_sms_for_attendance_result(result):
    """
    نقطة الربط مع المسح: تُستدعى بعد process_attendance مباشرة
    (بعد أن اكتمل حفظ سجل الحضور).

        result = process_attendance(text)
        send_sms_for_attendance_result(result)

    ترسل SMS فقط للأحداث المعتمدة (دخول، خروج، خروج امتحان/مرض/موافقة
    المدرسة)، وفقط إذا كُتب سجل فعلي (attendance_id).

    ترجع dict كما في _send_event_sms، أو None إذا لا يوجد SMS لهذا الحدث.
    لا ترفع استثناءً أبدًا: فشل SMS لا يجوز أن يعطل البوابة.
    """

    try:

        event = getattr(result, "event", None)
        attendance_id = getattr(result, "attendance_id", None)
        student_id = getattr(result, "student_id", None)

        message_type = EVENT_TO_MESSAGE_TYPE.get(event)

        if (
            message_type is None
            or attendance_id is None
            or student_id is None
        ):
            return None

        status = result[1] if len(result) > 1 else None

        return _send_event_sms(
            student_id,
            message_type,
            attendance_id=attendance_id,
            status=status,
            time_text=datetime.now().strftime("%H:%M"),
        )

    except Exception:

        logging.exception(
            "SMS Service: SMS for attendance result failed."
        )

        return None


# ============================================================
# SEND SMS TO STUDENT (عام)
# ============================================================

def send_sms_to_student(student_id, message):
    """
    إرسال نص حر إلى ولي أمر طالب (النوع CUSTOM). يُسجَّل في sms_logs.
    """

    contact = _get_student_contact(student_id)

    if not contact:
        return False

    phone = _normalize_phone(contact.get("phone"))

    if not phone:

        _log_attempt(
            TYPE_CUSTOM,
            RESULT_NO_PHONE,
            student_id=contact["student_id"],
            details="No guardian phone number.",
        )

        return False

    accepted, code = _send_sms_detailed(phone, message)

    _log_attempt(
        TYPE_CUSTOM,
        code,
        student_id=contact["student_id"],
        phone=phone,
    )

    return accepted


# ============================================================
# SPECIFIC SMS FUNCTIONS (توافق مع الكود القديم)
# ============================================================

def send_check_in_sms(
    student_id,
    status=None,
    attendance_id=None,
    time_text=None
):

    return _send_event_sms(
        student_id,
        TYPE_CHECK_IN,
        attendance_id=attendance_id,
        status=status,
        time_text=time_text,
    )["sent"]


def send_check_out_sms(
    student_id,
    attendance_id=None,
    time_text=None
):

    return _send_event_sms(
        student_id,
        TYPE_CHECK_OUT,
        attendance_id=attendance_id,
        time_text=time_text,
    )["sent"]


def send_exam_exit_sms(
    student_id,
    attendance_id=None,
    time_text=None
):

    return _send_event_sms(
        student_id,
        TYPE_EXAM_EXIT,
        attendance_id=attendance_id,
        time_text=time_text,
    )["sent"]


def send_sick_exit_sms(
    student_id,
    attendance_id=None,
    time_text=None
):

    return _send_event_sms(
        student_id,
        TYPE_SICK_EXIT,
        attendance_id=attendance_id,
        time_text=time_text,
    )["sent"]


def send_school_approved_exit_sms(
    student_id,
    attendance_id=None,
    time_text=None
):

    return _send_event_sms(
        student_id,
        TYPE_SCHOOL_APPROVED_EXIT,
        attendance_id=attendance_id,
        time_text=time_text,
    )["sent"]


def send_absent_sms(student_id, attendance_id=None):
    """
    إرسال SMS لطالب تم تسجيله ABSENT. لا تسجل الغياب.
    رسالة واحدة فقط لكل طالب في اليوم.
    """

    return _send_event_sms(
        student_id,
        TYPE_ABSENT,
        attendance_id=attendance_id,
    )["sent"]


# ============================================================
# TODAY'S ABSENT STUDENTS
# ============================================================

def get_absent_students_today():
    """
    الطلاب الذين سجّلهم المدير ABSENT اليوم (غير الملغاة، والنشطين).

    لا تسجل الغياب. ترجع قائمة dict:
        student_id, name, phone, attendance_id
    """

    students = []

    try:

        with get_connection() as connection:

            rows = connection.execute(
                """
                SELECT
                    a.student_id,
                    s.name,
                    s.phone,
                    MAX(a.id) AS attendance_id
                FROM attendance AS a
                INNER JOIN students AS s
                    ON s.student_id = a.student_id
                WHERE a.date_val = ?
                  AND a.voided_at IS NULL
                  AND s.active = 1
                  AND a.record_type = 'ABSENT-RECORD'
                  AND a.status = 'ABSENT'
                GROUP BY a.student_id, s.name, s.phone
                ORDER BY
                    CASE WHEN s.grade GLOB '[0-9]*'
                         THEN CAST(s.grade AS INTEGER)
                         ELSE 9999 END,
                    UPPER(COALESCE(s.section, '~')),
                    s.name COLLATE NOCASE,
                    a.student_id
                """,
                (_today(),)
            ).fetchall()

        for row in rows:

            name = row["name"]
            phone = row["phone"]

            students.append(
                {
                    "student_id": str(row["student_id"]).strip(),
                    "name": str(name).strip() if name else None,
                    "phone": str(phone).strip() if phone else None,
                    "attendance_id": row["attendance_id"],
                }
            )

        return students

    except Exception as e:

        logging.error(
            f"SMS Service absent student lookup error: {e}"
        )

        return []


def send_absent_sms_for_today():
    """
    إرسال SMS لجميع الطلاب المسجلين ABSENT اليوم.

    لا تسجل الغياب. تتخطى من أُرسل له اليوم من قبل (لا تكرار).

    ترجع:
        {
            "total":        عدد الغائبين المسجلين اليوم,
            "sent":         عدد الرسائل التي قبلها Android الآن,
            "failed":       عدد الفاشلة (اطلب get_students_without_sms),
            "no_phone":     عدد الطلاب بدون رقم صالح,
            "already_sent": عدد من أُرسل له سابقًا اليوم (تم تخطيه),
            "students":     [...]
        }
    """

    result = {
        "total": 0,
        "sent": 0,
        "failed": 0,
        "no_phone": 0,
        "already_sent": 0,
        "students": [],
    }

    absent_students = get_absent_students_today()

    result["total"] = len(absent_students)

    for student in absent_students:

        outcome = _send_event_sms(
            student["student_id"],
            TYPE_ABSENT,
            attendance_id=student.get("attendance_id"),
        )

        code = outcome["result"]

        if code == RESULT_ACCEPTED:
            result["sent"] += 1

        elif code == RESULT_ALREADY_SENT:
            result["already_sent"] += 1

        elif code in (RESULT_NO_PHONE, RESULT_INVALID_PHONE):
            result["no_phone"] += 1

        else:
            result["failed"] += 1

        result["students"].append(
            {
                "student_id": student["student_id"],
                "name": student.get("name"),
                "sent": outcome["sent"],
                "reason": code,
            }
        )

    logging.info(
        "SMS Service: Absent SMS completed. "
        f"Total={result['total']}, Sent={result['sent']}, "
        f"Failed={result['failed']}, NoPhone={result['no_phone']}, "
        f"AlreadySent={result['already_sent']}"
    )

    return result


def send_absent_sms_to_all():
    """اسم بديل للتوافق."""

    return send_absent_sms_for_today()


# ============================================================
# STUDENTS WITHOUT SMS (من لم يصله SMS)
# ============================================================

def _latest_problem(connection, row):
    """
    آخر سبب لعدم قبول SMS لهذا السجل.
    NOT_ATTEMPTED إذا لم تُجرَ أي محاولة.
    """

    log = connection.execute(
        """
        SELECT result
        FROM sms_logs
        WHERE attendance_id = ?
          AND message_type = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (row["id"], row["message_type"])
    ).fetchone()

    if log is None and row["message_type"] == TYPE_ABSENT:

        log = connection.execute(
            """
            SELECT result
            FROM sms_logs
            WHERE student_id = ?
              AND message_type = ?
              AND substr(created_at, 1, 10) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (row["student_id"], TYPE_ABSENT, row["date_val"])
        ).fetchone()

    if log is None:
        return RESULT_NOT_ATTEMPTED

    return log["result"]


def get_students_without_sms(date_val=None):
    """
    أحداث الحضور (الدخول، الخروج، الخروج الخاص، الغياب) التي لم يقبل
    الهاتف إرسال SMS لها في هذا اليوم (اليوم افتراضيًا).

    ترجع قائمة dict مرتبة بالصف ثم الشعبة ثم الاسم:
        attendance_id, student_id, name, grade, section,
        message_type, event_label, time_val, status,
        reason, suggestion

    ملاحظة: خروج EXAM/SICK/موافقة المدرسة يُكتب في attendance سجلين
    (سجل الخروج الخاص + CHECK-OUT للتوافق). نعتمد سجل الخروج الخاص
    فقط، فلا يظهر نفس الطالب مرتين.
    """

    date_val = date_val or _today()

    problems = []

    try:

        with get_connection() as connection:

            rows = connection.execute(
                """
                SELECT
                    a.id,
                    a.student_id,
                    s.name,
                    s.grade,
                    s.section,
                    a.date_val,
                    a.time_val,
                    a.record_type,
                    a.status
                FROM attendance AS a
                INNER JOIN students AS s
                    ON s.student_id = a.student_id
                WHERE a.date_val = ?
                  AND a.voided_at IS NULL
                  AND s.active = 1
                  AND (
                        a.record_type = 'CHECK-IN'
                     OR (a.record_type = 'CHECK-OUT'
                         AND a.status = 'Checked Out')
                     OR a.record_type IN (
                            'EXAM-EXIT',
                            'SICK-EXIT',
                            'SCHOOL-APPROVED-EXIT',
                            'ABSENT-RECORD'
                        )
                  )
                  AND NOT EXISTS (
                        SELECT 1
                        FROM sms_logs AS l
                        WHERE l.result = 'ACCEPTED'
                          AND (
                                l.attendance_id = a.id
                             OR (
                                    a.record_type = 'ABSENT-RECORD'
                                AND l.message_type = 'ABSENT'
                                AND l.student_id = a.student_id
                                AND substr(l.created_at, 1, 10)
                                    = a.date_val
                                )
                          )
                  )
                ORDER BY
                    CASE WHEN s.grade GLOB '[0-9]*'
                         THEN CAST(s.grade AS INTEGER)
                         ELSE 9999 END,
                    UPPER(COALESCE(s.section, '~')),
                    s.name COLLATE NOCASE,
                    a.id
                """,
                (date_val,)
            ).fetchall()

            for row in rows:

                message_type = RECORD_TYPE_TO_MESSAGE_TYPE.get(
                    row["record_type"]
                )

                if message_type is None:
                    continue

                item = {
                    "id": row["id"],
                    "student_id": row["student_id"],
                    "date_val": row["date_val"],
                    "message_type": message_type,
                }

                reason = _latest_problem(connection, item)

                problems.append(
                    {
                        "attendance_id": row["id"],
                        "student_id": str(row["student_id"]).strip(),
                        "name": row["name"],
                        "grade": row["grade"],
                        "section": row["section"],
                        "message_type": message_type,
                        "event_label": MESSAGE_TYPE_LABELS.get(
                            message_type,
                            message_type
                        ),
                        "time_val": row["time_val"],
                        "status": row["status"],
                        "reason": reason,
                        "suggestion": describe_sms_problem(reason),
                    }
                )

        return problems

    except Exception as e:

        logging.error(
            f"SMS Service: could not list students without SMS: {e}"
        )

        return []


def retry_missing_sms():
    """
    إعادة محاولة SMS لأحداث اليوم التي لم يقبلها الهاتف.

    - تتخطى من ليس له رقم هاتف صالح الآن (يحتاج تصحيح الرقم أولًا)،
      ولا تكتب له سجلًا جديدًا في كل مرة.
    - اليوم فقط، لأن نص رسالة الغياب يقول "today".
    - تحترم منع التكرار: لا ترسل ما قُبل سابقًا.

    ترجع:
        {
            "total":           عدد الأحداث بدون SMS,
            "sent":            عدد ما قبله الهاتف الآن,
            "failed":          عدد ما فشل مرة أخرى,
            "needs_phone_fix": عدد من يحتاج تصحيح/إضافة رقم,
        }
    """

    summary = {
        "total": 0,
        "sent": 0,
        "failed": 0,
        "needs_phone_fix": 0,
    }

    missing = get_students_without_sms()

    summary["total"] = len(missing)

    for item in missing:

        contact = _get_student_contact(item["student_id"])

        phone = (
            _normalize_phone(contact.get("phone"))
            if contact
            else None
        )

        if not _validate_phone(phone):

            summary["needs_phone_fix"] += 1

            continue

        outcome = _send_event_sms(
            item["student_id"],
            item["message_type"],
            attendance_id=item["attendance_id"],
            status=item["status"],
            time_text=str(item["time_val"] or "")[:5] or None,
        )

        code = outcome["result"]

        if code == RESULT_ACCEPTED:
            summary["sent"] += 1

        elif code != RESULT_ALREADY_SENT:
            summary["failed"] += 1

    logging.info(
        "SMS Service: Retry completed. "
        f"Total={summary['total']}, Sent={summary['sent']}, "
        f"Failed={summary['failed']}, "
        f"NeedsPhoneFix={summary['needs_phone_fix']}"
    )

    return summary


# ============================================================
# SMS SERVICE STATUS
# ============================================================

def sms_service_status():
    """
    فحص حالة خدمة SMS بدون إرسال رسالة.

    يرجع: android, pyjnius, sms_permission, sms_manager
    """

    status = {
        "android": False,
        "pyjnius": False,
        "sms_permission": False,
        "sms_manager": False,
    }

    try:

        import jnius  # noqa: F401

        status["pyjnius"] = True

    except Exception:

        return status

    activity = _get_android_activity()

    if activity is None:
        return status

    status["android"] = True

    status["sms_permission"] = _has_sms_permission()

    if status["sms_permission"]:

        status["sms_manager"] = (
            _get_sms_manager() is not None
        )

    return status
