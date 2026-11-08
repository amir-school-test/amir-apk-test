import logging
import re
from datetime import datetime

from database.database import get_connection


# ============================================================
# REPORT SERVICE
# ============================================================
#
# مسؤول عن:
# 1. قراءة الطلاب وسجلات الحضور من SQLite.
# 2. ربط attendance.student_id مع students.student_id.
# 3. تجميع الطلاب حسب الصف + الشعبة.
# 4. تحويل حالات الحضور إلى رموز.
# 5. حساب أيام الغياب المسجلة.
# 6. إنشاء النص الذي تعرضه شاشة التقارير.
#
# لا يحتوي على:
# - منطق QR.
# - تسجيل الدخول والخروج.
# - تغيير كلمة المرور.
# - النسخ الاحتياطي.
# - إنشاء PDF.
#
# ملاحظة مهمة:
# Grade و Section يتم قراءتهما مباشرة من قاعدة البيانات.
# لا يتم استخراج الصف من اسم الطالب.
# ============================================================


# ============================================================
# Constants
# ============================================================

OTHER_GRADES = "Other Grades"

VALID_SYMBOLS = {
    "IN",
    "OUT",
    "AB",
    "LT",
    "SK",
    "EXM",
    "HD",
    "EX",
}


# ============================================================
# Kivy Markup Safety
# ============================================================

def _escape_markup(value):
    """
    حماية النصوص التي ستظهر داخل Kivy Markup.

    إذا احتوى النص على:
        [
        ]

    فلن يتعامل معها Kivy على أنها Markup.
    """

    if value is None:
        return ""

    value = str(value)

    return (
        value
        .replace("&", "&amp;")
        .replace("[", "&bl;")
        .replace("]", "&br;")
    )


# ============================================================
# Grade / Section Helpers
# ============================================================

def _normalize_grade(grade):
    """
    توحيد قيمة الصف.

    قاعدة البيانات تخزن الصف مثل:
        12
        11
        1

    ويظهر في التقرير مثل:
        Grade 12
        Grade 11
        Grade 1
    """

    if grade is None:
        return OTHER_GRADES

    grade = str(grade).strip()

    if not grade:
        return OTHER_GRADES

    # إذا كانت القيمة أصلًا "Grade 12"
    match = re.fullmatch(
        r"Grade\s*(\d+)",
        grade,
        re.IGNORECASE
    )

    if match:
        return f"Grade {match.group(1)}"

    # إذا كانت القيمة "12"
    if grade.isdigit():
        return f"Grade {grade}"

    return grade


def _normalize_section(section):
    """
    توحيد قيمة الشعبة.

    أمثلة:
        A
        B
        1
        Blue

    إذا لم توجد شعبة:
        Other
    """

    if section is None:
        return "Other"

    section = str(section).strip()

    if not section:
        return "Other"

    return section


def _make_grade_section_key(grade, section):
    """
    إنشاء مفتاح ثابت لتجميع الطلاب.

    مثال:
        Grade 12 + A
        -> Grade 12 - Section A
    """

    normalized_grade = _normalize_grade(grade)
    normalized_section = _normalize_section(section)

    if normalized_grade == OTHER_GRADES:
        return OTHER_GRADES

    return (
        f"{normalized_grade} - "
        f"Section {normalized_section}"
    )


# ============================================================
# Attendance Symbol Helpers
# ============================================================

def _normalize_attendance_value(value):
    """
    تحويل قيمة attendance إلى نص موحد.
    """

    if value is None:
        return ""

    return str(value).strip().upper()


