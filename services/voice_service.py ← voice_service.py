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
_tts_listener = None


# ============================================================
# ANDROID TTS INITIALIZATION
# ============================================================

def _get_android_tts():
    """
    إنشاء Android TextToSpeech.

    تهيئة TTS غير متزامنة.
    يصبح جاهزًا فقط بعد نجاح onInit().
    """

    global _tts
    global _tts_initialized
    global _tts_ready
    global _tts_listener

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

        Locale = autoclass(
            "java.util.Locale"
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

                global _tts_ready

                try:

                    if status != TextToSpeech.SUCCESS:

                        _tts_ready = False

                        logging.error(
                            "AMIR SYSTEM TTS initialization failed."
                        )

                        return

                    language_result = _tts.setLanguage(
                        Locale.US
                    )

                    if (
                        language_result
                        == TextToSpeech.LANG_MISSING_DATA
                    ):

                        _tts_ready = False

                        logging.error(
                            "TTS language data is missing."
                        )

                        return

                    if (
                        language_result
                        == TextToSpeech.LANG_NOT_SUPPORTED
                    ):

                        _tts_ready = False

                        logging.error(
                            "TTS language is not supported."
                        )

                        return

                    _tts_ready = True

                    logging.info(
                        "AMIR SYSTEM TTS initialized successfully."
                    )

                except Exception as e:

                    _tts_ready = False

                    logging.error(
                        f"TTS onInit error: {e}"
                    )

        activity = PythonActivity.mActivity

        if activity is None:

            logging.error(
                "TTS: Android Activity is unavailable."
            )

            return None

        # الاحتفاظ بالـlistener مهم جدًا.
        _tts_listener = TTSListener()

        _tts = TextToSpeech(
            activity,
            _tts_listener
        )

        _tts_initialized = True

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

def speak(text):
    """
    نطق نص باستخدام Android TTS.

    True:
        تم قبول طلب النطق.

    False:
        لم يبدأ النطق.

    ملاحظة:
    فشل TTS لا يعني فشل عملية الحضور.
    """

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

        if not _tts_ready:

            logging.warning(
                "Voice Service: TTS is not ready yet."
            )

            return False

        from jnius import autoclass

        TextToSpeech = autoclass(
            "android.speech.tts.TextToSpeech"
        )

        result = tts.speak(
            text,
            TextToSpeech.QUEUE_FLUSH,
            None,
            "AMIR_TTS"
        )

        if result == TextToSpeech.ERROR:

            logging.error(
                "Android TTS rejected speech request."
            )

            return False

        return True

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
    فحص حالة خدمة الصوت بدون إجبارها
    على إرسال رسالة صوتية.
    """

    try:

        tts = _get_android_tts()

        if tts is None:

            return {
                "available": False,
                "ready": False,
                "message": (
                    "Android TTS unavailable."
                )
            }

        if not _tts_ready:

            return {
                "available": True,
                "ready": False,
                "message": (
                    "Android TTS is initializing."
                )
            }

        return {
            "available": True,
            "ready": True,
            "message": (
                "Android TTS is ready."
            )
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
    global _tts_listener

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
        _tts_listener = None
