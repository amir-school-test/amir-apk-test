"""
AMIR SYSTEM
QR Scan Service (الكاميرا)

وظيفة هذا الملف:
- فتح ماسح Google (ML Kit Code Scanner) عبر الجسر QrBridge.java.
- انتظار النتيجة بدون تعطيل الواجهة.
- تسليم النص المقروء إلى التطبيق. لا يعالج الحضور بنفسه.

يعمل فقط داخل APK المبني (يحتاج ملف QrBridge.java وخيار
android.gradle_dependencies في buildozer.spec). في Pydroid
يرجع رسالة واضحة بدل أن ينهار.

مهم: النص المقروء قد يكون أي QR في العالم، لذلك من يستدعي
هذا الملف مسؤول عن التحقق من أنه QR تابع لنظام AMIR.
"""

import logging

from kivy.clock import Clock


BRIDGE_CLASS = "org.amirtest.bridge.QrBridge"

ACTIVITY_CLASS = "org.kivy.android.PythonActivity"

POLL_INTERVAL_SECONDS = 0.25

# أطول مدة ننتظر فيها نتيجة الماسح (مثلًا إذا لم يُغلق لأي سبب).
SCAN_TIMEOUT_SECONDS = 120

_state = {
    "polling": False,
    "on_result": None,
    "on_status": None,
    "waited": 0.0,
}


def is_scanning():
    return bool(_state["polling"])


def _finish(status, value=""):
    """إنهاء الانتظار وتسليم النتيجة."""

    on_result = _state["on_result"]
    on_status = _state["on_status"]

    _state["polling"] = False
    _state["on_result"] = None
    _state["on_status"] = None
    _state["waited"] = 0.0

    try:

        if status == "ok" and str(value).strip():

            if on_result is not None:
                on_result(str(value).strip())

        elif on_status is not None:
            on_status(status)

    except Exception:
        logging.exception("QR scan callback failed.")


def _poll(dt):

    if not _state["polling"]:
        return False

    _state["waited"] += dt

    try:

        from jnius import autoclass

        bridge = autoclass(BRIDGE_CLASS)

        status = str(bridge.getStatus())

        if status == "scanning":

            if _state["waited"] >= SCAN_TIMEOUT_SECONDS:
                _finish("error: scan timed out")
                return False

            return True

        value = str(bridge.getResult() or "")

    except Exception as exc:

        logging.exception("QR scan polling failed.")

        _finish(f"error: {exc}")

        return False

    _finish(status, value)

    return False


def start_scan(on_result, on_status=None):
    """
    يفتح الماسح.

    on_result(text)   عند قراءة QR.
    on_status(status) عند الإلغاء أو الخطأ:
                      "canceled" أو "error: ...".

    يرجع (started: bool, message: str).
    """

    if _state["polling"]:
        return False, "Scanner is already open."

    try:

        from jnius import autoclass

        activity_class = autoclass(ACTIVITY_CLASS)
        bridge = autoclass(BRIDGE_CLASS)

        bridge.scan(activity_class.mActivity)

    except Exception:

        logging.exception("Could not open the camera scanner.")

        return (
            False,
            "Camera scanner is available only in the installed APK."
        )

    _state["polling"] = True
    _state["on_result"] = on_result
    _state["on_status"] = on_status
    _state["waited"] = 0.0

    Clock.schedule_interval(_poll, POLL_INTERVAL_SECONDS)

    return True, "Scanner opened."