def _get_symbol(record_type, status):
    """
    تحويل سجل الحضور إلى رمز واحد.

    الرموز:

        IN   = Check-In
        OUT  = Check-Out
        AB   = Absent
        LT   = Late / Too Late
        SK   = Sick
        EXM  = Exam
        HD   = Half-Day
        EX   = Other

    ملاحظة:
    يتم فحص EXAM وSICK قبل CHECK-OUT لأن
    سجلات EXAM/SICK قد تحتوي أيضًا على status = CHECK-OUT.
    """

    record_type = _normalize_attendance_value(
        record_type
    )

    status = _normalize_attendance_value(
        status
    )

    combined = f"{record_type} {status}"

    # --------------------------------------------------------
    # ABSENT / TOO LATE
    # --------------------------------------------------------

    if "TOO LATE" in combined:
        return "LT"

    if "ABSENT" in combined:
        return "AB"

    # --------------------------------------------------------
    # SICK
    # --------------------------------------------------------

    if "SICK" in combined:
        return "SK"

    # --------------------------------------------------------
    # EXAM
    # --------------------------------------------------------

    if "EXAM" in combined:
        return "EXM"

    # --------------------------------------------------------
    # HALF DAY
    # --------------------------------------------------------

    if (
        "HALF-DAY" in combined
        or "HALFDAY" in combined
        or "HALF DAY" in combined
    ):
        return "HD"

    # --------------------------------------------------------
    # LATE
    # --------------------------------------------------------

    if "LATE" in combined:
        return "LT"

    # --------------------------------------------------------
    # CHECK OUT
    # --------------------------------------------------------

    if (
        "CHECK-OUT" in combined
        or "CHECK OUT" in combined
        or record_type == "EXIT"
        or "CHECKED OUT" in combined
    ):
        return "OUT"

    # --------------------------------------------------------
    # CHECK IN
    # --------------------------------------------------------

    if (
        "CHECK-IN" in combined
        or "CHECK IN" in combined
        or record_type == "PRESENT"
        or "CHECKED IN" in combined
    ):
        return "IN"

    # --------------------------------------------------------
    # Unknown
    # --------------------------------------------------------

    return "EX"


# ============================================================
# Database Loading
# ============================================================

