import logging

from kivy.app import App
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.clock import Clock

from services.auto_service import (
    check_auto_trigger,
    clear_pending_scans
)
from services.attendance_service import (
    STUDENT_QR_PREFIX,
    ADMIN_QR_PREFIX
)


class MainScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        layout = BoxLayout(
            orientation="vertical",
            padding=20,
            spacing=15
        )

        # =================================================
        # AMIR SYSTEM BANNER
        # =================================================

        banner_layout = BoxLayout(
            orientation="vertical",
            size_hint=(1, 0.28),
            padding=10
        )

        with banner_layout.canvas:

            Color(
                0.05,
                0.08,
                0.14,
                1
            )

            self.bg_rect = RoundedRectangle(
                size=banner_layout.size,
                pos=banner_layout.pos,
                radius=[20]
            )

            Color(
                0.95,
                0.55,
                0.15,
                0.3
            )

            self.border_line = Line(
                rounded_rectangle=(
                    banner_layout.x,
                    banner_layout.y,
                    banner_layout.width,
                    banner_layout.height,
                    20
                ),
                width=1.5
            )

        banner_layout.bind(
            pos=self.update_canvas,
            size=self.update_canvas
        )

        title_1 = Label(
            text="AMIR",
            font_size="38sp",
            bold=True,
            color=(1, 0.85, 0.6, 1),
            halign="center",
            valign="middle"
        )

        title_1.bind(
            size=title_1.setter("text_size")
        )

        banner_layout.add_widget(title_1)

        title_2 = Label(
            text="SYSTEM",
            font_size="38sp",
            bold=True,
            color=(1, 0.85, 0.6, 1),
            halign="center",
            valign="middle"
        )

        title_2.bind(
            size=title_2.setter("text_size")
        )

        banner_layout.add_widget(title_2)

        subtitle = Label(
            text="Smart Attendance & Security",
            font_size="12sp",
            color=(0.7, 0.8, 0.9, 1),
            halign="center",
            valign="middle"
        )

        subtitle.bind(
            size=subtitle.setter("text_size")
        )

        banner_layout.add_widget(subtitle)

        layout.add_widget(
            banner_layout
        )

        # =================================================
        # RESULT AREA
        # =================================================

        result_container = BoxLayout(
            orientation="vertical",
            size_hint=(1, 0.18),
            spacing=4
        )

        self.name_label = Label(
            text="Ready to Scan...",
            font_size="16sp",
            bold=True,
            halign="center",
            valign="middle",
            color=(1, 1, 1, 1)
        )

        self.name_label.bind(
            size=self.name_label.setter("text_size")
        )

        result_container.add_widget(
            self.name_label
        )

        self.status_label = Label(
            text="Privacy Protected",
            font_size="14sp",
            halign="center",
            valign="middle",
            color=(0.7, 0.8, 0.9, 1)
        )

        self.status_label.bind(
            size=self.status_label.setter("text_size")
        )

        result_container.add_widget(
            self.status_label
        )

        layout.add_widget(
            result_container
        )

        # =================================================
        # QR / SCANNER INPUT
        # =================================================

        input_container = BoxLayout(
            size_hint=(1, 0.12),
            padding=[2, 2, 2, 2]
        )

        with input_container.canvas:

            Color(
                0.1,
                0.14,
                0.22,
                1
            )

            self.input_bg = RoundedRectangle(
                size=input_container.size,
                pos=input_container.pos,
                radius=[10]
            )

            Color(
                0.95,
                0.55,
                0.15,
                0.3
            )

            self.input_border = Line(
                rounded_rectangle=(
                    input_container.x,
                    input_container.y,
                    input_container.width,
                    input_container.height,
                    10
                ),
                width=1
            )

        input_container.bind(
            pos=self.update_input_bg,
            size=self.update_input_bg
        )

        self.qr_input = TextInput(
            hint_text="Scan or Type here...",
            multiline=False,
            font_size="16sp",
            background_normal="",
            background_active="",
            background_color=(0, 0, 0, 0),
            foreground_color=(1, 1, 1, 1),
            cursor_color=(1, 0.85, 0.6, 1),
            hint_text_color=(0.5, 0.5, 0.5, 1)
        )

        # Directly connect the scanner input
        # to the dedicated auto service.
        self.qr_input.bind(
            text=self._on_qr_text
        )

        # Backup identification: type a Student ID and press Enter.
        self.qr_input.bind(
            on_text_validate=self._on_manual_submit
        )

        input_container.add_widget(
            self.qr_input
        )

        layout.add_widget(
            input_container
        )

        # =================================================
        # CAMERA SCANNER (Google code scanner - APK only)
        # =================================================

        camera_row = BoxLayout(
            orientation="horizontal",
            size_hint=(1, 0.14),
            spacing=10
        )

        scan_btn = Button(
            text="SCAN QR (Camera)",
            size_hint=(0.62, 1),
            background_normal="",
            background_color=(0.15, 0.55, 0.3, 1),
            bold=True
        )

        scan_btn.bind(
            on_press=self.open_camera_scanner
        )

        self.continuous_btn = Button(
            text="Continuous: OFF",
            size_hint=(0.38, 1),
            background_normal="",
            background_color=(0.25, 0.3, 0.45, 1),
            bold=True
        )

        self.continuous_btn.bind(
            on_press=self.toggle_continuous
        )

        camera_row.add_widget(scan_btn)
        camera_row.add_widget(self.continuous_btn)

        layout.add_widget(
            camera_row
        )

        # =================================================
        # ADMIN BUTTON
        # =================================================

        admin_btn = Button(
            text="Admin Reports & Actions",
            size_hint=(1, 0.15),
            background_normal="",
            background_color=(0.1, 0.14, 0.22, 1),
            color=(1, 0.85, 0.6, 1),
            bold=True
        )

        admin_btn.bind(
            on_press=self.open_admin_login
        )

        layout.add_widget(
            admin_btn
        )

        self.add_widget(
            layout
        )

    # =====================================================
    # QR INPUT HANDLER
    # =====================================================

    def _on_qr_text(self, instance, text):

        try:

            app = App.get_running_app()

            if app is None:
                logging.error(
                    "Running application is unavailable."
                )
                return

            check_auto_trigger(
                app,
                instance,
                text
            )

        except Exception as e:

            logging.error(
                f"Main screen QR input error: {e}"
            )

    # =====================================================
    # MANUAL STUDENT ID (backup when the QR is lost)
    # =====================================================

    def _on_manual_submit(self, instance):

        try:

            text = str(instance.text or "").strip()

            if not text:
                return

            upper_text = text.upper()

            # QR codes are processed automatically by auto_service.
            # Handling them here too would record them twice.
            if (
                upper_text.startswith(STUDENT_QR_PREFIX)
                or upper_text.startswith(ADMIN_QR_PREFIX)
            ):
                return

            app = App.get_running_app()

            if app is None or not hasattr(app, "process_attendance"):
                logging.error(
                    "Attendance processor is not available."
                )
                return

            instance.text = ""

            app.process_attendance(text)

        except Exception as e:

            logging.error(
                f"Manual student ID error: {e}"
            )

        finally:

            # Keep the input ready for the next student.
            Clock.schedule_once(
                lambda dt: setattr(instance, "focus", True),
                0.1
            )

    # =====================================================
    # CAMERA SCANNER
    # =====================================================

    def open_camera_scanner(self, instance=None):

        try:

            app = App.get_running_app()

            if app is not None and hasattr(app, "scan_with_camera"):
                app.scan_with_camera()

        except Exception as e:

            logging.error(
                f"Camera scanner error: {e}"
            )

    def toggle_continuous(self, instance=None):

        try:

            app = App.get_running_app()

            if app is not None and hasattr(app, "toggle_continuous_scan"):
                app.toggle_continuous_scan()

        except Exception as e:

            logging.error(
                f"Continuous scan toggle error: {e}"
            )

    def set_continuous_text(self, enabled):

        self.continuous_btn.text = (
            "Continuous: ON" if enabled else "Continuous: OFF"
        )

    # =====================================================
    # OPEN ADMIN LOGIN
    # =====================================================

    def open_admin_login(self, instance):

        try:

            clear_pending_scans()

            if self.manager:
                self.manager.current = "admin_login"

        except Exception as e:

            logging.error(
                f"Admin login navigation error: {e}"
            )

    # =====================================================
    # SCREEN LEAVE
    # =====================================================

    def on_leave(self, *args):

        try:

            # Prevent an old QR scan from being
            # processed after leaving the main screen.
            clear_pending_scans()

            # Clear scanner input.
            self.qr_input.text = ""

        except Exception as e:

            logging.error(
                f"Main screen on_leave error: {e}"
            )

    # =====================================================
    # UPDATE BANNER CANVAS
    # =====================================================

    def update_canvas(self, instance, value):

        try:

            self.bg_rect.pos = instance.pos
            self.bg_rect.size = instance.size

            self.border_line.rounded_rectangle = (
                instance.x,
                instance.y,
                instance.width,
                instance.height,
                20
            )

        except Exception as e:

            logging.error(
                f"Banner canvas update error: {e}"
            )

    # =====================================================
    # UPDATE INPUT CANVAS
    # =====================================================

    def update_input_bg(self, instance, value):

        try:

            self.input_bg.pos = instance.pos
            self.input_bg.size = instance.size

            self.input_border.rounded_rectangle = (
                instance.x,
                instance.y,
                instance.width,
                instance.height,
                10
            )

        except Exception as e:

            logging.error(
                f"Input canvas update error: {e}"
      )
