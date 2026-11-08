import sqlite3
import logging

from database.database import get_db_path


# ============================================================
# VALIDATION HELPERS
# ============================================================

def _clean(value):
    """
    تحويل القيمة إلى نص وتنظيف المسافات.
    None تصبح نصًا فارغًا.
    """
    if value is None:
        return ""

    return str(value).strip()


def _validate_student_data(
    student_id,
    phone,
    name,
    grade,
    section
):
    """
    التحقق من بيانات الطالب الأساسية.
    """

    student_id = _clean(student_id)
    phone = _clean(phone)
    name = _clean(name)
    grade = _clean(grade)
    section = _clean(section)

    if not student_id:
        return False, "معرف الطالب مطلوب"

    if not name:
        return False, "اسم الطالب مطلوب"

    if not grade:
        return False, "الصف الدراسي مطلوب"

    if not section:
        return False, "الشعبة مطلوبة"

    return True, (
        student_id,
        phone,
        name,
        grade,
        section
    )


# ============================================================
# ADD STUDENT
# ============================================================

def add_student(
    student_id,
    phone,
    name,
    grade,
    section
):
    """
    إضافة طالب جديد.

    الهوية الأساسية:
        student_id

    رقم الهاتف:
        يمكن أن يتكرر بين عدة طلاب.

    grade:
        الصف الدراسي، مثل 12.

    section:
        الشعبة، مثل A أو B.
    """

    try:

        valid, result = _validate_student_data(
            student_id,
            phone,
            name,
            grade,
            section
        )

        if not valid:
            return False, result

        (
            student_id,
            phone,
            name,
            grade,
            section
        ) = result

        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:

            cursor = conn.cursor()

            cursor.execute(
                "PRAGMA foreign_keys = ON;"
            )

            cursor.execute(
                """
                INSERT INTO students
                (
                    student_id,
                    phone,
                    name,
                    grade,
                    section
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    student_id,
                    phone,
                    name,
                    grade,
                    section
                )
            )

            conn.commit()

        return True, "تمت إضافة الطالب بنجاح"

    except sqlite3.IntegrityError as e:

        logging.error(
            f"Integrity Error while adding student: {e}"
        )

        # غالبًا student_id موجود مسبقًا.
        return False, (
            "معرف الطالب مسجل مسبقاً"
        )

    except Exception as e:

        logging.error(
            f"Error adding student: {e}"
        )

        return False, (
            f"حدث خطأ أثناء إضافة الطالب: {e}"
        )


# ============================================================
# GET STUDENT BY ID
# ============================================================

def get_student_by_id(student_id):
    """
    البحث عن طالب باستخدام student_id.

    ترجع:

        (
            student_id,
            phone,
            name,
            grade,
            section
        )

    أو None إذا لم يوجد الطالب.
    """

    try:

        student_id = _clean(student_id)

        if not student_id:
            return None

        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    student_id,
                    phone,
                    name,
                    grade,
                    section
                FROM students
                WHERE student_id = ?
                """,
                (student_id,)
            )

            row = cursor.fetchone()

        return row

    except Exception as e:

        logging.error(
            f"Error fetching student by ID: {e}"
        )

        return None


# ============================================================
# GET STUDENTS BY PHONE
# ============================================================

