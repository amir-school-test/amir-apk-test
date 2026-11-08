import logging

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen


class AdminSettingsScreen(Screen):

    MIN_PASSWORD_LENGTH = 6
    MAX_PASSWORD_LENGTH = 256

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._password_change_in_progress = False
        self._active_popup = None

        layout = BoxLayout(
            orientation="vertical",
            padding=30,
            spacing=15
        )

        # TITLE
        layout.add_widget(
            Label(
                text="Change Admin Password",
                font_size="20sp",
                bold=True,
                color=(1, 0.85, 0.6, 1),
                size_hint=(1, 0.15)
            )
        )

        # CURRENT PASSWORD
        self.old_pass_input = TextInput(
            hint_text="Current Password",
            password=True,
            multiline=False,
            font_size="16sp",
            size_hint=(1, 0.15)
        )

        self.old_pass_input.bind(
            on_text_validate=self.change_password
        )

        layout.add_widget(self.old_pass_input)

        # NEW PASSWORD
        self.new_pass_input = TextInput(
            hint_text="New Password (minimum 6 characters)",
            password=True,
            multiline=False,
            font_size="16sp",
            size_hint=(1, 0.15)
        )

        layout.add_widget(self.new_pass_input)

        # CONFIRM NEW PASSWORD
        self.confirm_pass_input = TextInput(
            hint_text="Confirm New Password",
            password=True,
            multiline=False,
            font_size="16sp",
            size_hint=(1, 0.15)
        )

        self.confirm_pass_input.bind(
            on_text_validate=self.change_password
        )

        layout.add_widget(self.confirm_pass_input)

        # SAVE BUTTON
        self.save_btn = Button(
            text="Save New Password",
            size_hint=(1, 0.15),
            background_normal="",
            background_color=(0.15, 0.65, 0.35, 1),
            bold=True
        )

        self.save_btn.bind(
            on_press=self.change_password
        )

        layout.add_widget(self.save_btn)

        # BACK BUTTON
        back_btn = Button(
            text="Back to Reports",
            size_hint=(1, 0.15),
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
    # SCREEN SECURITY
    # =====================================================

    def on_enter(self, *args):

        self.clear_fields()

        if not self._is_admin_authenticated():

            logging.warning(
                "Unauthenticated attempt to open admin settings."
            )

            if self.manager:
                self.manager.current = "admin_login"

    def on_leave(self, *args):

        self.clear_fields()

        self._password_change_in_progress = False

        if self._active_popup is not None:
            try:
                self._active_popup.dismiss()
            except Exception:
                pass

            self._active_popup = None

    # =====================================================
    # AUTHENTICATION CHECK
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

        except Exception:
            logging.exception(
                "Admin authentication check failed."
            )
            return False

    # =====================================================
    # CHANGE PASSWORD
    # =====================================================

    def change_password(self, instance=None):

        if self._password_change_in_progress:
            return

        if not self._is_admin_authenticated():

            self.clear_fields()

            self.show_popup(
                "Access Denied",
                "Admin authentication is required.",
                is_success=False
            )

            if self.manager:
                self.manager.current = "admin_login"

            return

        self._password_change_in_progress = True

        try:
            old_password = self.old_pass_input.text
            new_password = self.new_pass_input.text
            confirm_password = self.confirm_pass_input.text

            # Validate current password field.
            if not old_password:
                self.show_popup(
                    "Error",
                    "Please enter your current password.",
                    is_success=False
                )
                return

            # Validate new password.
            if not new_password:
                self.show_popup(
                    "Error",
                    "New password cannot be empty.",
                    is_success=False
                )
                return

            if len(new_password) < self.MIN_PASSWORD_LENGTH:
                self.show_popup(
                    "Error",
                    "New password must contain at least 6 characters.",
                    is_success=False
                )
                return

            if len(new_password) > self.MAX_PASSWORD_LENGTH:
                self.show_popup(
                    "Error",
                    "New password is too long.",
                    is_success=False
                )
                return

            # Validate confirmation.
            if not confirm_password:
                self.show_popup(
                    "Error",
                    "Please confirm the new password.",
                    is_success=False
                )
                return

            if new_password != confirm_password:
                self.show_popup(
                    "Error",
                    "New passwords do not match.",
                    is_success=False
                )
                return

            if old_password == new_password:
                self.show_popup(
                    "Error",
                    "New password must be different from the current password.",
                    is_success=False
                )
                return

            # Verify current password.
            app = App.get_running_app()

            if not hasattr(app, "verify_admin_password"):
                logging.error(
                    "Admin password verification method is missing."
                )

                self.show_popup(
                    "System Error",
                    "Password verification is unavailable.",
                    is_success=False
                )
                return

            verified = app.verify_admin_password(
                old_password
            )

            if not verified:
                self.clear_fields()

                self.show_popup(
                    "Error",
                    "Current password is incorrect.",
                    is_success=False
                )
                return

            # Update password.
            if not hasattr(app, "update_admin_password"):
                logging.error(
                    "Admin password update method is missing."
                )

                self.clear_fields()

                self.show_popup(
                    "System Error",
                    "Password updating is unavailable.",
                    is_success=False
                )
                return

            result = app.update_admin_password(
                new_password
            )

            if result is not True:
                self.clear_fields()

                self.show_popup(
                    "Error",
                    "Password could not be updated.",
                    is_success=False
                )
                return

            self.clear_fields()

            self.show_popup(
                "Success",
                "Password updated successfully.\n"
                "Your new password is securely protected.",
                is_success=True
            )

        except Exception:
            logging.exception(
                "Admin password change failed."
            )

            self.clear_fields()

            self.show_popup(
                "System Error",
                "An error occurred while changing the password.",
                is_success=False
            )

        finally:
            self._password_change_in_progress = False

    # =====================================================
    # BACK
    # =====================================================

    def go_back(self, instance=None):

        self.clear_fields()

        if self.manager:
            self.manager.current = "admin_reports"

    # =====================================================
    # CLEAR INPUTS
    # =====================================================

    def clear_fields(self):

        for field_name in (
            "old_pass_input",
            "new_pass_input",
            "confirm_pass_input"
        ):
            field = getattr(self, field_name, None)

            if field is not None:
                field.text = ""

    # =====================================================
    # POPUP
    # =====================================================

    def show_popup(
        self,
        title,
        message,
        is_success=True
    ):

        # Close any previous popup first.
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

            if self._active_popup is popup:
                self._active_popup = None

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
