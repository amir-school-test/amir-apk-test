import traceback
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

NUMBER_HINT = "+2519XXXXXXXX"


class T(App):
    def build(self):
        root = BoxLayout(orientation="vertical", padding=10, spacing=10)
        self.num = TextInput(text=NUMBER_HINT, multiline=False,
                             size_hint=(1, .12))
        self.lbl = Label(text="Press a button", font_size="14sp")
        b1 = Button(text="1) Ask permissions", size_hint=(1, .15))
        b2 = Button(text="2) Send test SMS", size_hint=(1, .15))
        b1.bind(on_press=self.ask)
        b2.bind(on_press=self.sms)
        for w in (self.num, b1, b2, self.lbl):
            root.add_widget(w)
        return root

    def ask(self, *a):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.SEND_SMS, Permission.CAMERA])
            self.lbl.text = "Permissions requested"
        except Exception:
            self.lbl.text = traceback.format_exc()

    def sms(self, *a):
        try:
            from jnius import autoclass
            SmsManager = autoclass("android.telephony.SmsManager")
            SmsManager.getDefault().sendTextMessage(
                self.num.text.strip(), None, "AMIR test 1", None, None)
            self.lbl.text = "Call returned (not proof). Check the phone."
        except Exception:
            self.lbl.text = traceback.format_exc()


T().run()
