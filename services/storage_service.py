"""
AMIR SYSTEM
Storage Service (نسخ الملفات إلى مجلد Download العام)

المشكلة: من Android 10/11 فصاعدًا لا يستطيع التطبيق الكتابة مباشرة
داخل مجلد Download العام. الحل المعتمد من Android:

    Android 10 فما فوق : MediaStore (لا يحتاج إذنًا)
    Android 9 فما دون  : نسخ مباشر (يحتاج إذن WRITE_EXTERNAL_STORAGE)

تُحفظ الملفات في:

    Download/AMIR/<مجلد فرعي>/

تنبيه: هذا الملف لم يُختبر إلا على غير Android (يُرجع رسالة واضحة).
اختباره الحقيقي على الهاتف.
"""

import logging
import os
import shutil


PUBLIC_DOWNLOAD_DIR = "/storage/emulated/0/Download"

ROOT_FOLDER_NAME = "AMIR"


def _is_android():
    return (
        "ANDROID_ARGUMENT" in os.environ
        or "ANDROID_PRIVATE" in os.environ
    )


def _sdk_int():
    from jnius import autoclass

    return int(autoclass("android.os.Build$VERSION").SDK_INT)


def _relative_folder(subfolder):

    subfolder = str(subfolder or "").strip().strip("/\\")

    if subfolder:
        return f"{ROOT_FOLDER_NAME}/{subfolder}"

    return ROOT_FOLDER_NAME


def _write_bytes(stream, chunk):

    try:
        stream.write(bytearray(chunk))

    except Exception:
        # بديل بطيء لكنه مضمون: قائمة أرقام موقّعة.
        stream.write(
            [value - 256 if value > 127 else value for value in chunk]
        )


def _export_with_mediastore(source_path, subfolder, mime_type):

    from jnius import autoclass

    activity = autoclass(
        "org.kivy.android.PythonActivity"
    ).mActivity

    content_values_class = autoclass("android.content.ContentValues")
    media_columns = autoclass("android.provider.MediaStore$MediaColumns")
    downloads = autoclass("android.provider.MediaStore$Downloads")

    file_name = os.path.basename(source_path)
    relative_path = f"Download/{_relative_folder(subfolder)}"

    values = content_values_class()
    values.put(media_columns.DISPLAY_NAME, file_name)
    values.put(media_columns.MIME_TYPE, mime_type)
    values.put(media_columns.RELATIVE_PATH, relative_path)

    resolver = activity.getContentResolver()

    uri = resolver.insert(downloads.EXTERNAL_CONTENT_URI, values)

    if uri is None:
        return False, "Android refused to create the file in Downloads."

    stream = resolver.openOutputStream(uri)

    if stream is None:
        return False, "Android refused to open the file in Downloads."

    try:

        with open(source_path, "rb") as source:

            while True:

                chunk = source.read(65536)

                if not chunk:
                    break

                _write_bytes(stream, chunk)

    finally:
        stream.close()

    return True, f"{relative_path}/{file_name}"


def _export_with_direct_copy(source_path, subfolder):

    target_directory = os.path.join(
        PUBLIC_DOWNLOAD_DIR,
        *_relative_folder(subfolder).split("/")
    )

    os.makedirs(target_directory, exist_ok=True)

    target_path = os.path.join(
        target_directory,
        os.path.basename(source_path)
    )

    shutil.copyfile(source_path, target_path)

    return True, target_path


def export_to_downloads(
    source_path,
    subfolder="",
    mime_type="application/octet-stream"
):
    """
    ينسخ ملفًا إلى Download/AMIR/<subfolder>/.

    يرجع (True, مكان الملف) أو (False, سبب).
    لا يرفع استثناءً.
    """

    try:

        if not source_path or not os.path.isfile(source_path):
            return False, "The file was not found."

        # الملف أصلًا في Download العام: لا نكرره.
        if os.path.abspath(source_path).startswith(PUBLIC_DOWNLOAD_DIR):
            return True, source_path

        if not _is_android():
            return False, "Not running on Android."

        if _sdk_int() >= 29:
            return _export_with_mediastore(
                source_path,
                subfolder,
                mime_type
            )

        return _export_with_direct_copy(source_path, subfolder)

    except Exception as exc:

        logging.exception("Could not copy the file to Downloads.")

        return False, f"Copy to Downloads failed: {exc}"
