[app]

# Cripto Señales para Android - Autor: Luis Tranche Casado
title = Cripto Señales
package.name = criptosenales
package.domain = es.luistranche
version = 1.0

source.dir = .
source.include_exts = py,png
source.exclude_dirs = bin,.buildozer,.github

# python3 + kivy para la interfaz; sqlite3 (base de datos), openssl y certifi (https)
requirements = python3,kivy==2.3.1,sqlite3,openssl,certifi,pyjnius

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/icon.png
android.presplash_color = #0e1217

orientation = portrait
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
