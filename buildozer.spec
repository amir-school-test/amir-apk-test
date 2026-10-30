[app]
title = AMIR Test
package.name = amirtest
package.domain = org.amirtest
source.dir = .
source.include_exts = py
version = 0.2
requirements = python3,kivy==2.3.0,pyjnius,android,numpy,opencv
orientation = portrait
fullscreen = 0
android.permissions = SEND_SMS,CAMERA
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
