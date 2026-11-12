import logging

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput

from database.database import create_admin_qr_token, log_system_event
from services.qr_code_service import make_matrix, make_widget


# (اسم الوضع في النظام، النص الظاهر، لون الزر)
MODES = (
    ("EXAM", "Exam Card", (0.35, 0.35, 0.8, 1)),
    ("SICK", "Sick Card", (0.75, 0.3, 0.7, 1)),
    ("SCHOOL_APPROVAL", "School Approval Card", (0.85, 0.5, 0.15, 1)),
)


class ModeCardsScreen(Screen):
    """
    بطاقات الإدارة (QR) للأوضاع الخاصة:

        EXAM, SICK, SCHOOL_APPROVAL

    مسح البطاقة مرة يفتح الوضع، ومسحها مرة ثانية يغلقه.

    لا يُحفظ الرمز السري نفسه في قاعدة البيانات (يُحفظ hash فقط)،
    لذلك لا يمكن عرضه مرة ثانية. إنشاء بطاقة جديدة يُلغي القديمة.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._active_popup = None

        layout = BoxLayout(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10)
        )

        layout.add_widget(
            Label(
                text="Special Mode Cards",
                font_size="21sp",
                bold=True,
                color=(1, 0.85, 0.6, 1),
                size_hint_y=None,
                height=dp(50)
            )
        )

        info = Label(
            text=(
                "Scan a card once to turn its mode ON, and "
                "again to turn it OFF.\n"
                "Creating a new card disables the old one."
            ),
            font_size="14sp",
            halign="center",
            valign="middle",
            color=(0.7, 0.8, 0.9, 1),
            size_hint_y=None,
            height=dp(70)
        )

        info.bind(size=info.setter("text_size"))

        layout.add_widget(info)

        for mode_name, label, color in MODES:

            button = Button(
                text=f"Create New {label}",
                size_hint_y=None,
                height=dp(64),
                background_normal="",
                background_color=color,
                bold=True
            )

            button.bind(
                on_press=lambda instance, m=mode_name, l=label:
                    self.confirm_create(m, l)
            )

            layout.add_widget(button)

        layout.add_widget(BoxLayout())

        back_button = Button(
            text="Back to Reports",
            size_hint_y=None,
            height=dp(54),
            background_normal="",
            background_color=(0.5, 0.5, 0.5, 1),
            bold=True
        )

        back_button.bind(on_press=self.go_back)

        layout.add_widget(back_button)

        self.add_widget(layout)

    # =====================================================
    # SCREEN SECURITY
    # =====================================================

    def on_enter(self, *args):

        if not self._is_admin_authenticated():
            self._go_to_login()

    def on_leave(self, *args):

        self._dismiss_popup()

    def _is_admin_authenticated(self):

        try:

            app = App.get_running_app()

            return bool(
                getattr(app, "admin_authenticated", False)
            )

        except Exception:

            logging.exception(
                "Mode cards authentication check failed."
            )

            return False

    def _go_to_login(self):

        if self.manager:
            self.manager.current = "admin_login"

    def _dismiss_popup(self):

        if self._active_popup is not None:

            try:
                self._active_popup.dismiss()
            except Exception:
                pass

            self._active_popup = None

    # =====================================================
    # CREATE CARD
    # =====================================================

    def confirm_create(self, mode_name, label):

        if not self._is_admin_authenticated():
            self._go_to_login()
            return

        self._dismiss_popup()

        content = BoxLayout(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(12)
        )

        message = Label(
            text=(
                f"Create a NEW {label}?\n\n"
                f"The previous {label}, if you printed one, "
                "will stop working."
            ),
            halign="center",
            valign="middle",
            font_size="15sp"
        )

        message.bind(size=message.setter("text_size"))

        content.add_widget(message)

        buttons = BoxLayout(
            orientation="horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(50)
        )

        cancel_button = Button(
            text="Cancel",
            background_normal="",
            background_color=(0.5, 0.5, 0.5, 1)
        )

        create_button = Button(
            text="Create",
            background_normal="",
            background_color=(0.15, 0.65, 0.35, 1),
            bold=True
        )

        buttons.add_widget(cancel_button)
        buttons.add_widget(create_button)

        content.add_widget(buttons)

        popup = Popup(
            title="Confirm New Card",
            content=content,
            size_hint=(0.88, 0.42),
            auto_dismiss=False
        )

        self._active_popup = popup

        cancel_button.bind(on_press=lambda instance: self._dismiss_popup())

        create_button.bind(
            on_press=lambda instance:
                self._create_card(mode_name, label)
        )

        popup.open()

    def _create_card(self, mode_name, label):

        self._dismiss_popup()

        if not self._is_admin_authenticated():
            self._go_to_login()
            return

        try:

            token = create_admin_qr_token(mode_name)

            code_text = f"ADMIN:{mode_name}:{token}"

            matrix = make_matrix(code_text)

        except Exception:

            logging.exception("Could not create the admin card.")

            self._show_message(
                "Error",
                "The card could not be created.\nNothing was changed."
            )

            return

        try:

            log_system_event(
                "ADMIN_CARD_CREATED",
                details=f"New {mode_name} card was created."
            )

        except Exception:

            logging.exception("Could not log the card creation.")

        self._show_card(label, code_text, matrix)

    def _show_card(self, label, code_text, matrix):

        content = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8)
        )

        hint = Label(
            text=(
                "Take a screenshot to print this card, then delete "
                "the screenshot.\nThis code will NOT be shown again."
            ),
            font_size="13sp",
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(52)
        )

        hint.bind(size=hint.setter("text_size"))

        content.add_widget(hint)

        content.add_widget(make_widget(matrix, size_hint=(1, 1)))

        code_box = TextInput(
            text=code_text,
            readonly=True,
            multiline=True,
            font_size="12sp",
            size_hint_y=None,
            height=dp(64)
        )

        content.add_widget(code_box)

        close_button = Button(
            text="Done",
            size_hint_y=None,
            height=dp(50),
            background_normal="",
            background_color=(0.2, 0.5, 0.8, 1),
            bold=True
        )

        content.add_widget(close_button)

        popup = Popup(
            title=label,
            content=content,
            size_hint=(0.96, 0.92),
            auto_dismiss=False
        )

        self._active_popup = popup

        close_button.bind(on_press=lambda instance: self._dismiss_popup())

        popup.open()

    def _show_message(self, title, message_text):

        content = BoxLayout(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(15)
        )

        message = Label(
            text=message_text,
            halign="center",
            valign="middle",
            font_size="15sp"
        )

        message.bind(size=message.setter("text_size"))

        close_button = Button(
            text="OK",
            size_hint_y=None,
            height=dp(50),
            background_normal="",
            background_color=(0.2, 0.5, 0.8, 1),
            bold=True
        )

        content.add_widget(message)
        content.add_widget(close_button)

        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.85, 0.4),
            auto_dismiss=True
        )

        self._active_popup = popup

        close_button.bind(on_press=popup.dismiss)

        popup.open()

    # =====================================================
    # BACK
    # =====================================================

    def go_back(self, instance=None):

        self._dismiss_popup()

        if self.manager:
            self.manager.current = "admin_reports"
