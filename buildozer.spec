[app]
title = AMIR Test
package.name = amirtest
package.domain = org.amirtest
source.dir = .
source.include_exts = py
version = 0.1
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,pyjnius,android
orientation = portrait
fullscreen = 0
android.permissions = SEND_SMS,CAMERA
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
