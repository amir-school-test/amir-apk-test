import logging
from kivy.clock import Clock

from services.attendance_service import (
    STUDENT_QR_PREFIX,
    ADMIN_QR_PREFIX
)


# مهلة الانتظار بعد آخر تغيير للنص.
SCAN_DELAY = 0.35

_pending_events = {}
_processing_instances = set()


def _normalize_text(value):
    if value is None:
        return ""

    return str(value).strip()


def _cancel_previous_event(instance):
    event = _pending_events.pop(instance, None)

    if event is not None:
        try:
            event.cancel()
        except Exception:
            logging.exception(
                "Unable to cancel a pending QR scan."
            )


def _is_admin_qr(text):
    if not text.upper().startswith(ADMIN_QR_PREFIX):
        return False

    parts = text.split(":")

    if len(parts) != 3:
        return False

    mode = parts[1].strip().upper()
    token = parts[2].strip()

    return mode in ("EXAM", "SICK") and bool(token)


def _is_student_qr(text):
    if not text.upper().startswith(STUDENT_QR_PREFIX):
        return False

    student_id = text[len(STUDENT_QR_PREFIX):].strip()

    return bool(student_id)


def _is_valid_auto_input(text):
    if not text:
        return False

    return _is_student_qr(text) or _is_admin_qr(text)


def _process_after_delay(app, instance, expected_text):
    # لا نحذف حدثًا أحدث قد يكون قد حل محله.
    event = _pending_events.get(instance)

    if event is None:
        return

    _pending_events.pop(instance, None)

    try:
        current_text = _normalize_text(
            getattr(instance, "text", "")
        )

        # تجاهل النص إذا تغيّر بعد جدولة الحدث.
        if current_text != expected_text:
            return

        if not _is_valid_auto_input(current_text):
            return

        # منع إعادة الدخول من الحدث نفسه أثناء المعالجة.
        if instance in _processing_instances:
            return

        if not hasattr(app, "process_attendance"):
            logging.error(
                "Attendance processor is not available."
            )
            return

        _processing_instances.add(instance)

        try:
            app.process_attendance(current_text)
        finally:
            _processing_instances.discard(instance)

        # امسح النص فقط إذا لم يتغير أثناء المعالجة.
        if _normalize_text(
            getattr(instance, "text", "")
        ) == expected_text:
            instance.text = ""

    except Exception:
        logging.exception(
            "Auto service processing error."
        )

    finally:
        _processing_instances.discard(instance)


def check_auto_trigger(app, instance, text):
    """
    يستقبل نص QR، وينتظر انتهاء الكتابة،
    ثم يمرر الرمز إلى معالج الحضور.

    لا ينفذ قواعد الحضور داخل هذه الخدمة.
    """

    text = _normalize_text(text)

    if not text:
        _cancel_previous_event(instance)
        return

    _cancel_previous_event(instance)

    if not (
        text.upper().startswith(STUDENT_QR_PREFIX)
        or text.upper().startswith(ADMIN_QR_PREFIX)
    ):
        return

    event = Clock.schedule_once(
        lambda dt: _process_after_delay(
            app,
            instance,
            text
        ),
        SCAN_DELAY
    )

    _pending_events[instance] = event


def clear_pending_scans():
    """إلغاء جميع عمليات المسح التي لم تبدأ بعد."""

    for instance, event in list(_pending_events.items()):
        try:
            event.cancel()
        except Exception:
            logging.exception(
                "Unable to cancel a pending scan."
            )

    _pending_events.clear()
    _processing_instances.clear()
