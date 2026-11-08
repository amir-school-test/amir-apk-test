[app]
title = AMIR SYSTEM
package.name = amir
package.domain = org.amirsystem
source.dir = .
source.include_exts = py,ttf
source.exclude_patterns = check_files.py
source.include_patterns = database/*.py, services/*.py, screens/*.py
version = 0.5
requirements = python3,kivy==2.3.0,pyjnius,android,fpdf
orientation = portrait
fullscreen = 0
android.wakelock = True
android.permissions = SEND_SMS,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.add_src = javasrc
android.gradle_dependencies = com.google.android.gms:play-services-code-scanner:16.1.0
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
