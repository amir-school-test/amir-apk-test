import logging
import os
import sqlite3
from datetime import datetime

from database.database import get_db_path


# ============================================================
# BACKUP SERVICE - AMIR SYSTEM
# ============================================================
#
# مسؤول عن:
# 1. إنشاء نسخة احتياطية كاملة من قاعدة بيانات AMIR SYSTEM.
# 2. استخدام SQLite Backup API.
# 3. محاولة الحفظ في:
#
#       /storage/emulated/0/Download/AMIR_Backups
#
#    وإذا لم يكن متاحًا:
#
#       App user_data_dir/AMIR_Backups
#
# 4. التحقق من قاعدة البيانات الأصلية.
# 5. إنشاء النسخة في ملف مؤقت.
# 6. فحص سلامة النسخة.
# 7. تحويل النسخة المؤقتة إلى نسخة نهائية فقط بعد نجاح الفحص.
# 8. تنظيف الملفات المؤقتة عند حدوث خطأ.
# 9. إرجاع نتيجة واضحة إلى شاشة الإدارة.
#
# النسخة الاحتياطية تشمل قاعدة البيانات كاملة:
#
# - students
# - attendance
# - settings
# - passcodes
# - system_modes
# - admin_qr_tokens
# - وأي جداول مستقبلية موجودة داخل نفس قاعدة البيانات.
#
# لا يحتوي على:
# - منطق الحضور.
# - QR.
# - إدارة الطلاب.
# - كلمة مرور المسؤول.
# - التقارير.
# - PDF.
# ============================================================


# ============================================================
# Constants
# ============================================================

BACKUP_FOLDER_NAME = "AMIR_Backups"

BACKUP_FILENAME_PREFIX = (
    "AMIR_database_backup_"
)

TEMP_FILENAME_SUFFIX = ".tmp"

ANDROID_DOWNLOAD_PATH = (
    "/storage/emulated/0/Download"
)


# ============================================================
# Logging
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# Backup Directory
# ============================================================

def _get_backup_directory(app=None):
    """
    الحصول على مجلد Backup قابل للكتابة.

    الأولوية:

    1. Android Download/AMIR_Backups
    2. App user_data_dir/AMIR_Backups

    ملاحظة:
    قد يمنع Android الوصول المباشر إلى بعض المجلدات العامة
    حسب إصدار Android والصلاحيات.

    لذلك يوجد fallback داخل user_data_dir.

    يرجع:
        str

    يرفع:
        OSError
    """

    # --------------------------------------------------------
    # 1. Android Download
    # --------------------------------------------------------

    try:

        download_directory = os.path.join(
            ANDROID_DOWNLOAD_PATH,
            BACKUP_FOLDER_NAME
        )

        os.makedirs(
            download_directory,
            exist_ok=True
        )

        if (
            os.path.isdir(
                download_directory
            )
            and os.access(
                download_directory,
                os.W_OK
            )
        ):

            return download_directory

    except Exception as e:

        logger.warning(
            "Could not use Android Download "
            f"backup directory: {e}"
        )

    # --------------------------------------------------------
    # 2. Application private storage
    # --------------------------------------------------------

    try:

        if app is not None:

            app_data_directory = getattr(
                app,
                "user_data_dir",
                None
            )

            if app_data_directory:

                fallback_directory = os.path.join(
                    app_data_directory,
                    BACKUP_FOLDER_NAME
                )

                os.makedirs(
                    fallback_directory,
                    exist_ok=True
                )

                if (
                    os.path.isdir(
                        fallback_directory
                    )
                    and os.access(
                        fallback_directory,
                        os.W_OK
                    )
                ):

                    return fallback_directory

    except Exception as e:

        logger.warning(
            "Could not use application backup "
            f"directory: {e}"
        )

    raise OSError(
        "No writable backup directory is available."
    )


# ============================================================
# Backup Filename
# ============================================================

def _create_backup_filename():
    """
    إنشاء اسم Backup فريد.

    مثال:

    AMIR_database_backup_2026-09-22_08-58-31-123456.db
    """

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S-%f"
    )

    return (
        f"{BACKUP_FILENAME_PREFIX}"
        f"{timestamp}.db"
    )


# ============================================================
# SQLite Connection Helper
# ============================================================

def _open_database(database_path):
    """
    فتح اتصال SQLite مناسب لعملية Backup.
    """

    connection = sqlite3.connect(
        database_path,
        timeout=30
    )

    try:

        connection.execute(
            "PRAGMA busy_timeout = 30000;"
        )

    except Exception:

        pass

    return connection


# ============================================================
# Source Database Verification
# ============================================================

