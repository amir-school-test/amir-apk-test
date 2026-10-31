import time
import traceback
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

BRIDGE = "org.amirtest.bridge.QrBridge"


class T(App):
    def build(self):
        self.t0 = 0.0
        self.count = 0
        self.loop = False
        self.polling = False
        box = BoxLayout(orientation="vertical", padding=8, spacing=8)
        self.num = TextInput(text="+2519XXXXXXXX", multiline=False,
                             size_hint=(1, .08))
        self.lbl = Label(text="Ready", font_size="18sp",
                         halign="center", valign="middle",
                         size_hint=(1, .38))
        self.lbl.bind(size=lambda i, v: setattr(i, "text_size", v))
        b_scan = Button(text="SCAN QR (Google scanner)",
                        size_hint=(1, .16))
        self.b_loop = Button(text="Auto-repeat: OFF", size_hint=(1, .1))
        b_sms = Button(text="Send test SMS", size_hint=(1, .1))
        b_scan.bind(on_press=self.start_scan)
        self.b_loop.bind(on_press=self.toggle_loop)
        b_sms.bind(on_press=self.sms)
        for w in (self.num, self.lbl, b_scan, self.b_loop, b_sms):
            box.add_widget(w)
        return box

    def on_start(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.SEND_SMS])
        except Exception:
            self.lbl.text = traceback.format_exc()[-500:]

    def toggle_loop(self, *a):
        self.loop = not self.loop
        self.b_loop.text = "Auto-repeat: " + ("ON" if self.loop else "OFF")

    def start_scan(self, *a):
        if self.polling:
            return
        try:
            from jnius import autoclass
            PA = autoclass("org.kivy.android.PythonActivity")
            Q = autoclass(BRIDGE)
            self.t0 = time.time()
            Q.scan(PA.mActivity)
            self.lbl.text = "Opening scanner..."
            self.polling = True
            Clock.schedule_interval(self.poll, 0.25)
        except Exception:
            self.lbl.text = traceback.format_exc()[-500:]

    def poll(self, dt):
        try:
            from jnius import autoclass
            Q = autoclass(BRIDGE)
            st = Q.getStatus()
            if st == "scanning":
                return True
            self.polling = False
            if st == "ok":
                self.count += 1
                self.lbl.text = "QR #%d:\n%s\n(%.1f s incl. aiming)" % (
                    self.count, Q.getResult(), time.time() - self.t0)
                if self.loop:
                    Clock.schedule_once(self.start_scan, 1.5)
            else:
                self.loop = False
                self.b_loop.text = "Auto-repeat: OFF"
                self.lbl.text = st
            return False
        except Exception:
            self.polling = False
            self.lbl.text = traceback.format_exc()[-500:]
            return False

    def sms(self, *a):
        try:
            from jnius import autoclass
            SmsManager = autoclass("android.telephony.SmsManager")
            SmsManager.getDefault().sendTextMessage(
                self.num.text.strip(), None, "AMIR test 2", None, None)
            self.lbl.text = "SMS call returned (not proof)."
        except Exception:
            self.lbl.text = traceback.format_exc()[-500:]


T().run()
