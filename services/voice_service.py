"""
AMIR SYSTEM
Voice Service

وظيفة هذا الملف:
- استخدام Android Text-to-Speech (TTS).
- إعطاء تأكيد صوتي للحارس بعد عمليات الحضور والخروج.
- لا يحتوي على منطق الحضور نفسه.
- Student ID هو هوية الطالب.
- فشل الصوت لا يمنع تسجيل الحضور.
"""

import logging

from database.database import get_connection


# ============================================================
# TTS STATE
# ============================================================

_tts = None
_tts_initialized = False
_tts_ready = False
_tts_failed = False
_tts_listener = None
_tts_pending_text = None
_tts_early_status = None
_tts_note = ""
_tts_last_error = ""


# ============================================================
# ANDROID TTS INITIALIZATION
# ============================================================

def _on_tts_init(status):
    """
    يُستدعى عندما ينتهي Android من تشغيل محرك الصوت.

    - يجرّب الإنجليزية الأمريكية ثم الإنجليزية ثم لغة الجهاز.
    - إذا لم تتوفر بيانات أي لغة لا يتوقف: يحاول النطق ويُظهر ملاحظة.
    - ينطق الكلمة التي طُلبت قبل أن يصبح المحرك جاهزًا.
    """

    global _tts_ready
    global _tts_failed
    global _tts_note
    global _tts_early_status
    global _tts_pending_text

    try:

        from jnius import autoclass

        text_to_speech = autoclass(
            "android.speech.tts.TextToSpeech"
        )

        locale_class = autoclass(
            "java.util.Locale"
        )

        # قد يصل onInit قبل أن يكتمل إنشاء الكائن.
        if _tts is None:
            _tts_early_status = status
            return

        if status != text_to_speech.SUCCESS:

            _tts_ready = False
            _tts_failed = True

            _tts_note = (
                "The text-to-speech engine could not start "
                f"(status {status}). Check phone Settings > "
                "Text-to-speech."
            )

            logging.error(
                f"AMIR SYSTEM TTS initialization failed: {status}"
            )

            return

        note = ""
        language_ok = False

        candidates = (
            ("English (US)", locale_class.US),
            ("English", locale_class.ENGLISH),
            ("the phone language", locale_class.getDefault()),
        )

        for label, locale in candidates:

            result = _tts.setLanguage(locale)

            if result not in (
                text_to_speech.LANG_MISSING_DATA,
                text_to_speech.LANG_NOT_SUPPORTED,
            ):

                language_ok = True

                if label != "English (US)":
                    note = (
                        "English (US) voice is not installed; "
                        f"using {label}."
                    )

                break

        if not language_ok:

            note = (
                "No voice data found for English or the phone "
                "language. Install voice data in phone Settings > "
                "Text-to-speech."
            )

        _tts_ready = True
        _tts_failed = False
        _tts_note = note

        logging.info(
            "AMIR SYSTEM TTS initialized. " + note
        )

        pending = _tts_pending_text
        _tts_pending_text = None

        if pending:
            _speak_now(pending)

    except Exception as e:

        _tts_ready = False

        logging.error(
            f"TTS onInit error: {e}"
        )


def _get_android_tts():
    """
    إنشاء Android TextToSpeech (مرة واحدة).

    التهيئة غير متزامنة: الكائن يُرجَع فورًا، ويصبح جاهزًا
    لاحقًا عند وصول onInit. لذلك نستدعي هذه الدالة عند بدء
    التطبيق (init_voice_service) لا عند أول نطق.
    """

    global _tts
    global _tts_initialized
    global _tts_ready
    global _tts_listener
    global _tts_early_status

    if _tts_initialized:
        return _tts

    try:

        from jnius import (
            autoclass,
            PythonJavaClass,
            java_method
        )

        PythonActivity = autoclass(
            "org.kivy.android.PythonActivity"
        )

        TextToSpeech = autoclass(
            "android.speech.tts.TextToSpeech"
        )

        class TTSListener(PythonJavaClass):

            __javainterfaces__ = [
                "android/speech/tts/"
                "TextToSpeech$OnInitListener"
            ]

            def __init__(self):
                super().__init__()

            @java_method("(I)V")
            def onInit(self, status):
                _on_tts_init(status)

        activity = PythonActivity.mActivity

        if activity is None:

            logging.error(
                "TTS: Android Activity is unavailable."
            )

            return None

        # الاحتفاظ بالـlistener مهم جدًا.
        _tts_listener = TTSListener()

        _tts_early_status = None

        _tts = TextToSpeech(
            activity,
            _tts_listener
        )

        _tts_initialized = True

        # إذا وصل onInit أثناء إنشاء الكائن، نكمله الآن.
        if _tts_early_status is not None:

            early_status = _tts_early_status
            _tts_early_status = None

            _on_tts_init(early_status)

        return _tts

    except Exception as e:

        logging.error(
            f"Unable to initialize Android TTS: {e}"
        )

        _tts = None
        _tts_initialized = False
        _tts_ready = False
        _tts_listener = None

        return None