def _verify_source_database(source_path):
    """
    التحقق من أن قاعدة البيانات الأصلية:

    - موجودة.
    - ملف حقيقي.
    - غير فارغة.
    - سليمة حسب integrity_check.

    يرجع:

        (True, "OK")

    أو:

        (False, "سبب الخطأ")
    """

    if not os.path.exists(
        source_path
    ):

        return (
            False,
            "AMIR database was not found."
        )

    if not os.path.isfile(
        source_path
    ):

        return (
            False,
            "AMIR database path is not a file."
        )

    try:

        file_size = os.path.getsize(
            source_path
        )

        if file_size <= 0:

            return (
                False,
                "AMIR database file is empty."
            )

    except OSError as e:

        return (
            False,
            f"Could not inspect database: {e}"
        )

    connection = None

    try:

        connection = _open_database(
            source_path
        )

        cursor = connection.cursor()

        cursor.execute(
            "PRAGMA integrity_check;"
        )

        result = cursor.fetchone()

        if not result:

            return (
                False,
                "Could not verify source database integrity."
            )

        integrity_result = str(
            result[0]
        ).strip().lower()

        if integrity_result != "ok":

            return (
                False,
                "Source database integrity check failed."
            )

        return True, "OK"

    except sqlite3.Error as e:

        logger.error(
            f"Source database check failed: {e}"
        )

        return (
            False,
            f"Source database check failed: {e}"
        )

    except Exception as e:

        logger.error(
            f"Unexpected source database check error: {e}"
        )

        return (
            False,
            f"Database check error: {e}"
        )

    finally:

        if connection is not None:

            try:
                connection.close()
            except Exception:
                pass


# ============================================================
# Backup Integrity Verification
# ============================================================

def _verify_backup_integrity(
    backup_path
):
    """
    فحص سلامة ملف Backup.

    يرجع:

        True
        False
    """

    if not os.path.exists(
        backup_path
    ):

        return False

    if not os.path.isfile(
        backup_path
    ):

        return False

    try:

        if os.path.getsize(
            backup_path
        ) <= 0:

            return False

    except OSError:

        return False

    connection = None

    try:

        connection = _open_database(
            backup_path
        )

        cursor = connection.cursor()

        cursor.execute(
            "PRAGMA integrity_check;"
        )

        result = cursor.fetchone()

        if not result:

            return False

        integrity_result = str(
            result[0]
        ).strip().lower()

        return integrity_result == "ok"

    except Exception as e:

        logger.error(
            "Backup integrity check failed: "
            f"{e}"
        )

        return False

    finally:

        if connection is not None:

            try:
                connection.close()
            except Exception:
                pass


# ============================================================
# Safe File Removal
# ============================================================

def _remove_file_safely(
    file_path
):
    """
    حذف ملف بأمان.

    يستخدم لتنظيف:
    - ملفات .tmp
    - ملفات Backup غير مكتملة
    """

    if not file_path:
        return

    try:

        if os.path.exists(
            file_path
        ):

            os.remove(
                file_path
            )

    except Exception as e:

        logger.warning(
            "Could not remove file "
            f"'{file_path}': {e}"
        )


# ============================================================
# Create Backup
# ============================================================

