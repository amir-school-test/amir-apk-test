import traceback
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

try:
    import numpy as np
    import cv2
    CV_OK = True
    CV_ERR = ""
except Exception:
    CV_OK = False
    CV_ERR = traceback.format_exc()


class T(App):
    def build(self):
        self.cam = None
        self.cam_index = 0
        self.root_box = BoxLayout(orientation="vertical",
                                  padding=6, spacing=6)
        self.num = TextInput(text="+2519XXXXXXXX", multiline=False,
                             size_hint=(1, .09))
        self.lbl = Label(text="OpenCV: " + ("OK" if CV_OK else "MISSING"),
                         font_size="13sp", size_hint=(1, .2))
        b1 = Button(text="1) Ask permissions", size_hint=(1, .09))
        b2 = Button(text="2) Send test SMS", size_hint=(1, .09))
        b3 = Button(text="3) Start camera / scan QR", size_hint=(1, .09))
        b4 = Button(text="4) Switch camera", size_hint=(1, .09))
        b1.bind(on_press=self.ask)
        b2.bind(on_press=self.sms)
        b3.bind(on_press=self.start_cam)
        b4.bind(on_press=self.switch_cam)
        for w in (self.num, b1, b2, b3, b4, self.lbl):
            self.root_box.add_widget(w)
        return self.root_box

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
            self.lbl.text = "SMS call returned (not proof)."
        except Exception:
            self.lbl.text = traceback.format_exc()

    def stop_cam(self):
        Clock.unschedule(self.tick)
        if self.cam is not None:
            try:
                self.cam.play = False
                self.root_box.remove_widget(self.cam)
            except Exception:
                pass
            self.cam = None

    def start_cam(self, *a):
        if not CV_OK:
            self.lbl.text = CV_ERR[-600:]
            return
        try:
            from kivy.uix.camera import Camera
            self.stop_cam()
            self.cam = Camera(index=self.cam_index,
                              resolution=(640, 480),
                              play=True, size_hint=(1, .35))
            self.root_box.add_widget(self.cam, index=1)
            self.det = cv2.QRCodeDetector()
            Clock.schedule_interval(self.tick, 0.7)
            self.lbl.text = "Camera %d started" % self.cam_index
        except Exception:
            self.lbl.text = traceback.format_exc()[-600:]

    def switch_cam(self, *a):
        self.cam_index = 1 - self.cam_index
        self.start_cam()

    def tick(self, dt):
        try:
            t = self.cam.texture
            if t is None:
                self.lbl.text = "No camera frame yet"
                return
            w, h = t.size
            arr = np.frombuffer(t.pixels, np.uint8).reshape(h, w, 4)
            gray = cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
            for k in range(4):
                img = np.ascontiguousarray(np.rot90(gray, k))
                data, _, _ = self.det.detectAndDecode(img)
                if data:
                    self.lbl.text = "QR: " + data
                    return
            self.lbl.text = "Camera OK, no QR found"
        except Exception:
            self.lbl.text = traceback.format_exc()[-600:]


T().run()