def _load_report_data():
    """
    تحميل جميع البيانات المطلوبة للتقرير.

    الطلاب:
        students.student_id
        students.name
        students.grade
        students.section

    الحضور:
        attendance.student_id
        attendance.date_val
        attendance.time_val
        attendance.record_type
        attendance.status
        attendance.day_name
        attendance.id

    Student ID هو الرابط الأساسي بين الجدولين.

    الهاتف لا يستخدم هنا كهوية للطالب.
    """

    grades_students = {}

    student_names_by_id = {}

    student_grade_section_by_id = {}

    student_date_status = {}

    absences_by_grade_section = {}

    all_dates = set()

    try:

        with get_connection() as conn:

            cursor = conn.cursor()

            # ------------------------------------------------
            # Registered Students
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    student_id,
                    name,
                    grade,
                    section
                FROM students
                ORDER BY
                    grade ASC,
                    section ASC,
                    name COLLATE NOCASE ASC,
                    student_id ASC
                """
            )

            student_rows = cursor.fetchall()

            for row in student_rows:

                student_id = (
                    str(row["student_id"]).strip()
                    if row["student_id"] is not None
                    else ""
                )

                name = (
                    str(row["name"]).strip()
                    if row["name"] is not None
                    else ""
                )

                grade = (
                    str(row["grade"]).strip()
                    if row["grade"] is not None
                    else ""
                )

                section = (
                    str(row["section"]).strip()
                    if row["section"] is not None
                    else ""
                )

                if not student_id:
                    continue

                if not name:
                    name = "Unknown Student"

                student_names_by_id[
                    student_id
                ] = name

                grade_section = (
                    _make_grade_section_key(
                        grade,
                        section
                    )
                )

                student_grade_section_by_id[
                    student_id
                ] = grade_section

                grades_students.setdefault(
                    grade_section,
                    []
                ).append(
                    (
                        student_id,
                        name
                    )
                )

            # ------------------------------------------------
            # Attendance Records
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    student_id,
                    date_val,
                    time_val,
                    record_type,
                    status,
                    day_name,
                    id
                FROM attendance
                WHERE voided_at IS NULL
                ORDER BY
                    date_val ASC,
                    time_val ASC,
                    id ASC
                """
            )

            attendance_rows = cursor.fetchall()

            for row in attendance_rows:

                student_id = (
                    str(row["student_id"]).strip()
                    if row["student_id"] is not None
                    else ""
                )

                date_val = (
                    str(row["date_val"]).strip()
                    if row["date_val"] is not None
                    else ""
                )

                if not student_id or not date_val:
                    continue

                all_dates.add(date_val)

                symbol = _get_symbol(
                    row["record_type"],
                    row["status"]
                )

                if symbol not in VALID_SYMBOLS:
                    symbol = "EX"

                student_date_status.setdefault(
                    student_id,
                    {}
                ).setdefault(
                    date_val,
                    []
                )

                daily_symbols = (
                    student_date_status[
                        student_id
                    ][date_val]
                )

                if symbol not in daily_symbols:
                    daily_symbols.append(symbol)

                # ------------------------------------------------
                # Absence Summary
                # ------------------------------------------------
                #
                # مهم:
                # نريد حساب "يوم غياب" وليس عدد سجلات AB.
                #
                # إذا حدث أكثر من سجل AB لنفس الطالب في نفس اليوم،
                # لا نحسبه غيابين.
                # ------------------------------------------------

                if symbol == "AB":

                    student_name = (
                        student_names_by_id.get(
                            student_id,
                            "Unknown Student"
                        )
                    )

                    grade_section = (
                        student_grade_section_by_id.get(
                            student_id,
                            OTHER_GRADES
                        )
                    )

                    absences_by_grade_section.setdefault(
                        grade_section,
                        {}
                    )

                    student_absence_dates = (
                        absences_by_grade_section[
                            grade_section
                        ].setdefault(
                            student_id,
                            set()
                        )
                    )

                    student_absence_dates.add(
                        date_val
                    )

    except Exception as e:

        logging.error(
            f"Report loading error: {e}"
        )

    return {
        "grades_students": grades_students,
        "student_names_by_id": student_names_by_id,
        "student_grade_section_by_id": (
            student_grade_section_by_id
        ),
        "student_date_status": student_date_status,
        "absences_by_grade_section": (
            absences_by_grade_section
        ),
        "all_dates": all_dates,
    }


# ============================================================
# Date Helpers
# ============================================================

def _sort_dates(dates):
    """
    ترتيب التواريخ زمنيًا.

    التاريخ الأساسي للنظام:
        YYYY-MM-DD

    القيم غير الصحيحة لا تسبب توقف التقرير.
    """

    valid_dates = []
    invalid_dates = []

    for value in dates:

        value = str(value).strip()

        if not value:
            continue

        try:

            parsed_date = datetime.strptime(
                value,
                "%Y-%m-%d"
            )

            valid_dates.append(
                (
                    parsed_date,
                    value
                )
            )

        except ValueError:

            invalid_dates.append(value)

    valid_dates.sort(
        key=lambda item: item[0]
    )

    result = [
        item[1]
        for item in valid_dates
    ]

    result.extend(
        sorted(invalid_dates)
    )

    return result


# ============================================================
# Grade / Section Sorting
# ============================================================

def _grade_section_sort_key(grade_section):
    """
    ترتيب الصفوف والشعب.

    مثال:

        Grade 1 - Section A
        Grade 1 - Section B
        Grade 2 - Section A
        ...
        Grade 12 - Section A
        Other Grades
    """

    if not grade_section:
        return (
            9999,
            "",
            ""
        )

    text = str(grade_section)

    grade_match = re.search(
        r"Grade\s*(\d+)",
        text,
        re.IGNORECASE
    )

    if grade_match:

        try:
            grade_number = int(
                grade_match.group(1)
            )
        except ValueError:
            grade_number = 9999

    else:
        grade_number = 9999

    section_match = re.search(
        r"Section\s*(.+)$",
        text,
        re.IGNORECASE
    )

    if section_match:
        section_value = (
            section_match.group(1)
            .strip()
            .lower()
        )
    else:
        section_value = ""

    return (
        grade_number,
        section_value,
        text.lower()
    )