def get_students_by_phone(phone):
    """
    إرجاع جميع الطلاب الذين يستخدمون
    نفس رقم الهاتف.

    مهم:
    phone ليس معرفًا فريدًا للطالب.
    """

    try:

        phone = _clean(phone)

        if not phone:
            return []

        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    student_id,
                    phone,
                    name,
                    grade,
                    section
                FROM students
                WHERE phone = ?
                ORDER BY
                    CASE WHEN grade GLOB '[0-9]*'
                         THEN CAST(grade AS INTEGER)
                         ELSE 9999 END,
                    UPPER(COALESCE(section, '~')),
                    name COLLATE NOCASE,
                    student_id
                """,
                (phone,)
            )

            rows = cursor.fetchall()

        return rows

    except Exception as e:

        logging.error(
            f"Error fetching students by phone: {e}"
        )

        return []


# ============================================================
# UPDATE STUDENT
# ============================================================

def update_student(
    student_id,
    new_phone,
    new_name,
    new_grade,
    new_section
):
    """
    تعديل بيانات الطالب.

    student_id لا يتغير.

    يمكن تغيير:
        phone
        name
        grade
        section

    phone يمكن أن يكون مستخدمًا لطالب آخر.
    """

    try:

        student_id = _clean(student_id)
        new_phone = _clean(new_phone)
        new_name = _clean(new_name)
        new_grade = _clean(new_grade)
        new_section = _clean(new_section)

        if not student_id:
            return False, "معرف الطالب مطلوب"

        if not new_name:
            return False, "اسم الطالب مطلوب"

        if not new_grade:
            return False, "الصف الدراسي مطلوب"

        if not new_section:
            return False, "الشعبة مطلوبة"

        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:

            cursor = conn.cursor()

            cursor.execute(
                "PRAGMA foreign_keys = ON;"
            )

            cursor.execute(
                """
                UPDATE students
                SET
                    phone = ?,
                    name = ?,
                    grade = ?,
                    section = ?
                WHERE student_id = ?
                """,
                (
                    new_phone,
                    new_name,
                    new_grade,
                    new_section,
                    student_id
                )
            )

            if cursor.rowcount == 0:

                return False, (
                    "الطالب غير موجود لتحديث بياناته"
                )

            conn.commit()

        return True, (
            "تم تحديث بيانات الطالب بنجاح"
        )

    except sqlite3.IntegrityError as e:

        logging.error(
            f"Integrity Error updating student: {e}"
        )

        return False, (
            "تعذر تحديث بيانات الطالب بسبب "
            "مشكلة في قاعدة البيانات"
        )

    except Exception as e:

        logging.error(
            f"Error updating student: {e}"
        )

        return False, (
            f"حدث خطأ أثناء تحديث الطالب: {e}"
        )


# ============================================================
# DELETE STUDENT
# ============================================================

def delete_student(student_id):
    """
    حذف الطالب.

    سجلات الحضور التاريخية تمنع الحذف
    بسبب ON DELETE RESTRICT.
    """

    try:

        student_id = _clean(student_id)

        if not student_id:
            return False, "معرف الطالب مطلوب"

        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:

            cursor = conn.cursor()

            cursor.execute(
                "PRAGMA foreign_keys = ON;"
            )

            cursor.execute(
                """
                DELETE FROM students
                WHERE student_id = ?
                """,
                (student_id,)
            )

            if cursor.rowcount == 0:

                return False, (
                    "الطالب غير موجود للحذف"
                )

            conn.commit()

        return True, "تم حذف الطالب بنجاح"

    except sqlite3.IntegrityError as e:

        logging.error(
            f"Integrity Error deleting student "
            f"{student_id}: {e}"
        )

        return False, (
            "لا يمكن حذف الطالب لأنه يمتلك "
            "سجلات حضور تاريخية"
        )

    except Exception as e:

        logging.error(
            f"Error deleting student: {e}"
        )

        return False, (
            f"حدث خطأ أثناء حذف الطالب: {e}"
        )


# ============================================================
# ACTIVATE / DEACTIVATE STUDENT
# ============================================================

def set_student_active(student_id, active):
    """
    تفعيل أو إيقاف طالب (غادر المدرسة) بدون حذف سجلاته.

    الطالب الموقوف:
        - لا يُسجَّل غائبًا تلقائيًا.
        - لا يمر من البوابة.
        - تبقى سجلاته التاريخية كما هي.
    """

    try:

        student_id = _clean(student_id)

        if not student_id:
            return False, "معرف الطالب مطلوب"

        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:

            cursor = conn.cursor()

            cursor.execute(
                "UPDATE students SET active = ? WHERE student_id = ?",
                (1 if active else 0, student_id)
            )

            if cursor.rowcount == 0:
                return False, "الطالب غير موجود"

            conn.commit()

        if active:
            return True, "تم تفعيل الطالب"

        return True, "تم إيقاف الطالب (لم يُحذف)"

    except Exception as e:

        logging.error(
            f"Error changing student active state: {e}"
        )

        return False, f"حدث خطأ: {e}"


# ============================================================
# LOAD ALL STUDENTS
# ============================================================

def load_students_database(*args):
    """
    جلب جميع الطلاب.

    ترتيب:
        grade
        section
        student_id

    الغلاف متوافق مع الاستدعاءات القديمة.
    """

    try:

        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    student_id,
                    phone,
                    name,
                    grade,
                    section
                FROM students
                ORDER BY
                    CASE WHEN grade GLOB '[0-9]*'
                         THEN CAST(grade AS INTEGER)
                         ELSE 9999 END,
                    UPPER(COALESCE(section, '~')),
                    name COLLATE NOCASE,
                    student_id
                """
            )

            rows = cursor.fetchall()

        return rows

    except Exception as e:

        logging.error(
            f"Error loading students: {e}"
        )

        return []


# ============================================================
# COMPATIBILITY WRAPPER
# ============================================================

def insert_student_to_db(*args):
    """
    غلاف متوافق مع الاستدعاءات القديمة.

    الصيغة الجديدة:

        insert_student_to_db(
            student_id,
            phone,
            name,
            grade,
            section
        )

    أو إذا كان أول argument هو app/self:

        insert_student_to_db(
            app,
            student_id,
            phone,
            name,
            grade,
            section
        )
    """

    actual_args = args

    # app/self + 5 بيانات
    if len(args) == 6:
        actual_args = args[1:]

    if len(actual_args) >= 5:

        return add_student(
            actual_args[0],
            actual_args[1],
            actual_args[2],
            actual_args[3],
            actual_args[4]
        )

    return False, (
        "بيانات غير كافية لإضافة الطالب"
    )


# ============================================================
# COMPATIBILITY WRAPPER
# ============================================================

def update_student_in_db(*args):
    """
    غلاف متوافق مع الاستدعاءات القديمة.

    الصيغة الجديدة:

        update_student_in_db(
            student_id,
            phone,
            name,
            grade,
            section
        )

    أو:

        update_student_in_db(
            app,
            student_id,
            phone,
            name,
            grade,
            section
        )
    """

    actual_args = args

    # app/self + 5 بيانات
    if len(args) == 6:
        actual_args = args[1:]

    if len(actual_args) >= 5:

        return update_student(
            actual_args[0],
            actual_args[1],
            actual_args[2],
            actual_args[3],
            actual_args[4]
        )

    return False, (
        "بيانات غير كافية لتحديث بيانات الطالب"
    )


# ============================================================
# COMPATIBILITY WRAPPER
# ============================================================

def delete_student_from_db(*args):
    """
    غلاف متوافق مع الاستدعاءات القديمة.
    """

    actual_args = args

    if len(args) == 2:
        actual_args = args[1:]

    if len(actual_args) >= 1:

        return delete_student(
            actual_args[0]
        )

    return False, (
        "معرف الطالب غير موجود للحذف"
    )
