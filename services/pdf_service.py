import logging
import os
import sqlite3
import tempfile
from datetime import datetime

from database.database import get_db_path

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None


# ============================================================
# Configuration
# ============================================================

REPORTS_FOLDER_NAME = "Reports"

DOWNLOAD_DIRECTORY = (
    "/storage/emulated/0/Download"
)

PDF_FILENAME_PREFIX = "Daily_"

FONT_FOLDER_NAME = "fonts"

UNICODE_FONT_FILENAME = "DejaVuSans.ttf"

UNICODE_FONT_BOLD_FILENAME = (
    "DejaVuSans-Bold.ttf"
)


# ============================================================
# Date Utilities
# ============================================================

def _validate_report_date(report_date):
    """
    Validate and normalize:

        YYYY-MM-DD
    """

    if report_date is None:
        return datetime.now().strftime(
            "%Y-%m-%d"
        )

    report_date = str(
        report_date
    ).strip()

    try:

        parsed_date = datetime.strptime(
            report_date,
            "%Y-%m-%d"
        )

    except ValueError:

        raise ValueError(
            "Invalid report date. "
            "Expected YYYY-MM-DD."
        )

    return parsed_date.strftime(
        "%Y-%m-%d"
    )


# ============================================================
# Path Utilities
# ============================================================

def _get_project_font_directory():
    """
    Expected:

        AMIR SYSTEM/
        ├── fonts/
        │   ├── DejaVuSans.ttf
        │   └── DejaVuSans-Bold.ttf
        ├── services/
        └── ...
    """

    try:

        services_directory = os.path.dirname(
            os.path.abspath(__file__)
        )

        project_directory = os.path.dirname(
            services_directory
        )

        return os.path.join(
            project_directory,
            FONT_FOLDER_NAME
        )

    except Exception as e:

        logging.warning(
            "Could not determine project font "
            f"directory: {e}"
        )

        return None


def _get_unicode_font_paths():
    """
    Return available Unicode font paths.
    """

    font_directory = (
        _get_project_font_directory()
    )

    if not font_directory:
        return None, None

    regular_font = os.path.join(
        font_directory,
        UNICODE_FONT_FILENAME
    )

    bold_font = os.path.join(
        font_directory,
        UNICODE_FONT_BOLD_FILENAME
    )

    if not os.path.isfile(
        regular_font
    ):
        regular_font = None

    if not os.path.isfile(
        bold_font
    ):
        bold_font = None

    return (
        regular_font,
        bold_font
    )


