[app]

title = Fetch
package.name = fetch
package.domain = org.fetch
version = 1.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

requirements = hostpython3,python3,kivy==2.3.0,yt-dlp,certifi,requests,urllib3,idna,chardet,openssl,sqlite3,pycryptodome

orientation = portrait

android.manifest.intent_filters = intent_filters.xml

android.manifest.launch_mode = singleTask

android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE

android.logcat_filters = *:S python:D

android.api          = 33
android.minapi       = 21
android.ndk          = 25b
android.ndk_api      = 21

android.accept_sdk_license = True

android.archs = arm64-v8a

android.release_artifact = apk

p4a.branch = v2024.01.21

[buildozer]

log_level = 2
warn_on_root = 1