# ============================================================
# Student Sorting
# ============================================================

def _student_sort_key(student):
    """
    ترتيب الطالب حسب الاسم ثم Student ID.
    """

    student_id, student_name = student

    return (
        str(student_name).lower(),
        str(student_id).lower()
    )


# ============================================================
# Report Text Generation
# ============================================================

def generate_report_text():
    """
    إنشاء التقرير الكامل بصيغة Kivy Markup.

    يرجع:
        report_text
    """

    data = _load_report_data()

    grades_students = data[
        "grades_students"
    ]

    student_names_by_id = data[
        "student_names_by_id"
    ]

    student_date_status = data[
        "student_date_status"
    ]

    absences_by_grade_section = data[
        "absences_by_grade_section"
    ]

    all_dates = data[
        "all_dates"
    ]

    # --------------------------------------------------------
    # Dates
    # --------------------------------------------------------

    sorted_dates = _sort_dates(
        all_dates
    )

    # الأحدث أولاً في شاشة التقرير
    report_dates = list(
        reversed(sorted_dates)
    )

    date_to_index = {}

    for index, date_value in enumerate(
        sorted_dates,
        start=1
    ):

        date_to_index[
            date_value
        ] = f"D{index}"

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    report_text = (
        "[color=FFA500]"
        "=== AMIR SYSTEM - Attendance Reports ==="
        "[/color]\n"
    )

    # --------------------------------------------------------
    # Absence Summary
    # --------------------------------------------------------

    report_text += (
        "\n[color=FFA500]"
        "=== Absences Summary "
        "Grouped by Grade & Section ==="
        "[/color]\n"
    )

    if not absences_by_grade_section:

        report_text += (
            "• No absences recorded.\n"
        )

    else:

        for grade_section in sorted(
            absences_by_grade_section.keys(),
            key=_grade_section_sort_key
        ):

            report_text += (
                f"\n[color=00FFFF]"
                f"=== "
                f"{_escape_markup(grade_section)}"
                f" ==="
                f"[/color]\n"
            )

            students_in_group = (
                absences_by_grade_section[
                    grade_section
                ]
            )

            sorted_absent_students = sorted(
                students_in_group.items(),
                key=lambda item: (
                    student_names_by_id.get(
                        item[0],
                        "Unknown Student"
                    ).lower(),
                    str(item[0]).lower()
                )
            )

            for student_id, absence_dates in (
                sorted_absent_students
            ):

                student_name = (
                    student_names_by_id.get(
                        student_id,
                        "Unknown Student"
                    )
                )

                # set يحتوي على أيام الغياب الفعلية
                count = len(absence_dates)

                plural = (
                    "absence"
                    if count == 1
                    else "absences"
                )

                report_text += (
                    f"• {_escape_markup(student_name)} "
                    f"(ID: {_escape_markup(student_id)}): "
                    f"{count} {plural}\n"
                )

    # --------------------------------------------------------
    # Symbols Legend
    # --------------------------------------------------------

    report_text += (
        "\n[color=FFA500]"
        "=== Symbols Legend ==="
        "[/color]\n"
    )

    report_text += (
        "[color=00FF00]IN[/color]=Check-In | "
        "[color=00FF00]OUT[/color]=Check-Out | "
        "[color=FF6666]AB[/color]=Absent | "
        "[color=FFFF00]LT[/color]=Late | "
        "[color=FF88FF]SK[/color]=Sick | "
        "[color=8888FF]EXM[/color]=Exam | "
        "[color=FFAA00]HD[/color]=Half-Day | "
        "[color=888888]EX[/color]=Other\n"
    )

    # --------------------------------------------------------
    # No Students
    # --------------------------------------------------------

    if not grades_students:

        report_text += (
            "\n[color=FF0000]"
            "No students registered in database."
            "[/color]\n"
        )

        return report_text

    # --------------------------------------------------------
    # Days Mapping
    # --------------------------------------------------------

    report_text += (
        "\n[color=FFA500]"
        "=== Days Mapping ==="
        "[/color]\n"
    )

    if report_dates:

        mapping_parts = []

        for date_value in report_dates:

            mapping_parts.append(
                f"{date_to_index[date_value]}"
                f"={_escape_markup(date_value)}"
            )

        report_text += (
            " | ".join(mapping_parts)
            + "\n"
        )

    else:

        report_text += (
            "• No dates recorded yet.\n"
        )

    # --------------------------------------------------------
    # Students by Grade + Section
    # --------------------------------------------------------

    for grade_section in sorted(
        grades_students.keys(),
        key=_grade_section_sort_key
    ):

        report_text += (
            f"\n[color=00FFFF]"
            f"=== "
            f"{_escape_markup(grade_section)}"
            f" ==="
            f"[/color]\n"
        )

        students = sorted(
            grades_students[grade_section],
            key=_student_sort_key
        )

        for student_id, student_name in students:

            safe_student_id = _escape_markup(
                student_id
            )

            safe_student_name = _escape_markup(
                student_name
            )

            # ------------------------------------------------
            # Student identity = Student ID.
            # Phone is intentionally NOT used.
            # ------------------------------------------------

            report_text += (
                f"• {safe_student_name} "
                f"(ID: {safe_student_id})"
            )

            if report_dates:

                paired_parts = []

                student_records = (
                    student_date_status.get(
                        student_id,
                        {}
                    )
                )

                for date_value in report_dates:

                    symbols = (
                        student_records.get(
                            date_value,
                            []
                        )
                    )

                    if symbols:

                        symbol_text = "+".join(
                            symbols
                        )

                        paired_parts.append(
                            f"["
                            f"{date_to_index[date_value]},"
                            f"{symbol_text}"
                            f"]"
                        )

                    else:

                        paired_parts.append(
                            f"["
                            f"{date_to_index[date_value]},"
                            f"--"
                            f"]"
                        )

                report_text += (
                    "\u00A0\u00A0→\u00A0\u00A0"
                    + "\u00A0\u00A0".join(
                        paired_parts
                    )
                )

            else:

                report_text += (
                    " [No records]"
                )

            report_text += "\n"

    return report_text


