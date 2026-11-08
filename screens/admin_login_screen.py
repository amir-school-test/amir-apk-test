import logging

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen

from services.auth_service import get_login_lockout_remaining


class AdminLoginScreen(Screen):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._login_in_progress = False
        self._active_popup = None

        layout = BoxLayout(
            orientation="vertical",
            padding=40,
            spacing=20
        )

        layout.add_widget(
            Label(
                text="Admin Access Only",
                font_size="22sp",
                bold=True,
                color=(1, 0.85, 0.6, 1),
                size_hint=(1, 0.18)
            )
        )

        self.pass_input = TextInput(
            hint_text="Enter Admin Password",
            password=True,
            multiline=False,
            font_size="18sp",
            size_hint=(1, 0.2)
        )

        self.pass_input.bind(
            on_text_validate=self.verify_admin
        )

        layout.add_widget(self.pass_input)

        self.login_btn = Button(
            text="Login",
            size_hint=(1, 0.2),
            background_normal="",
            background_color=(0.15, 0.65, 0.35, 1),
            bold=True
        )

        self.login_btn.bind(
            on_press=self.verify_admin
        )

        layout.add_widget(self.login_btn)

        back_btn = Button(
            text="Back",
            size_hint=(1, 0.2),
            background_normal="",
            background_color=(0.75, 0.25, 0.25, 1),
            bold=True
        )

        back_btn.bind(
            on_press=self.go_back
        )

        layout.add_widget(back_btn)

        self.add_widget(layout)

    # =====================================================
    # SCREEN LIFECYCLE
    # =====================================================

    def on_enter(self, *args):
        self.pass_input.text = ""

        try:
            app = App.get_running_app()

            # A fresh visit to login must not inherit
            # an old authenticated session.
            app.admin_authenticated = False

        except Exception:
            logging.exception(
                "Unable to reset admin authentication state."
            )

    def on_leave(self, *args):
        self.pass_input.text = ""
        self._login_in_progress = False
        self.login_btn.disabled = False

        if self._active_popup is not None:
            try:
                self._active_popup.dismiss()
            except Exception:
                pass

            self._active_popup = None

    # =====================================================
    # LOGIN
    # =====================================================

    def verify_admin(self, instance=None):

        if self._login_in_progress:
            return

        self._login_in_progress = True
        self.login_btn.disabled = True

        entered_password = self.pass_input.text

        # Clear the visible field immediately.
        self.pass_input.text = ""

        try:
            app = App.get_running_app()

            if not entered_password:
                self.show_popup(
                    "Login Error",
                    "Please enter the admin password.",
                    is_success=False
                )
                return

            # Fail closed if lockout status cannot be read.
            try:
                remaining = int(
                    get_login_lockout_remaining()
                )
            except Exception:
                logging.exception(
                    "Unable to check admin login lockout."
                )

                self.show_popup(
                    "System Error",
                    "Login protection is temporarily unavailable.",
                    is_success=False
                )
                return

            if remaining > 0:
                self.show_popup(
                    "Temporarily Locked",
                    f"Too many failed attempts.\n"
                    f"Please wait {remaining} seconds.",
                    is_success=False
                )
                return

            if not hasattr(app, "verify_admin_password"):
                logging.error(
                    "Admin password verification method is missing."
                )

                self.show_popup(
                    "System Error",
                    "Admin authentication is unavailable.",
                    is_success=False
                )
                return

            success = app.verify_admin_password(
                entered_password
            )

            if success:
                app.admin_authenticated = True

                if self.manager:
                    self.manager.current = "admin_reports"

            else:
                # Check whether this failure triggered lockout.
                try:
                    remaining = int(
                        get_login_lockout_remaining()
                    )
                except Exception:
                    logging.exception(
                        "Unable to read lockout after failed login."
                    )
                    remaining = 0

                if remaining > 0:
                    self.show_popup(
                        "Temporarily Locked",
                        f"Too many failed attempts.\n"
                        f"Please wait {remaining} seconds.",
                        is_success=False
                    )
                else:
                    self.show_popup(
                        "Login Failed",
                        "Incorrect admin password.",
                        is_success=False
                    )

        except Exception:
            logging.exception(
                "Admin login failed unexpectedly."
            )

            try:
                app = App.get_running_app()
                app.admin_authenticated = False
            except Exception:
                pass

            self.show_popup(
                "System Error",
                "An error occurred during login.",
                is_success=False
            )

        finally:
            # Do not retain the entered password.
            entered_password = ""

            self._login_in_progress = False

            Clock.schedule_once(
                self._enable_login_button,
                0.3
            )

    # =====================================================
    # NAVIGATION
    # =====================================================

    def go_back(self, instance=None):

        try:
            app = App.get_running_app()
            app.admin_authenticated = False
        except Exception:
            logging.exception(
                "Unable to clear admin authentication."
            )

        self.pass_input.text = ""

        if self.manager:
            self.manager.current = "main"

    # =====================================================
    # BUTTON STATE
    # =====================================================

    def _enable_login_button(self, dt):

        if self.parent is not None:
            self.login_btn.disabled = False

    # =====================================================
    # POPUP
    # =====================================================

    def show_popup(
        self,
        title,
        message,
        is_success=True
    ):

        if self._active_popup is not None:
            try:
                self._active_popup.dismiss()
            except Exception:
                pass

        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=15
        )

        message_label = Label(
            text=message,
            font_size="15sp",
            halign="center",
            valign="middle",
            color=(1, 1, 1, 1)
        )

        message_label.bind(
            size=message_label.setter("text_size")
        )

        content.add_widget(message_label)

        close_btn = Button(
            text="OK",
            size_hint=(1, 0.4),
            background_normal="",
            background_color=(
                (0.15, 0.65, 0.35, 1)
                if is_success
                else (0.8, 0.2, 0.2, 1)
            ),
            bold=True
        )

        content.add_widget(close_btn)

        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.8, 0.4),
            auto_dismiss=True
        )

        self._active_popup = popup

        def close_popup(*args):
            popup.dismiss()

        close_btn.bind(on_press=close_popup)

        popup.bind(
            on_dismiss=lambda *args: self._clear_popup_reference(
                popup
            )
        )

        popup.open()

    def _clear_popup_reference(self, popup):

        if self._active_popup is popup:
            self._active_popup = None