def create_backup(app=None):
    """
    إنشاء نسخة احتياطية كاملة من قاعدة بيانات
    AMIR SYSTEM.

    الخطوات:

    1. التحقق من المصدر.
    2. تحديد مجلد Backup.
    3. إنشاء اسم نهائي.
    4. إنشاء ملف مؤقت.
    5. استخدام SQLite Backup API.
    6. إغلاق الاتصالات.
    7. فحص النسخة.
    8. نقل النسخة إلى اسمها النهائي.
    9. التحقق النهائي.

    يرجع:

        (
            success,
            message,
            backup_path
        )
    """

    source_db = get_db_path()

    # ========================================================
    # 1. Verify Source
    # ========================================================

    source_ok, source_message = (
        _verify_source_database(
            source_db
        )
    )

    if not source_ok:

        logger.error(
            "Source database verification failed: "
            f"{source_message}"
        )

        return (
            False,
            source_message,
            None
        )

    # ========================================================
    # Variables
    # ========================================================

    source_connection = None
    backup_connection = None

    temporary_backup_path = None
    final_backup_path = None

    try:

        # ====================================================
        # 2. Backup Directory
        # ====================================================

        backup_directory = (
            _get_backup_directory(app)
        )

        # ====================================================
        # 3. Final Filename
        # ====================================================

        backup_filename = (
            _create_backup_filename()
        )

        final_backup_path = os.path.join(
            backup_directory,
            backup_filename
        )

        # ====================================================
        # 4. Temporary Filename
        # ====================================================

        temporary_backup_path = (
            final_backup_path
            + TEMP_FILENAME_SUFFIX
        )

        # إزالة ملف مؤقت بنفس الاسم إن وجد
        _remove_file_safely(
            temporary_backup_path
        )

        # ====================================================
        # 5. Open Source
        # ====================================================

        source_connection = _open_database(
            source_db
        )

        # ====================================================
        # 6. Open Temporary Destination
        # ====================================================

        backup_connection = _open_database(
            temporary_backup_path
        )

        # ====================================================
        # 7. SQLite Backup API
        # ====================================================
        #
        # نستخدم SQLite Backup API بدل نسخ الملف مباشرة.
        #
        # هذا مهم لأن SQLite قد تكون قيد الاستخدام
        # أثناء تشغيل AMIR SYSTEM.
        # ====================================================

        source_connection.backup(
            backup_connection
        )

        backup_connection.commit()

        # ====================================================
        # 8. Close Connections
        # ====================================================

        backup_connection.close()
        backup_connection = None

        source_connection.close()
        source_connection = None

        # ====================================================
        # 9. Temporary File Exists?
        # ====================================================

        if not os.path.exists(
            temporary_backup_path
        ):

            return (
                False,
                "Backup file was not created.",
                None
            )

        # ====================================================
        # 10. Temporary File Size
        # ====================================================

        temporary_size = os.path.getsize(
            temporary_backup_path
        )

        if temporary_size <= 0:

            _remove_file_safely(
                temporary_backup_path
            )

            return (
                False,
                "Backup file is empty.",
                None
            )

        # ====================================================
        # 11. Integrity Check
        # ====================================================

        if not _verify_backup_integrity(
            temporary_backup_path
        ):

            logger.error(
                "Backup integrity verification failed."
            )

            _remove_file_safely(
                temporary_backup_path
            )

            return (
                False,
                "Backup was created but failed "
                "the database integrity check.",
                None
            )

        # ====================================================
        # 12. Finalize Backup
        # ====================================================
        #
        # os.replace يجعل الانتقال من المؤقت إلى النهائي
        # عملية واحدة على نفس filesystem.
        # ====================================================

        os.replace(
            temporary_backup_path,
            final_backup_path
        )

        temporary_backup_path = None

        # ====================================================
        # 13. Final File Verification
        # ====================================================

        if not os.path.exists(
            final_backup_path
        ):

            return (
                False,
                "Backup was verified but could not "
                "be finalized.",
                None
            )

        final_size = os.path.getsize(
            final_backup_path
        )

        if final_size <= 0:

            _remove_file_safely(
                final_backup_path
            )

            return (
                False,
                "Final backup file is empty.",
                None
            )

        # ====================================================
        # 14. Final Integrity Check
        # ====================================================

        if not _verify_backup_integrity(
            final_backup_path
        ):

            logger.error(
                "Final backup integrity verification failed."
            )

            _remove_file_safely(
                final_backup_path
            )

            return (
                False,
                "Final backup failed the integrity check.",
                None
            )

        # ====================================================
        # 15. Success
        # ====================================================

        logger.info(
            "AMIR database backup created successfully: "
            f"{final_backup_path}"
        )

        return (
            True,
            "Database backup created and verified successfully.",
            final_backup_path
        )

    except sqlite3.Error as e:

        logger.error(
            f"SQLite backup error: {e}"
        )

        _remove_file_safely(
            temporary_backup_path
        )

        _remove_file_safely(
            final_backup_path
        )

        return (
            False,
            f"SQLite backup error: {e}",
            None
        )

    except OSError as e:

        logger.error(
            f"Backup file system error: {e}"
        )

        _remove_file_safely(
            temporary_backup_path
        )

        _remove_file_safely(
            final_backup_path
        )

        return (
            False,
            f"Backup file system error: {e}",
            None
        )

    except Exception as e:

        logger.error(
            f"Unexpected backup error: {e}"
        )

        _remove_file_safely(
            temporary_backup_path
        )

        _remove_file_safely(
            final_backup_path
        )

        return (
            False,
            f"Backup error: {e}",
            None
        )

    finally:

        # ====================================================
        # Safety Cleanup
        # ====================================================

        if backup_connection is not None:

            try:
                backup_connection.close()
            except Exception:
                pass

        if source_connection is not None:

            try:
                source_connection.close()
            except Exception:
                pass

        # ====================================================
        # Remove Leftover Temporary File
        # ====================================================

        if temporary_backup_path is not None:

            _remove_file_safely(
                temporary_backup_path
            )


# ============================================================
# Screen Integration
# ============================================================

def backup_database(
    app,
    instance=None
):
    """
    Compatibility wrapper.

    يستخدم من App:

        app.backup_database(instance)

    ويحافظ على وظيفة زر:

        Backup Database (SQLite)

    يرجع:

        (
            success,
            message,
            backup_path
        )
    """

    try:

        success, message, backup_path = (
            create_backup(app)
        )

        # ====================================================
        # Display Result
        # ====================================================

        if (
            app is not None
            and hasattr(
                app,
                "root"
            )
        ):

            try:

                admin_screen = (
                    app.root.get_screen(
                        "admin_reports"
                    )
                )

                if hasattr(
                    admin_screen,
                    "report_label"
                ):

                    if success:

                        filename = (
                            os.path.basename(
                                backup_path
                            )
                        )

                        admin_screen.report_label.text += (
                            "\n\n"
                            "[color=00FF00]"
                            "Backup Saved Successfully"
                            "[/color]\n"
                            f"File: {filename}"
                        )

                    else:

                        admin_screen.report_label.text += (
                            "\n\n"
                            "[color=FF0000]"
                            "Backup Error: "
                            f"{message}"
                            "[/color]"
                        )

            except Exception as e:

                logger.error(
                    "Could not display backup result: "
                    f"{e}"
                )

        return (
            success,
            message,
            backup_path
        )

    except Exception as e:

        logger.error(
            f"Backup wrapper error: {e}"
        )

        return (
            False,
            f"Backup error: {e}",
            None
          )