def init_voice_service():
    """
    يبدأ محرك الصوت. استدعِه عند فتح التطبيق، ليكون جاهزًا
    قبل أول طالب.
    """

    return voice_service_status()


# ============================================================
# DATABASE
# ============================================================

def _get_student_name(student_id):
    """
    الحصول على اسم الطالب من قاعدة البيانات.

    Student ID هو مصدر الهوية.
    رقم الهاتف لا يستخدم هنا.
    """

    if student_id is None:
        return None

    student_id = str(student_id).strip()

    if not student_id:
        return None

    try:

        with get_connection() as connection:

            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT name
                FROM students
                WHERE student_id = ?
                LIMIT 1
                """,
                (student_id,)
            )

            row = cursor.fetchone()

            if row is None:

                logging.warning(
                    "Voice Service: Student not found."
                )

                return None

            name = row["name"]

            if name is None:
                return None

            name = str(name).strip()

            if not name:
                return None

            return name

    except Exception as e:

        logging.error(
            f"Voice student lookup error: {e}"
        )

        return None


# ============================================================
# BASIC SPEAK
# ============================================================

def _speak_now(text):
    """
    يطلب من Android نطق النص.

    يجرّب ثلاث صيغ مختلفة لاستدعاء speak() لأن الأجهزة تختلف في
    قبولها، ويحفظ سبب فشل كل محاولة ليظهر في زر Voice & SMS Check.
    """

    global _tts_last_error

    try:

        from jnius import autoclass

        TextToSpeech = autoclass(
            "android.speech.tts.TextToSpeech"
        )

    except Exception as e:

        _tts_last_error = f"jnius: {e}"

        logging.error(
            f"TTS speak error: {e}"
        )

        return False

    def with_null_bundle():
        return _tts.speak(
            text,
            TextToSpeech.QUEUE_FLUSH,
            None,
            "AMIR_TTS"
        )

    def with_empty_bundle():
        Bundle = autoclass("android.os.Bundle")
        return _tts.speak(
            text,
            TextToSpeech.QUEUE_FLUSH,
            Bundle(),
            "AMIR_TTS"
        )

    def with_legacy_params():
        HashMap = autoclass("java.util.HashMap")
        params = HashMap()
        params.put("utteranceId", "AMIR_TTS")
        return _tts.speak(
            text,
            TextToSpeech.QUEUE_FLUSH,
            params
        )

    failures = []

    for name, call in (
        ("null-bundle", with_null_bundle),
        ("empty-bundle", with_empty_bundle),
        ("legacy", with_legacy_params),
    ):

        try:

            result = call()

            if result == TextToSpeech.ERROR:
                failures.append(f"{name}: ERROR")
                continue

            _tts_last_error = ""

            return True

        except Exception as e:

            failures.append(
                f"{name}: {type(e).__name__}: {str(e)[:90]}"
            )

    _tts_last_error = "; ".join(failures)

    logging.error(
        "Android TTS rejected every speech request: "
        + _tts_last_error
    )

    return False


def _engine_info():
    """اسم محرك الصوت الافتراضي وعدد المحركات المثبتة."""

    try:
        engine = str(_tts.getDefaultEngine())
    except Exception:
        engine = "unknown"

    try:
        count = int(_tts.getEngines().size())
    except Exception:
        count = "?"

    return f"engine={engine}, installed={count}"


def speak(text):
    """
    نطق نص باستخدام Android TTS.

    True:
        بدأ النطق، أو سيبدأ فور أن يصبح المحرك جاهزًا.

    False:
        لا يمكن النطق (لا يوجد محرك صوت).

    ملاحظة:
    فشل الصوت لا يعني فشل عملية الحضور.
    """

    global _tts_pending_text

    if text is None:
        return False

    text = str(text).strip()

    if not text:
        return False

    try:

        tts = _get_android_tts()

        if tts is None:

            logging.warning(
                "Voice Service: TTS unavailable."
            )

            return False

        if _tts_failed:
            return False

        if not _tts_ready:

            # المحرك ما زال يبدأ: نحتفظ بآخر كلمة وننطقها عند الجاهزية.
            _tts_pending_text = text

            return True

        return _speak_now(text)

    except Exception as e:

        logging.error(
            f"TTS speak error: {e}"
        )

        return False


# ============================================================
# STUDENT NAME
# ============================================================

def speak_student_name(student_id):
    """
    نطق اسم الطالب.

    مثال:
        Hello Ahmed
    """

    student_name = _get_student_name(
        student_id
    )

    if not student_name:
        return False

    return speak(
        f"Hello {student_name}"
    )


# ============================================================
# CHECK-IN VOICE
# ============================================================

def speak_check_in(
    student_id,
    status=None
):
    """
    تأكيد Check-In صوتيًا.

    On Time:
        Hello Ahmed. Correct Check In.

    Late:
        Hello Ahmed. Correct Check In. Late.

    status يمكن أن يكون:
        Checked In (On Time)
        Checked In (Late)
    """

    student_name = _get_student_name(
        student_id
    )

    if not student_name:
        return False

    is_late = False

    if status is not None:

        status_text = str(
            status
        ).strip().lower()

        is_late = "late" in status_text

    if is_late:

        message = (
            f"Hello {student_name}. "
            "Correct Check In. Late."
        )

    else:

        message = (
            f"Hello {student_name}. "
            "Correct Check In."
        )

    return speak(message)


# ============================================================
# CHECK-OUT VOICE
# ============================================================

def speak_check_out(student_id):
    """
    تأكيد Check-Out العادي.

    مثال:
        Goodbye Ahmed. Correct Check Out.
    """

    student_name = _get_student_name(
        student_id
    )

    if not student_name:
        return False

    return speak(
        f"Goodbye {student_name}. "
        "Correct Check Out."
    )


# ============================================================
# EXAM EXIT VOICE
# ============================================================

def speak_exam_exit(student_id):
    """
    تأكيد خروج الطالب بسبب EXAM MODE.
    """

    student_name = _get_student_name(
        student_id
    )

    if not student_name:
        return False

    return speak(
        f"Hello {student_name}. "
        "Exam Exit."
    )


# ============================================================
# SICK EXIT VOICE
# ============================================================

def speak_sick_exit(student_id):
    """
    تأكيد خروج الطالب بسبب SICK MODE.
    """

    student_name = _get_student_name(
        student_id
    )

    if not student_name:
        return False

    return speak(
        f"Hello {student_name}. "
        "Sick Exit."
    )


# ============================================================
# SCHOOL APPROVED EXIT VOICE
# ============================================================

def speak_school_approved_exit(student_id):
    """
    تأكيد خروج الطالب بموافقة المدرسة (SCHOOL_APPROVAL).
    """

    student_name = _get_student_name(
        student_id
    )

    if not student_name:
        return False

    return speak(
        f"Hello {student_name}. "
        "School Approved Exit."
    )


# ============================================================
# ABSENT VOICE
# ============================================================

def speak_absent(student_id):
    """
    تأكيد تسجيل الطالب كغائب.

    هذه الدالة لا تقوم بتسجيل الغياب.
    هي فقط تنطق التأكيد.
    """

    student_name = _get_student_name(
        student_id
    )

    if not student_name:
        return False

    return speak(
        f"{student_name}. "
        "Marked Absent."
    )


# ============================================================
# ERROR VOICE
# ============================================================

def speak_error(message="Error"):
    """
    نطق رسالة خطأ قصيرة.
    """

    if not message:
        message = "Error"

    return speak(message)


def speak_not_registered():
    """
    عند مسح طالب غير مسجل.
    """

    return speak(
        "Error. Student not registered."
    )


# ============================================================
# VOICE SERVICE STATUS
# ============================================================

def voice_service_status():
    """
    حالة خدمة الصوت. ترجع:
        available: هل يوجد محرك صوت.
        ready:     هل هو جاهز للنطق الآن.
        message:   شرح بسيط يظهر للمدير.
    """

    try:

        tts = _get_android_tts()

        if tts is None:

            return {
                "available": False,
                "ready": False,
                "message": (
                    "Text-to-speech is not available "
                    "(it works only inside the installed app)."
                )
            }

        if _tts_failed:

            return {
                "available": True,
                "ready": False,
                "message": _tts_note or "The voice engine failed to start."
            }

        if not _tts_ready:

            return {
                "available": True,
                "ready": False,
                "message": (
                    "The voice engine is starting. "
                    "Try again in a few seconds."
                )
            }

        message = "Voice is ready (" + _engine_info() + ")."

        if _tts_note:
            message += " " + _tts_note

        if _tts_last_error:
            message += " Last speech error: " + _tts_last_error

        return {
            "available": True,
            "ready": True,
            "message": message
        }

    except Exception as e:

        logging.error(
            f"Voice service status error: {e}"
        )

        return {
            "available": False,
            "ready": False,
            "message": str(e)
        }


# ============================================================
# SHUTDOWN
# ============================================================

def shutdown_voice_service():
    """
    إيقاف Android TTS وتحرير الموارد.
    """

    global _tts
    global _tts_initialized
    global _tts_ready
    global _tts_failed
    global _tts_listener
    global _tts_pending_text
    global _tts_early_status
    global _tts_note
    global _tts_last_error

    try:

        if _tts is not None:

            try:
                _tts.stop()

            except Exception as e:

                logging.error(
                    f"TTS stop error: {e}"
                )

            try:
                _tts.shutdown()

            except Exception as e:

                logging.error(
                    f"TTS shutdown error: {e}"
                )

    except Exception as e:

        logging.error(
            f"TTS cleanup error: {e}"
        )

    finally:

        _tts = None
        _tts_initialized = False
        _tts_ready = False
        _tts_failed = False
        _tts_listener = None
        _tts_pending_text = None
        _tts_early_status = None
        _tts_note = ""
        _tts_last_error = ""
