import logging

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from services.sms_service import (
    send_absent_sms_for_today,
    get_students_without_sms,
    retry_missing_sms
)


class AdminReportsScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=8
        )

        # =================================================
        # TITLE
        # =================================================

        layout.add_widget(
            Label(
                text="Confidential Detailed Reports",
                font_size="16sp",
                bold=True,
                size_hint=(1, 0.06),
                color=(1, 0.85, 0.6, 1)
            )
        )

        # =================================================
        # REPORT AREA
        # =================================================

        self.scroll_view = ScrollView(
            size_hint=(1, 0.30),
            do_scroll_x=True,
            do_scroll_y=True
        )

        self.report_grid = GridLayout(
            cols=1,
            size_hint_x=None,
            size_hint_y=None,
            width=1400
        )

        self.report_grid.bind(
            minimum_height=self.report_grid.setter("height")
        )

        self.report_label = Label(
            text="Loading reports...",
            font_size="14sp",
            halign="left",
            valign="top",
            size_hint_x=None,
            size_hint_y=None,
            width=1400,
            height=800,
            markup=True,
            color=(1, 1, 1, 1)
        )

        self.report_label.bind(
            texture_size=self._update_label_size
        )

        self.report_grid.add_widget(
            self.report_label
        )

        self.scroll_view.add_widget(
            self.report_grid
        )

        layout.add_widget(
            self.scroll_view
        )

        # =================================================
        # ABSENT
        # =================================================

        absent_btn = Button(
            text="ABSENT",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.85, 0.4, 0.1, 1),
            bold=True
        )

        absent_btn.bind(
            on_press=self.open_absent_menu
        )

        layout.add_widget(absent_btn)

        # =================================================
        # EXPORT DAILY PDF
        # =================================================

        export_btn = Button(
            text="Export Daily Report (PDF)",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.2, 0.65, 0.45, 1),
            bold=True
        )

        export_btn.bind(
            on_press=self.export_daily_report
        )

        layout.add_widget(export_btn)

        # =================================================
        # MONTHLY REPORT ARCHIVE
        # =================================================

        archive_btn = Button(
            text="Monthly Reports / Report Archive",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.35, 0.55, 0.8, 1),
            bold=True
        )

        archive_btn.bind(
            on_press=self.open_report_archive
        )

        layout.add_widget(archive_btn)

        # =================================================
        # MANAGE STUDENTS
        # =================================================

        manage_students_btn = Button(
            text="Manage Students (Add / Edit / Delete)",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.55, 0.2, 0.75, 1),
            bold=True
        )

        manage_students_btn.bind(
            on_press=self.open_student_management
        )

        layout.add_widget(manage_students_btn)

        # =================================================
        # BACKUP DATABASE
        # =================================================

        backup_btn = Button(
            text="Backup Database (SQLite)",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.15, 0.5, 0.65, 1),
            bold=True
        )

        backup_btn.bind(
            on_press=self.backup_database
        )

        layout.add_widget(backup_btn)

        # =================================================
        # CHANGE ADMIN PASSWORD
        # =================================================

        settings_btn = Button(
            text="Change Admin Password",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.2, 0.5, 0.8, 1),
            bold=True
        )

        settings_btn.bind(
            on_press=self.open_admin_settings
        )

        layout.add_widget(settings_btn)

        # =================================================
        # REFRESH
        # =================================================

        refresh_btn = Button(
            text="Refresh Data",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.25, 0.25, 0.75, 1),
            bold=True
        )

        refresh_btn.bind(
            on_press=self.refresh_reports
        )

        layout.add_widget(refresh_btn)

        # =================================================
        # LOGOUT
        # =================================================

        back_btn = Button(
            text="Logout / Back",
            size_hint=(1, 0.06),
            background_normal="",
            background_color=(0.75, 0.25, 0.25, 1),
            bold=True
        )

        back_btn.bind(
            on_press=self.logout
        )

        layout.add_widget(back_btn)

        self.add_widget(layout)

    # =====================================================
    # REPORT LABEL SIZE
    # =====================================================

    def _update_label_size(self, label, size):

        try:

            label.height = max(
                size[1],
                800
            )

            label.text_size = (
                label.width,
                None
            )

        except Exception as e:

            logging.error(
                f"Report label sizing error: {e}"
            )

    # =====================================================
    # ADMIN SESSION CHECK
    # =====================================================

    def _is_admin_authenticated(self):

        try:

            app = App.get_running_app()

            return bool(
                getattr(
                    app,
                    "admin_authenticated",
                    False
                )
            )

        except Exception as e:

            logging.error(
                f"Admin authentication check error: {e}"
            )

            return False

    # =====================================================
    # GO TO LOGIN
    # =====================================================

    def _require_admin_authentication(self):

        if self._is_admin_authenticated():
            return True

        if self.manager:
            self.manager.current = "admin_login"

        return False

    # =====================================================
    # SCREEN ENTER
    # =====================================================

    def on_enter(self, *args):

        try:

            if not self._require_admin_authentication():
                return

            Clock.schedule_once(
                self.refresh_reports,
                0
            )

        except Exception as e:

            logging.error(
                f"Admin reports on_enter error: {e}"
            )

    # =====================================================
    # SCREEN LEAVE
    # =====================================================

    def on_leave(self, *args):

        try:

            # Confidential report data should not remain
            # visible when leaving this screen.
            self.report_label.text = (
                "Loading reports..."
            )

        except Exception as e:

            logging.error(
                f"Admin reports on_leave error: {e}"
            )

    # =====================================================
    # REFRESH REPORTS
    # =====================================================

    def refresh_reports(self, instance=None):

        try:

            if not self._require_admin_authentication():
                return

            app = App.get_running_app()

            if not hasattr(
                app,
                "load_reports"
            ):

                logging.error(
                    "App.load_reports is not available."
                )

                self.report_label.text = (
                    "[color=FF0000]"
                    "Report service is unavailable."
                    "[/color]"
                )

                return

            app.load_reports(instance)

        except Exception as e:

            logging.error(
                f"Refresh reports error: {e}"
            )

            self.report_label.text = (
                "[color=FF0000]"
                "Unable to load reports."
                "[/color]"
            )

    # =====================================================
    # ABSENT MENU
    # =====================================================

    def open_absent_menu(self, instance):

        if not self._require_admin_authentication():
            return

        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=12
        )

        title = Label(
            text=(
                "Choose an ABSENT action:"
            ),
            font_size="15sp",
            bold=True,
            size_hint=(1, 0.14),
            halign="center",
            valign="middle"
        )

        title.bind(
            size=title.setter("text_size")
        )

        content.add_widget(title)

        # -------------------------------------------------
        # MARK ABSENT
        # -------------------------------------------------

        mark_btn = Button(
            text="Mark Students as ABSENT",
            size_hint=(1, 0.20),
            background_normal="",
            background_color=(0.85, 0.3, 0.2, 1),
            bold=True
        )

        content.add_widget(mark_btn)

        # -------------------------------------------------
        # SEND SMS
        # -------------------------------------------------

        sms_btn = Button(
            text="Send SMS to Parents",
            size_hint=(1, 0.20),
            background_normal="",
            background_color=(0.15, 0.55, 0.75, 1),
            bold=True
        )

        content.add_widget(sms_btn)

        # -------------------------------------------------
        # SMS PROBLEMS / RETRY
        # -------------------------------------------------

        problems_btn = Button(
            text="Students Without SMS / Retry",
            size_hint=(1, 0.20),
            background_normal="",
            background_color=(0.55, 0.4, 0.15, 1),
            bold=True
        )

        content.add_widget(problems_btn)

        # -------------------------------------------------
        # CANCEL
        # -------------------------------------------------

        cancel_btn = Button(
            text="Cancel",
            size_hint=(1, 0.16),
            background_normal="",
            background_color=(0.5, 0.5, 0.5, 1),
            bold=True
        )

        content.add_widget(cancel_btn)

        popup = Popup(
            title="ABSENT",
            content=content,
            size_hint=(0.88, 0.68),
            auto_dismiss=False
        )

        cancel_btn.bind(
            on_press=popup.dismiss
        )

        mark_btn.bind(
            on_press=lambda btn:
                self.confirm_mark_absent(
                    popup,
                    btn
                )
        )

        sms_btn.bind(
            on_press=lambda btn:
                self.confirm_send_absent_sms(
                    popup,
                    btn
                )
        )

        problems_btn.bind(
            on_press=lambda btn:
                self.open_sms_problems(
                    popup,
                    btn
                )
        )

        popup.open()

    # =====================================================
    # MARK ABSENT CONFIRMATION
    # =====================================================

    def confirm_mark_absent(
        self,
        menu_popup=None,
        instance=None
    ):

        if not self._require_admin_authentication():
            return

        if menu_popup is not None:
            menu_popup.dismiss()

        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=15
        )

        message = Label(
            text=(
                "This will mark all students who have "
                "no attendance record today as ABSENT.\n\n"
                "Do you want to continue?"
            ),
            halign="center",
            valign="middle",
            font_size="15sp"
        )

        message.bind(
            size=message.setter("text_size")
        )

        content.add_widget(message)

        buttons = BoxLayout(
            orientation="horizontal",
            spacing=10,
            size_hint=(1, 0.35)
        )

        cancel_btn = Button(
            text="Cancel",
            background_normal="",
            background_color=(0.5, 0.5, 0.5, 1),
            bold=True
        )

        confirm_btn = Button(
            text="Confirm",
            background_normal="",
            background_color=(0.85, 0.3, 0.2, 1),
            bold=True
        )

        buttons.add_widget(cancel_btn)
        buttons.add_widget(confirm_btn)

        content.add_widget(buttons)

        popup = Popup(
            title="Confirm ABSENT Action",
            content=content,
            size_hint=(0.88, 0.45),
            auto_dismiss=False
        )

        cancel_btn.bind(
            on_press=popup.dismiss
        )

        confirm_btn.bind(
            on_press=lambda btn:
                self._execute_mark_absent(
                    popup,
                    btn
                )
        )

        popup.open()

    # =====================================================
    # EXECUTE MARK ABSENT
    # =====================================================

    def _execute_mark_absent(
        self,
        popup,
        instance
    ):

        popup.dismiss()

        try:

            if not self._require_admin_authentication():
                return

            app = App.get_running_app()

            if not hasattr(
                app,
                "mark_absent_for_missing_students"
            ):

                logging.error(
                    "Absent service is unavailable."
                )

                self._append_report_message(
                    "[color=FF0000]"
                    "Absent service is unavailable."
                    "[/color]"
                )

                return

            app.mark_absent_for_missing_students(
                instance
            )

        except Exception as e:

            logging.error(
                f"Mark absent screen error: {e}"
            )

            self._append_report_message(
                "[color=FF0000]"
                "ABSENT operation failed."
                "[/color]"
            )

    # =====================================================
    # SEND ABSENT SMS CONFIRMATION
    # =====================================================

    def confirm_send_absent_sms(
        self,
        menu_popup=None,
        instance=None
    ):

        if not self._require_admin_authentication():
            return

        if menu_popup is not None:
            menu_popup.dismiss()

        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=15
        )

        message = Label(
            text=(
                "Send an absence SMS to the parents "
                "of students already marked ABSENT today?\n\n"
                "This action will NOT mark any new "
                "student as ABSENT."
            ),
            halign="center",
            valign="middle",
            font_size="14sp"
        )

        message.bind(
            size=message.setter("text_size")
        )

        content.add_widget(message)

        buttons = BoxLayout(
            orientation="horizontal",
            spacing=10,
            size_hint=(1, 0.35)
        )

        cancel_btn = Button(
            text="Cancel",
            background_normal="",
            background_color=(0.5, 0.5, 0.5, 1),
            bold=True
        )

        send_btn = Button(
            text="Send SMS",
            background_normal="",
            background_color=(0.15, 0.55, 0.75, 1),
            bold=True
        )

        buttons.add_widget(cancel_btn)
        buttons.add_widget(send_btn)

        content.add_widget(buttons)

        popup = Popup(
            title="Confirm Absent SMS",
            content=content,
            size_hint=(0.90, 0.52),
            auto_dismiss=False
        )

        cancel_btn.bind(
            on_press=popup.dismiss
        )

        send_btn.bind(
            on_press=lambda btn:
                self._execute_send_absent_sms(
                    popup,
                    btn
                )
        )

        popup.open()

    # =====================================================
    # EXECUTE ABSENT SMS
    # =====================================================

    def _execute_send_absent_sms(
        self,
        popup,
        instance
    ):

        popup.dismiss()

        try:

            if not self._require_admin_authentication():
                return

            result = send_absent_sms_for_today()

            self._show_absent_sms_result(
                result
            )

        except Exception as e:

            logging.error(
                f"Absent SMS screen error: {e}"
            )

            self._show_simple_message(
                "Absent SMS",
                "Unable to send absent SMS."
            )

    # =====================================================
    # STUDENTS WITHOUT SMS (problems + retry)
    # =====================================================

    def open_sms_problems(self, menu_popup=None, instance=None):

        if not self._require_admin_authentication():
            return

        if menu_popup is not None:
            menu_popup.dismiss()

        try:

            problems = get_students_without_sms()

        except Exception:

            logging.exception(
                "Could not load students without SMS."
            )

            self._show_simple_message(
                "SMS Problems",
                "Unable to load the list."
            )

            return

        content = BoxLayout(
            orientation="vertical",
            padding=12,
            spacing=10
        )

        if not problems:

            ok_label = Label(
                text=(
                    "Every notification of today was "
                    "accepted by the phone.\n\n"
                    "Accepted means Android took the request. "
                    "It does not prove the parent received it."
                ),
                halign="center",
                valign="middle",
                font_size="14sp"
            )

            ok_label.bind(
                size=ok_label.setter("text_size")
            )

            content.add_widget(ok_label)

        else:

            header = Label(
                text=(
                    f"{len(problems)} notification(s) "
                    "without SMS today"
                ),
                font_size="15sp",
                bold=True,
                size_hint=(1, None),
                height=34
            )

            content.add_widget(header)

            scroll = ScrollView(
                size_hint=(1, 1),
                do_scroll_x=False,
                do_scroll_y=True
            )

            grid = GridLayout(
                cols=1,
                spacing=10,
                size_hint_y=None
            )

            grid.bind(
                minimum_height=grid.setter("height")
            )

            for item in problems:

                row_text = (
                    f"{item['name']}  -  "
                    f"{item['event_label']} "
                    f"({str(item['time_val'])[:5]})\n"
                    f"{item['suggestion']}"
                )

                row = Label(
                    text=row_text,
                    font_size="13sp",
                    halign="left",
                    valign="top",
                    size_hint_y=None
                )

                row.bind(
                    width=lambda inst, w:
                        setattr(
                            inst,
                            "text_size",
                            (w, None)
                        )
                )

                row.bind(
                    texture_size=lambda inst, size:
                        setattr(
                            inst,
                            "height",
                            size[1] + 8
                        )
                )

                grid.add_widget(row)

            scroll.add_widget(grid)
            content.add_widget(scroll)

        buttons = BoxLayout(
            orientation="horizontal",
            spacing=10,
            size_hint=(1, None),
            height=50
        )

        close_btn = Button(
            text="Close",
            background_normal="",
            background_color=(0.5, 0.5, 0.5, 1),
            bold=True
        )

        buttons.add_widget(close_btn)

        retry_btn = None

        if problems:

            retry_btn = Button(
                text="Retry",
                background_normal="",
                background_color=(0.15, 0.55, 0.75, 1),
                bold=True
            )

            buttons.add_widget(retry_btn)

        content.add_widget(buttons)

        popup = Popup(
            title="Students Without SMS",
            content=content,
            size_hint=(0.94, 0.85),
            auto_dismiss=False
        )

        close_btn.bind(
            on_press=popup.dismiss
        )

        if retry_btn is not None:

            retry_btn.bind(
                on_press=lambda btn:
                    self._execute_retry_sms(
                        popup
                    )
            )

        popup.open()

    def _execute_retry_sms(self, popup):

        popup.dismiss()

        try:

            if not self._require_admin_authentication():
                return

            summary = retry_missing_sms()

        except Exception:

            logging.exception(
                "Retry SMS failed."
            )

            self._show_simple_message(
                "Retry SMS",
                "Unable to retry the SMS."
            )

            return

        self._show_simple_message(
            "Retry SMS Result",
            (
                "Retry finished.\n\n"
                f"Without SMS: {summary.get('total', 0)}\n"
                f"Accepted now: {summary.get('sent', 0)}\n"
                f"Failed again: {summary.get('failed', 0)}\n"
                f"Need a phone number fix: "
                f"{summary.get('needs_phone_fix', 0)}\n\n"
                "Accepted means Android accepted "
                "the request for sending."
            )
        )

    # =====================================================
    # ABSENT SMS RESULT
    # =====================================================

    def _show_absent_sms_result(self, result):

        total = int(
            result.get("total", 0)
        )

        sent = int(
            result.get("sent", 0)
        )

        failed = int(
            result.get("failed", 0)
        )

        no_phone = int(
            result.get("no_phone", 0)
        )

        already_sent = int(
            result.get("already_sent", 0)
        )

        if total == 0:

            message_text = (
                "No students have been marked "
                "ABSENT today."
            )

        else:

            message_text = (
                "Absent SMS operation completed.\n\n"
                f"Total absent: {total}\n"
                f"SMS accepted: {sent}\n"
                f"Failed: {failed}\n"
                f"No phone number: {no_phone}\n"
                f"Already sent earlier today: {already_sent}\n\n"
                "SMS accepted means Android accepted "
                "the request for sending."
            )

        self._show_simple_message(
            "Absent SMS Result",
            message_text
        )

    # =====================================================
    # SIMPLE INFORMATION POPUP
    # =====================================================

    def _show_simple_message(
        self,
        title,
        message_text
    ):

        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=15
        )

        message = Label(
            text=message_text,
            halign="center",
            valign="middle",
            font_size="14sp"
        )

        message.bind(
            size=message.setter("text_size")
        )

        close_btn = Button(
            text="OK",
            size_hint=(1, 0.25),
            background_normal="",
            background_color=(0.2, 0.5, 0.8, 1),
            bold=True
        )

        content.add_widget(message)
        content.add_widget(close_btn)

        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.90, 0.55),
            auto_dismiss=True
        )

        close_btn.bind(
            on_press=popup.dismiss
        )

        popup.open()

    # =====================================================
    # EXPORT DAILY PDF
    # =====================================================

    def export_daily_report(self, instance):

        try:

            if not self._require_admin_authentication():
                return

            app = App.get_running_app()

            if not hasattr(
                app,
                "export_daily_report"
            ):

                logging.error(
                    "PDF export service is unavailable."
                )

                self._append_report_message(
                    "[color=FF0000]"
                    "PDF export service is unavailable."
                    "[/color]"
                )

                return

            app.export_daily_report(
                instance
            )

        except Exception as e:

            logging.error(
                f"PDF export screen error: {e}"
            )

            self._append_report_message(
                "[color=FF0000]"
                "PDF export failed."
                "[/color]"
            )

    # =====================================================
    # MONTHLY REPORT ARCHIVE
    # =====================================================

    def open_report_archive(self, instance):

        try:

            if not self._require_admin_authentication():
                return

            app = App.get_running_app()

            if hasattr(
                app,
                "open_report_archive"
            ):

                app.open_report_archive(
                    instance
                )

                return

            # Safe fallback.
            # The actual archive navigation can be connected
            # during final integration.

            self._show_archive_info()

        except Exception as e:

            logging.error(
                f"Report archive navigation error: {e}"
            )

            self._append_report_message(
                "[color=FF0000]"
                "Report archive is unavailable."
                "[/color]"
            )

    # =====================================================
    # ARCHIVE INFORMATION
    # =====================================================

    def _show_archive_info(self):

        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=15
        )

        message = Label(
            text=(
                "Monthly Report Archive\n\n"
                "Daily reports are organized by year "
                "and month.\n\n"
                "Example:\n"
                "Reports / 2026 / September /\n"
                "Daily_2026-09-01.pdf\n"
                "Daily_2026-09-02.pdf"
            ),
            halign="center",
            valign="middle",
            font_size="14sp"
        )

        message.bind(
            size=message.setter("text_size")
        )

        close_btn = Button(
            text="OK",
            size_hint=(1, 0.3),
            background_normal="",
            background_color=(0.2, 0.5, 0.8, 1),
            bold=True
        )

        content.add_widget(message)
        content.add_widget(close_btn)

        popup = Popup(
            title="Monthly Reports",
            content=content,
            size_hint=(0.88, 0.55),
            auto_dismiss=True
        )

        close_btn.bind(
            on_press=popup.dismiss
        )

        popup.open()

    # =====================================================
    # MANAGE STUDENTS
    # =====================================================

    def open_student_management(self, instance):

        try:

            if not self._require_admin_authentication():
                return

            if self.manager:
                self.manager.current = "add_student"

        except Exception as e:

            logging.error(
                f"Student management navigation error: {e}"
            )

    # =====================================================
    # DATABASE BACKUP
    # =====================================================

    def backup_database(self, instance):

        try:

            if not self._require_admin_authentication():
                return

            app = App.get_running_app()

            if not hasattr(
                app,
                "backup_database"
            ):

                logging.error(
                    "Backup service is unavailable."
                )

                self._append_report_message(
                    "[color=FF0000]"
                    "Backup service is unavailable."
                    "[/color]"
                )

                return

            app.backup_database(
                instance
            )

        except Exception as e:

            logging.error(
                f"Database backup screen error: {e}"
            )

            self._append_report_message(
                "[color=FF0000]"
                "Database backup failed."
                "[/color]"
            )

    # =====================================================
    # ADMIN SETTINGS
    # =====================================================

    def open_admin_settings(self, instance):

        try:

            if not self._require_admin_authentication():
                return

            if self.manager:
                self.manager.current = "admin_settings"

        except Exception as e:

            logging.error(
                f"Admin settings navigation error: {e}"
            )

    # =====================================================
    # LOGOUT
    # =====================================================

    def logout(self, instance):

        try:

            app = App.get_running_app()

            # Remove confidential report information.
            self.report_label.text = (
                "Loading reports..."
            )

            # Destroy current admin session.
            app.admin_authenticated = False

            if self.manager:
                self.manager.current = "main"

        except Exception as e:

            logging.error(
                f"Admin logout error: {e}"
            )

            try:

                app.admin_authenticated = False

                if self.manager:
                    self.manager.current = "main"

            except Exception:
                pass

    # =====================================================
    # REPORT MESSAGE HELPER
    # =====================================================

    def _append_report_message(self, message):

        try:

            current_text = (
                self.report_label.text or ""
            )

            self.report_label.text = (
                current_text
                + "\n\n"
                + message
            )

        except Exception as e:

            logging.error(
                f"Report message update error: {e}"
          )
