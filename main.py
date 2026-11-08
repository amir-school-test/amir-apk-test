"""
AMIR SYSTEM - Smart Attendance & Security
"""

import importlib
import logging
import os
import sys
import traceback

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import NoTransition, ScreenManager

logging.basicConfig(level=logging.INFO)

_APP_DIR = os.path.dirname(os.path.abspath(__file__))

if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def _describe_app_folder():
    lines = ["App folder: " + _APP_DIR]
    try:
        names = sorted(os.listdir(_APP_DIR))
        lines.append("Root: " + ", ".join(names)[:400])
        for folder in ("database", "services", "screens"):
            path = os.path.join(_APP_DIR, folder)
            if os.path.isdir(path):
                lines.append(
                    folder + "/: " + ", ".join(sorted(os.listdir(path)))
                )
            else:
                lines.append(folder + "/: MISSING")
    except Exception as exc:
        lines.append(f"(could not list files: {exc})")
    return "\n".join(lines)


# ============================================================
# IMPORTS
# ============================================================

IMPORT_ERROR = None

try:
    # استيراد مباشر لملفات المجلدات لضمان عملها على أندرويد
    from database.database import *
    from services.attendance_service import *
    from services.auth_service import *
    from services.backup_service import *
    from services.pdf_service import *
    from services.qr_scan_service import *
    from services.report_service import *
    from services.sms_service import *
    from services.storage_service import *
    from services.voice_service import *
    from services.auto_service import *

except Exception:
    IMPORT_ERROR = traceback.format_exc() + "\n" + _describe_app_folder()
    logging.error("Startup import failed:\n%s", IMPORT_ERROR)


# ============================================================
# SCREENS
# ============================================================
SCREENS = (
    ("main", "main_screen", "MainScreen"),
    ("admin_login", "admin_login_screen", "AdminLoginScreen"),
    ("admin_reports", "admin_reports_screen", "AdminReportsScreen"),
    ("admin_settings", "admin_settings_screen", "AdminSettingsScreen"),
    ("add_student", "add_student_screen", "AddStudentScreen"),
)

SCREEN_PACKAGES = ("screens", "ui", "views", "")

RESET_DELAY_SECONDS = 5
CAMERA_REOPEN_DELAY_SECONDS = 1.5

READY_NAME_TEXT = "Ready to Scan..."
READY_STATUS_TEXT = "Privacy Protected"
READY_STATUS_COLOR = (0.7, 0.8, 0.9, 1)
NAME_COLOR = (1, 1, 1, 1)
ERROR_COLOR = (0.9, 0.3, 0.3, 1)


def _load_screen_class(module_name, class_name):
    last_error = None
    for package in SCREEN_PACKAGES:
        full_name = f"{package}.{module_name}" if package else module_name
        try:
            module = importlib.import_module(full_name)
            return getattr(module, class_name)
        except ModuleNotFoundError as exc:
            if exc.name not in (full_name, package, module_name):
                raise
            last_error = exc
    raise ImportError(
        f"Screen file '{module_name}.py' was not found "
        f"(looked in: {', '.join(p or 'main folder' for p in SCREEN_PACKAGES)})."
    ) from last_error