# ============================================================
# Screen Integration
# ============================================================

def load_reports(
    app,
    instance=None
):
    """
    Compatibility wrapper لشاشة AdminReportsScreen.

    يمكن استدعاؤها بواسطة:
        app.load_reports(...)
    """

    try:

        report_text = generate_report_text()

        if app is None:
            return report_text

        if not hasattr(app, "root"):
            return report_text

        try:

            admin_screen = app.root.get_screen(
                "admin_reports"
            )

        except Exception as e:

            logging.error(
                f"Admin reports screen not found: {e}"
            )

            return report_text

        if not hasattr(
            admin_screen,
            "report_label"
        ):

            logging.error(
                "Admin reports screen has no report_label."
            )

            return report_text

        admin_screen.report_label.text = (
            report_text
        )

        return report_text

    except Exception as e:

        logging.error(
            f"Could not display reports: {e}"
        )

        error_text = (
            "[color=FF0000]"
            "Report Error: "
            f"{_escape_markup(e)}"
            "[/color]"
        )

        try:

            if (
                app is not None
                and hasattr(app, "root")
            ):

                admin_screen = (
                    app.root.get_screen(
                        "admin_reports"
                    )
                )

                if hasattr(
                    admin_screen,
                    "report_label"
                ):

                    admin_screen.report_label.text = (
                        error_text
                    )

        except Exception:
            pass

        return error_text