def _get_reports_directory(
    report_date
):
    """
    Creates:

        Download/
            Reports/
                YEAR/
                    MONTH/

    Example:

        Reports/
            2026/
                September/
                    Daily_2026-09-20.pdf

    Falls back to the application's
    private storage if necessary.
    """

    report_date = _validate_report_date(
        report_date
    )

    parsed_date = datetime.strptime(
        report_date,
        "%Y-%m-%d"
    )

    year_name = parsed_date.strftime(
        "%Y"
    )

    month_name = parsed_date.strftime(
        "%B"
    )

    # --------------------------------------------------------
    # Primary Android Download directory
    # --------------------------------------------------------

    primary_directory = os.path.join(
        DOWNLOAD_DIRECTORY,
        REPORTS_FOLDER_NAME,
        year_name,
        month_name
    )

    try:

        os.makedirs(
            primary_directory,
            exist_ok=True
        )

        if (
            os.path.isdir(
                primary_directory
            )
            and os.access(
                primary_directory,
                os.W_OK
            )
        ):

            return primary_directory

    except Exception as e:

        logging.warning(
            "Could not use Android Reports "
            f"directory: {e}"
        )

    # --------------------------------------------------------
    # Application private directory
    # --------------------------------------------------------

    try:

        from kivy.app import App

        app = App.get_running_app()

        if app is not None:

            app_data_directory = getattr(
                app,
                "user_data_dir",
                None
            )

            if app_data_directory:

                fallback_directory = (
                    os.path.join(
                        app_data_directory,
                        REPORTS_FOLDER_NAME,
                        year_name,
                        month_name
                    )
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

        logging.warning(
            "Could not use application Reports "
            f"directory: {e}"
        )

    raise OSError(
        "No writable Reports directory is available."
    )


def _create_report_filename(
    report_date
):
    """
    Creates:

        Daily_YYYY-MM-DD.pdf
    """

    report_date = _validate_report_date(
        report_date
    )

    return (
        f"{PDF_FILENAME_PREFIX}"
        f"{report_date}.pdf"
    )


# ============================================================
# Student Information Utilities
# ============================================================

def _normalize_grade(grade):
    """
    Read Grade directly from database.

    Examples:

        12
        -> Grade 12

        Grade 12
        -> Grade 12
    """

    if grade is None:
        return "Other"

    grade = str(
        grade
    ).strip()

    if not grade:
        return "Other"

    if grade.lower().startswith(
        "grade "
    ):
        return grade

    if grade.isdigit():
        return f"Grade {grade}"

    return grade


def _normalize_section(section):
    """
    Read Section directly from database.
    """

    if section is None:
        return "Other"

    section = str(
        section
    ).strip()

    if not section:
        return "Other"

    return section


def _get_grade_section_text(
    grade,
    section
):
    """
    Creates a readable Grade + Section value.

    Example:

        Grade 12 - A
    """

    grade_text = _normalize_grade(
        grade
    )

    section_text = _normalize_section(
        section
    )

    return (
        f"{grade_text} - {section_text}"
    )


def _clean_student_name(
    student_name
):
    """
    Student name is kept exactly as stored.

    Grade is NOT extracted from the name.
    """

    if not student_name:
        return "Unknown"

    student_name = str(
        student_name
    ).strip()

    return (
        student_name
        if student_name
        else "Unknown"
    )


# ============================================================
# Attendance Status Utilities
# ============================================================

def _status_priority(status):
    """
    Higher number = more important status.
    """

    if not status:
        return 0

    status_upper = (
        str(status)
        .strip()
        .upper()
    )

    if "SICK" in status_upper:
        return 100

    if "EXAM" in status_upper:
        return 95

    if (
        "HALF-DAY" in status_upper
        or "HALFDAY" in status_upper
        or "HALF DAY" in status_upper
    ):
        return 90

    if "ABSENT (TOO LATE)" in status_upper:
        return 80

    if "ABSENT" in status_upper:
        return 75

    if "LATE" in status_upper:
        return 60

    if "EARLY-EXIT" in status_upper:
        return 55

    if "CHECKED OUT" in status_upper:
        return 50

    if "CHECKED IN" in status_upper:
        return 40

    return 10


def _display_status(
    record_type,
    status
):
    """
    Converts special attendance records
    into readable statuses.
    """

    record_type_upper = (
        str(record_type or "")
        .strip()
        .upper()
    )

    status_text = (
        str(status or "")
        .strip()
    )

    status_upper = status_text.upper()

    # --------------------------------------------------------
    # EXAM
    # --------------------------------------------------------

    if "EXAM" in record_type_upper:

        if "EXIT" in record_type_upper:

            return "Exam Exit"

        return "Exam"

    if "EXAM" in status_upper:

        if "EXIT" in status_upper:

            return "Exam Exit"

        return "Exam"

    # --------------------------------------------------------
    # SICK
    # --------------------------------------------------------

    if "SICK" in record_type_upper:

        if "EXIT" in record_type_upper:

            return "Sick Exit"

        return "Sick"

    if "SICK" in status_upper:

        if "EXIT" in status_upper:

            return "Sick Exit"

        return "Sick"

    # --------------------------------------------------------
    # HALF DAY
    # --------------------------------------------------------

    if (
        "HALF-DAY" in record_type_upper
        or "HALFDAY" in record_type_upper
        or "HALF DAY" in record_type_upper
    ):
        return "Half-Day"

    if (
        "HALF-DAY" in status_upper
        or "HALFDAY" in status_upper
        or "HALF DAY" in status_upper
    ):
        return "Half-Day"

    return status_text


# ============================================================
# Daily Student Summary
# ============================================================

def _update_student_summary(
    summary,
    student_id,
    student_name,
    grade,
    section,
    record_type,
    status,
    time_val
):
    """
    Add one attendance event to the student's
    daily summary.

    Important:

    - Earliest check-in is preserved.
    - Latest check-out is preserved.
    - Grade comes from database.
    - Section comes from database.
    - Phone is never used as identity.
    """

    if student_id not in summary:

        summary[student_id] = {
            "name": _clean_student_name(
                student_name
            ),
            "grade": _normalize_grade(
                grade
            ),
            "section": _normalize_section(
                section
            ),
            "check_in": "-",
            "check_out": "-",
            "status": "No Attendance Record"
        }

    record_type_upper = (
        str(record_type or "")
        .strip()
        .upper()
    )

    status_text = _display_status(
        record_type,
        status
    )

    status_upper = (
        str(status_text or "")
        .strip()
        .upper()
    )

    # --------------------------------------------------------
    # Check-In
    # --------------------------------------------------------

    is_check_in = (
        "CHECK-IN" in record_type_upper
        or "CHECK IN" in record_type_upper
        or record_type_upper == "PRESENT"
        or "CHECKED IN" in status_upper
    )

    if is_check_in:

        current_check_in = (
            summary[student_id][
                "check_in"
            ]
        )

        if current_check_in == "-":

            summary[student_id][
                "check_in"
            ] = (
                time_val or "-"
            )

        elif time_val:

            if (
                str(time_val)
                < str(current_check_in)
            ):

                summary[student_id][
                    "check_in"
                ] = time_val

    # --------------------------------------------------------
    # Check-Out
    # --------------------------------------------------------

    is_check_out = (
        "CHECK-OUT" in record_type_upper
        or "CHECK OUT" in record_type_upper
        or "EXIT" in record_type_upper
        or "CHECKED OUT" in status_upper
    )

    if is_check_out:

        current_check_out = (
            summary[student_id][
                "check_out"
            ]
        )

        if current_check_out == "-":

            summary[student_id][
                "check_out"
            ] = (
                time_val or "-"
            )

        elif time_val:

            if (
                str(time_val)
                > str(current_check_out)
            ):

                summary[student_id][
                    "check_out"
                ] = time_val

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    current_status = (
        summary[student_id][
            "status"
        ]
    )

    if (
        _status_priority(status_text)
        >= _status_priority(
            current_status
        )
    ):

        if status_text:

            summary[student_id][
                "status"
            ] = status_text


# ============================================================
# Database Reading
# ============================================================

def _load_daily_attendance(
    report_date
):
    """
    Reads attendance using the current
    AMIR database schema.

    Grade and Section are read directly
    from students.
    """

    report_date = _validate_report_date(
        report_date
    )

    database_path = get_db_path()

    if not os.path.exists(
        database_path
    ):

        raise FileNotFoundError(
            "AMIR database was not found."
        )

    connection = None

    try:

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

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                a.student_id,
                s.name,
                s.grade,
                s.section,
                a.time_val,
                a.record_type,
                a.status
            FROM attendance AS a
            LEFT JOIN students AS s
                ON s.student_id = a.student_id
            WHERE a.date_val = ?
              AND a.voided_at IS NULL
            ORDER BY
                a.time_val ASC,
                a.id ASC
            """,
            (
                report_date,
            )
        )

        return cursor.fetchall()

    finally:

        if connection is not None:

            try:
                connection.close()
            except Exception:
                pass


def _build_daily_summary(
    report_date
):
    """
    Converts raw attendance records
    into one row per student.
    """

    report_date = _validate_report_date(
        report_date
    )

    rows = _load_daily_attendance(
        report_date
    )

    summary = {}

    for row in rows:

        (
            student_id,
            student_name,
            grade,
            section,
            time_val,
            record_type,
            status
        ) = row

        student_id = str(
            student_id or ""
        ).strip()

        if not student_id:
            continue

        student_name = str(
            student_name or "Unknown"
        ).strip()

        _update_student_summary(
            summary=summary,
            student_id=student_id,
            student_name=student_name,
            grade=grade,
            section=section,
            record_type=record_type,
            status=status,
            time_val=time_val
        )

    return summary


# ============================================================
# PDF Text Utilities
# ============================================================

_UNICODE_FONT_ACTIVE = False


def _set_unicode_font_active(active):

    global _UNICODE_FONT_ACTIVE

    _UNICODE_FONT_ACTIVE = bool(active)


def _safe_pdf_text(value):
    """
    Safely convert a value to text.

    Without a Unicode font the built-in PDF fonts only support Latin-1.
    Other characters (Arabic, Amharic ...) become "?" instead of
    crashing the whole report.
    """

    if value is None:
        return ""

    text = str(value)

    if _UNICODE_FONT_ACTIVE:
        return text

    return text.encode("latin-1", "replace").decode("latin-1")


# ============================================================
# PDF Font Setup
# ============================================================

def _setup_fonts(pdf):
    """
    Register DejaVu Unicode fonts when available.

    Returns:

        True  -> Unicode font available
        False -> fallback to Arial
    """

    regular_font, bold_font = (
        _get_unicode_font_paths()
    )

    if not regular_font:

        logging.warning(
            "DejaVuSans.ttf was not found. "
            "Falling back to Arial."
        )

        return False

    try:

        # ----------------------------------------------------
        # Regular
        # ----------------------------------------------------

        try:

            pdf.add_font(
                "DejaVu",
                "",
                regular_font,
                uni=True
            )

        except TypeError:

            pdf.add_font(
                "DejaVu",
                "",
                regular_font
            )

        # ----------------------------------------------------
        # Bold
        # ----------------------------------------------------

        if bold_font:

            try:

                pdf.add_font(
                    "DejaVu",
                    "B",
                    bold_font,
                    uni=True
                )

            except TypeError:

                pdf.add_font(
                    "DejaVu",
                    "B",
                    bold_font
                )

        else:

            try:

                pdf.add_font(
                    "DejaVu",
                    "B",
                    regular_font,
                    uni=True
                )

            except TypeError:

                pdf.add_font(
                    "DejaVu",
                    "B",
                    regular_font
                )

        return True

    except Exception as e:

        logging.warning(
            f"Could not register Unicode fonts: {e}"
        )

        return False


# ============================================================
# PDF Table
# ============================================================

def _draw_table_header(
    pdf,
    font_name
):

    pdf.set_font(
        font_name,
        "B",
        8
    )

    pdf.cell(
        16,
        8,
        "ID",
        1,
        0,
        "C"
    )

    pdf.cell(
        48,
        8,
        "Student Name",
        1,
        0,
        "C"
    )

    pdf.cell(
        32,
        8,
        "Grade",
        1,
        0,
        "C"
    )

    pdf.cell(
        20,
        8,
        "Section",
        1,
        0,
        "C"
    )

    pdf.cell(
        23,
        8,
        "Check-In",
        1,
        0,
        "C"
    )

    pdf.cell(
        23,
        8,
        "Check-Out",
        1,
        0,
        "C"
    )

    pdf.cell(
        38,
        8,
        "Status",
        1,
        1,
        "C"
    )


def _fit_text(
    pdf,
    text,
    max_width
):
    """
    Fits text into the requested cell width.
    """

    text = _safe_pdf_text(
        text
    )

    if not text:
        return ""

    try:

        if (
            pdf.get_string_width(
                text
            )
            <= max_width
        ):
            return text

    except Exception:

        return text[:25]

    ellipsis = "..."

    try:

        ellipsis_width = (
            pdf.get_string_width(
                ellipsis
            )
        )

    except Exception:

        return (
            text[:20]
            + ellipsis
        )

    available_width = (
        max_width
        - ellipsis_width
    )

    if available_width <= 0:
        return ellipsis

    result = ""

    for character in text:

        candidate = (
            result
            + character
        )

        try:

            if (
                pdf.get_string_width(
                    candidate
                )
                > available_width
            ):
                break

        except Exception:

            break

        result = candidate

    return (
        result
        + ellipsis
    )


def _draw_table_row(
    pdf,
    student_id,
    data,
    font_name
):

    pdf.set_font(
        font_name,
        "",
        7
    )

    student_id_text = _fit_text(
        pdf,
        student_id,
        14
    )

    name_text = _fit_text(
        pdf,
        data.get(
            "name",
            "Unknown"
        ),
        46
    )

    grade_text = _fit_text(
        pdf,
        data.get(
            "grade",
            "Other"
        ),
        30
    )

    section_text = _fit_text(
        pdf,
        data.get(
            "section",
            "Other"
        ),
        18
    )

    check_in_text = _fit_text(
        pdf,
        data.get(
            "check_in",
            "-"
        ),
        21
    )

    check_out_text = _fit_text(
        pdf,
        data.get(
            "check_out",
            "-"
        ),
        21
    )

    status_text = _fit_text(
        pdf,
        data.get(
            "status",
            "-"
        ),
        36
    )

    pdf.cell(
        16,
        8,
        student_id_text,
        1,
        0,
        "C"
    )

    pdf.cell(
        48,
        8,
        name_text,
        1,
        0,
        "L"
    )

    pdf.cell(
        32,
        8,
        grade_text,
        1,
        0,
        "C"
    )

    pdf.cell(
        20,
        8,
        section_text,
        1,
        0,
        "C"
    )

    pdf.cell(
        23,
        8,
        check_in_text,
        1,
        0,
        "C"
    )

    pdf.cell(
        23,
        8,
        check_out_text,
        1,
        0,
        "C"
    )

    pdf.cell(
        38,
        8,
        status_text,
        1,
        1,
        "L"
    )


# ============================================================
# Temporary PDF
# ============================================================

def _create_temp_pdf_path(
    reports_directory
):
    """
    Create a temporary PDF file in the
    same directory as the final PDF.
    """

    file_descriptor = None
    temporary_path = None

    try:

        (
            file_descriptor,
            temporary_path
        ) = tempfile.mkstemp(
            prefix=".amir_tmp_",
            suffix=".pdf",
            dir=reports_directory
        )

        os.close(
            file_descriptor
        )

        return temporary_path

    except Exception:

        if file_descriptor is not None:

            try:
                os.close(
                    file_descriptor
                )
            except Exception:
                pass

        if (
            temporary_path
            and os.path.exists(
                temporary_path
            )
        ):

            try:
                os.remove(
                    temporary_path
                )
            except Exception:
                pass

        raise


# ============================================================
# PDF Creation
# ============================================================

def create_daily_report(
    report_date=None
):
    """
    Create one daily attendance PDF.

    Returns:

        (
            success,
            message,
            pdf_path
        )
    """

    if FPDF is None:

        logging.error(
            "FPDF is not installed."
        )

        return (
            False,
            "FPDF library is not installed.",
            None
        )

    try:

        report_date = _validate_report_date(
            report_date
        )

    except ValueError as e:

        return (
            False,
            str(e),
            None
        )

    temporary_path = None

    try:

        # ----------------------------------------------------
        # Load data
        # ----------------------------------------------------

        summary = _build_daily_summary(
            report_date
        )

        # ----------------------------------------------------
        # Reports directory
        # ----------------------------------------------------

        reports_directory = (
            _get_reports_directory(
                report_date
            )
        )

        filename = _create_report_filename(
            report_date
        )

        final_path = os.path.join(
            reports_directory,
            filename
        )

        # ----------------------------------------------------
        # Temporary PDF
        # ----------------------------------------------------

        temporary_path = (
            _create_temp_pdf_path(
                reports_directory
            )
        )

        # ----------------------------------------------------
        # Create PDF
        # ----------------------------------------------------

        pdf = FPDF(
            orientation="L",
            unit="mm",
            format="A4"
        )

        pdf.set_auto_page_break(
            auto=True,
            margin=12
        )

        pdf.add_page()

        # ----------------------------------------------------
        # Fonts
        # ----------------------------------------------------

        unicode_font_available = (
            _setup_fonts(pdf)
        )

        _set_unicode_font_active(unicode_font_available)

        font_name = (
            "DejaVu"
            if unicode_font_available
            else "Arial"
        )

        # ----------------------------------------------------
        # Metadata
        # ----------------------------------------------------

        pdf.set_title(
            "AMIR Daily Attendance Report - "
            f"{report_date}"
        )

        pdf.set_author(
            "AMIR SYSTEM"
        )

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        pdf.set_font(
            font_name,
            "B",
            15
        )

        pdf.cell(
            0,
            10,
            "AMIR SYSTEM - Daily Attendance Report",
            0,
            1,
            "C"
        )

        pdf.set_font(
            font_name,
            "",
            9
        )

        pdf.cell(
            0,
            6,
            f"Date: {report_date}",
            0,
            1,
            "C"
        )

        pdf.cell(
            0,
            6,
            "Generated: "
            + datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            0,
            1,
            "C"
        )

        pdf.ln(5)

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        pdf.set_font(
            font_name,
            "B",
            9
        )

        pdf.cell(
            0,
            6,
            "Students with attendance records: "
            + str(
                len(summary)
            ),
            0,
            1,
            "L"
        )

        pdf.ln(2)

        # ----------------------------------------------------
        # Table
        # ----------------------------------------------------

        _draw_table_header(
            pdf,
            font_name
        )

        if not summary:

            pdf.set_font(
                font_name,
                "",
                9
            )

            pdf.cell(
                200,
                10,
                "No attendance records found "
                "for this date.",
                1,
                1,
                "C"
            )

        else:

            sorted_students = sorted(
                summary.items(),
                key=lambda item: (
                    str(
                        item[1].get(
                            "grade",
                            ""
                        )
                    ).lower(),

                    str(
                        item[1].get(
                            "section",
                            ""
                        )
                    ).lower(),

                    str(
                        item[1].get(
                            "name",
                            ""
                        )
                    ).lower(),

                    str(item[0])
                )
            )

            for (
                student_id,
                data
            ) in sorted_students:

                # Leave room for table row.
                if (
                    pdf.get_y()
                    > pdf.h - 22
                ):

                    pdf.add_page()

                    _draw_table_header(
                        pdf,
                        font_name
                    )

                _draw_table_row(
                    pdf,
                    student_id,
                    data,
                    font_name
                )

        # ----------------------------------------------------
        # Legend
        # ----------------------------------------------------

        if (
            pdf.get_y()
            > pdf.h - 30
        ):

            pdf.add_page()

        pdf.ln(5)

        pdf.set_font(
            font_name,
            "",
            7
        )

        legend = (
            "Status examples: "
            "Checked In, Checked Out, "
            "ABSENT, "
            "Late, Sick, Sick Exit, "
            "Exam, Exam Exit, Half-Day."
        )

        pdf.multi_cell(
            0,
            4,
            legend
        )

        # ----------------------------------------------------
        # Write temporary PDF
        # ----------------------------------------------------

        pdf.output(
            temporary_path
        )

        # ----------------------------------------------------
        # Verify temporary PDF
        # ----------------------------------------------------

        if not os.path.exists(
            temporary_path
        ):

            return (
                False,
                "Temporary PDF file was not created.",
                None
            )

        temporary_size = (
            os.path.getsize(
                temporary_path
            )
        )

        if temporary_size <= 0:

            return (
                False,
                "Temporary PDF file is empty.",
                None
            )

        # ----------------------------------------------------
        # Finalize
        # ----------------------------------------------------

        os.replace(
            temporary_path,
            final_path
        )

        temporary_path = None

        # ----------------------------------------------------
        # Final Verification
        # ----------------------------------------------------

        if not os.path.exists(
            final_path
        ):

            return (
                False,
                "PDF file was not created.",
                None
            )

        final_size = (
            os.path.getsize(
                final_path
            )
        )

        if final_size <= 0:

            try:
                os.remove(
                    final_path
                )
            except Exception:
                pass

            return (
                False,
                "PDF file is empty.",
                None
            )

        logging.info(
            "Daily PDF report created successfully: "
            f"{final_path}"
        )

        return (
            True,
            "Daily PDF report created successfully.",
            final_path
        )

    except sqlite3.Error as e:

        logging.error(
            f"SQLite error while creating PDF: {e}",
            exc_info=True
        )

        return (
            False,
            f"Database error while creating PDF: {e}",
            None
        )

    except Exception as e:

        logging.error(
            f"PDF creation error: {e}",
            exc_info=True
        )

        return (
            False,
            f"PDF creation error: {e}",
            None
        )

    finally:

        if (
            temporary_path
            and os.path.exists(
                temporary_path
            )
        ):

            try:

                os.remove(
                    temporary_path
                )

            except Exception:

                logging.warning(
                    "Could not remove temporary PDF: "
                    f"{temporary_path}"
                )


# ============================================================
# Kivy Compatibility Wrapper
# ============================================================

def export_daily_report(
    app,
    instance=None
):
    """
    Compatibility wrapper.

    Existing call remains:

        export_daily_report(
            app,
            instance
        )
    """

    try:

        (
            success,
            message,
            pdf_path
        ) = create_daily_report()

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
                                pdf_path
                            )
                        )

                        admin_screen.report_label.text += (
                            "\n\n"
                            "[color=00FF00]"
                            "PDF Report Saved Successfully"
                            "[/color]\n"
                            f"File: {filename}"
                        )

                    else:

                        admin_screen.report_label.text += (
                            "\n\n"
                            "[color=FF0000]"
                            "PDF Export Error: "
                            f"{message}"
                            "[/color]"
                        )

            except Exception as e:

                logging.error(
                    "Could not display PDF result: "
                    f"{e}"
                )

        return (
            success,
            message,
            pdf_path
        )

    except Exception as e:

        logging.error(
            f"PDF export wrapper error: {e}",
            exc_info=True
        )

        return (
            False,
            f"PDF export error: {e}",
            None
        )