class AmirApp(App):

    title = "AMIR SYSTEM"

    def build(self):
        self.admin_authenticated = False
        self._must_change_password = False
        self._password_popup = None
        self._reset_event = None
        self._continuous_scan = False

        if IMPORT_ERROR:
            return self._error_view(
                "Startup error (missing or damaged file)",
                IMPORT_ERROR
            )

        try:
            manager = ScreenManager(transition=NoTransition())
            for screen_name, module_name, class_name in SCREENS:
                screen_class = _load_screen_class(module_name, class_name)
                manager.add_widget(screen_class(name=screen_name))

            manager.current = "main"

            manager.get_screen("admin_reports").bind(
                on_enter=self._on_admin_reports_enter
            )
        except Exception:
            logging.exception("Screen creation failed.")
            return self._error_view(
                "Screen error",
                traceback.format_exc()
            )

        Window.bind(on_keyboard=self._on_keyboard)
        return manager

    def _error_view(self, title, details):
        layout = BoxLayout(orientation="vertical", padding=20, spacing=10)
        title_label = Label(
            text=title, font_size="18sp", bold=True,
            color=ERROR_COLOR, size_hint=(1, 0.15)
        )
        title_label.bind(size=title_label.setter("text_size"))
        details_label = Label(
            text=str(details)[-2600:], font_size="11sp",
            halign="left", valign="top", size_hint=(1, 0.85)
        )
        details_label.bind(size=details_label.setter("text_size"))
        layout.add_widget(title_label)
        layout.add_widget(details_label)
        return layout

    def on_start(self):
        if not IMPORT_ERROR:
            try:
                # استدعاء دالة التهيئة مباشرة
                init_sqlite_db()
                if not initialize_admin_password():
                    raise RuntimeError("Could not prepare the admin password.")
            except Exception:
                logging.exception("Database initialization failed.")
                self.root.clear_widgets()
                self.root.add_widget(self._error_view(
                    "Database error - attendance is NOT being recorded",
                    traceback.format_exc()
                ))
                return

        Clock.schedule_once(self._request_android_permissions, 1)

    def _request_android_permissions(self, dt):
        if IMPORT_ERROR:
            return
        try:
            from android.permissions import Permission, request_permissions
            request_permissions([
                Permission.SEND_SMS,
                Permission.WRITE_EXTERNAL_STORAGE,
            ])
            return
        except ImportError:
            pass
        except Exception:
            logging.exception("Permission request failed.")
        try:
            request_sms_permission()
        except Exception:
            logging.exception("SMS permission request failed.")

    def on_pause(self):
        return True

    def on_resume(self):
        pass

    def on_stop(self):
        if IMPORT_ERROR:
            return
        try:
            clear_pending_scans()
        except Exception:
            logging.exception("Could not clear pending scans.")
        try:
            shutdown_voice_service()
        except Exception:
            logging.exception("Could not shut down voice service.")

    def _on_keyboard(self, window, key, *args):
        if key != 27:
            return False
        manager = self.root
        current = getattr(manager, "current", None)
        if current == "main":
            return True
        if current in ("admin_login", "admin_reports"):
            self.admin_authenticated = False
            manager.current = "main"
            return True
        if current in ("admin_settings", "add_student"):
            manager.current = "admin_reports"
            return True
        return False

    def process_attendance(self, text):
        try:
            result = process_attendance(text)
        except Exception:
            logging.exception("Attendance processing crashed.")
            self._show_scan_result("System Error", "System Error", ERROR_COLOR)
            self._speak("error", "System error.")
            return None
        success, message, title, color = result
        self._show_scan_result(title, message, color)
        self._speak_for_result(result)
        Clock.schedule_once(lambda dt: self._send_sms(result), 0)
        return result

    def _send_sms(self, result):
        try:
            send_sms_for_attendance_result(result)
        except Exception:
            logging.exception("SMS dispatch failed.")

    def _get_screen(self, name):
        try:
            return self.root.get_screen(name)
        except Exception:
            return None

    def _show_scan_result(self, title, message, color):
        screen = self._get_screen("main")
        if screen is None:
            return
        try:
            screen.name_label.text = str(title)
            screen.name_label.color = NAME_COLOR
            screen.status_label.text = str(message)
            screen.status_label.color = color
            if self._reset_event is not None:
                self._reset_event.cancel()
            self._reset_event = Clock.schedule_once(self._reset_scan_result, RESET_DELAY_SECONDS)
        except Exception:
            logging.exception("Could not show scan result.")

    def _reset_scan_result(self, dt):
        self._reset_event = None
        screen = self._get_screen("main")
        if screen is None:
            return
        try:
            screen.name_label.text = READY_NAME_TEXT
            screen.name_label.color = NAME_COLOR
            screen.status_label.text = READY_STATUS_TEXT
            screen.status_label.color = READY_STATUS_COLOR
        except Exception:
            logging.exception("Could not reset scan result.")

    def _speak(self, kind, text):
        try:
            if kind == "error":
                speak_error(text)
            else:
                speak(text)
        except Exception:
            logging.exception("Voice feedback failed.")

    def _speak_for_result(self, result):
        success, message, title, color = result
        event = getattr(result, "event", None)
        student_id = getattr(result, "student_id", None)
        text = str(message)
        try:
            if event == "CHECK_IN":
                speak_check_in(student_id, status=text)
            elif event == "CHECK_OUT":
                speak_check_out(student_id)
            elif event == "EXAM_EXIT":
                speak_exam_exit(student_id)
            elif event == "SICK_EXIT":
                speak_sick_exit(student_id)
            elif event == "SCHOOL_APPROVED_EXIT":
                speak_school_approved_exit(student_id)
            elif event == "EARLY_EXIT_WARNING":
                speak_error("Warning. Early exit not authorized.")
            elif success:
                upper_text = text.upper()
                if upper_text.endswith(" ON") or upper_text.endswith(" OFF"):
                    speak(text.title())
            else:
                lower_text = text.lower()
                if "not registered" in lower_text:
                    speak_not_registered()
                elif "marked absent" in lower_text:
                    speak_error("Student marked absent.")
                elif "not active" in lower_text:
                    speak_error("Student not active.")
                elif "not checked in" in lower_text:
                    speak_error("Student has not checked in.")
                elif "invalid admin" in lower_text:
                    speak_error("Invalid admin card.")
                else:
                    speak_error("Error.")
        except Exception:
            logging.exception("Voice feedback failed.")

    def scan_with_camera(self, instance=None):
        if self.root is None or getattr(self.root, "current", None) != "main":
            return
        started, message = start_scan(
            self._on_camera_result, self._on_camera_status
        )
        if not started and message != "Scanner is already open.":
            self._set_continuous(False)
            self._show_scan_result("Camera", message, ERROR_COLOR)

    def toggle_continuous_scan(self, instance=None):
        self._set_continuous(not self._continuous_scan)
        if self._continuous_scan:
            self.scan_with_camera()

    def _set_continuous(self, enabled):
        self._continuous_scan = bool(enabled)
        screen = self._get_screen("main")
        if screen is not None:
            try:
                screen.set_continuous_text(self._continuous_scan)
            except Exception:
                logging.exception("Could not update the continuous button.")

    def _on_camera_result(self, text):
        text = str(text).strip()
        upper_text = text.upper()
        if (
            upper_text.startswith(STUDENT_QR_PREFIX)
            or upper_text.startswith(ADMIN_QR_PREFIX)
        ):
            self.process_attendance(text)
        else:
            self._show_scan_result(
                "Unknown QR", "This is not an AMIR QR code.", ERROR_COLOR
            )
            self._speak("error", "Unknown QR code.")
        if self._continuous_scan:
            Clock.schedule_once(
                lambda dt: self.scan_with_camera(), CAMERA_REOPEN_DELAY_SECONDS
            )

    def _on_camera_status(self, status):
        self._set_continuous(False)
        if status != "canceled":
            self._show_scan_result(
                "Camera", "Scanner error. Use the input box instead.", ERROR_COLOR
            )
            logging.error("Camera scanner status: %s", status)

    def verify_admin_password(self, entered_password):
        verified = bool(
            verify_admin_password(entered_password, self)
        )
        if verified:
            try:
                self._must_change_password = bool(
                    is_default_admin_password(entered_password)
                )
            except Exception:
                logging.exception("Default password check failed.")
        return verified

    def update_admin_password(self, new_password):
        updated, message = update_admin_password(new_password, self)
        if updated:
            self._must_change_password = False
            return True
        logging.warning("Admin password was not updated: %s", message)
        return False

    def _on_admin_reports_enter(self, screen):
        if not self._must_change_password:
            return
        if not self.admin_authenticated:
            return
        if self._password_popup is not None:
            return
        content = BoxLayout(orientation="vertical", padding=15, spacing=15)
        message = Label(
            text=(
                "The default admin password is still in use.\n\n"
                "Change it now before continuing."
            ),
            halign="center", valign="middle", font_size="15sp"
        )
        message.bind(size=message.setter("text_size"))
        change_btn = Button(
            text="Change Password Now", size_hint=(1, 0.35),
            background_normal="", background_color=(0.85, 0.3, 0.2, 1), bold=True
        )
        content.add_widget(message)
        content.add_widget(change_btn)
        popup = Popup(
            title="Security Warning", content=content,
            size_hint=(0.88, 0.42), auto_dismiss=False
        )
        self._password_popup = popup

        def go_to_settings(*args):
            popup.dismiss()
            if self.root is not None:
                self.root.current = "admin_settings"

        change_btn.bind(on_press=go_to_settings)
        popup.bind(on_dismiss=self._clear_password_popup)
        popup.open()

    def _clear_password_popup(self, *args):
        self._password_popup = None

    def load_reports(self, instance=None):
        return load_reports(self, instance)

    def mark_absent_for_missing_students(self, instance=None):
        screen = self._get_screen("admin_reports")
        try:
            count = mark_absent_for_missing_students()
        except Exception:
            logging.exception("Mark absent crashed.")
            count = None
        if screen is not None:
            if count is None:
                screen._show_simple_message(
                    "ABSENT", "ABSENT operation failed.\nNothing was saved."
                )
            elif count == 0:
                screen._show_simple_message(
                    "ABSENT", "No student was marked ABSENT.\n\n"
                    "Everyone already has a record today, or today is a weekend."
                )
            else:
                screen._show_simple_message(
                    "ABSENT", f"{count} student(s) were marked ABSENT.\n\n"
                    "You can now send SMS to their parents."
                )
        if count:
            self.load_reports(instance)
        return count

    def export_daily_report(self, instance=None):
        result = export_daily_report(self, instance)
        self._publish_to_downloads(result, "Reports", "application/pdf")
        return result

    def backup_database(self, instance=None):
        result = backup_database(self, instance)
        self._publish_to_downloads(result, "AMIR_Backups", "application/octet-stream")
        return result

    @staticmethod
    def _subfolder_from_path(path, root_name):
        parts = os.path.normpath(path).split(os.sep)
        if root_name in parts:
            index = len(parts) - 1 - parts[::-1].index(root_name)
            return "/".join(parts[index:-1])
        return root_name

    def _publish_to_downloads(self, result, root_name, mime_type):
        try:
            success, message, path = result
            if not success or not path:
                return
            subfolder = self._subfolder_from_path(path, root_name)
            copied, location = export_to_downloads(
                path, subfolder, mime_type
            )
            screen = self._get_screen("admin_reports")
            if screen is None:
                return
            if copied:
                screen._append_report_message(
                    "[color=00FF00]Saved in Downloads:[/color]\n" + f"{location}"
                )
            else:
                screen._append_report_message(
                    "[color=FFA500]Saved inside the app only "
                    "(could not copy to Downloads):[/color]\n" + f"{location}"
                )
        except Exception:
            logging.exception("Could not publish file to Downloads.")


if __name__ == "__main__":
    AmirApp().run()
