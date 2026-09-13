# TextSpeak Pro 1.2.0-rc.3

Windows release candidate from JojoLapin Inc.

## Downloads

- **TextSpeakPro-Setup-1.2.0-rc.3.exe**: Windows installer with Start menu shortcuts,
  optional desktop shortcut and an uninstaller.
- **TextSpeakPro-1.2.0-rc.3-portable.zip**: extract the entire ZIP to a writable
  folder, then open TextSpeakPro.exe. Keep portable.flag next to it.
- Each download has a SHA-256 checksum sidecar.

Quit an existing copy through its tray menu before opening another copy.
Installed documents and voices use the existing user profile; portable copies keep
their data beside the executable. The binaries are unsigned.

## Included

The colorful native editor carries the TextSpeak Pro trademark and JojoLapin Inc.
branding. It supports file drops, native editing and context menus, independent
document tabs during playback, and visible MP3/WAV export controls with batch
export and Piper MP3 bitrate selection.

The source archive includes three Windows scripts: run **setup.bat** once, then
**run.bat** to open the application. **build.bat** creates all Windows packages.
Source setup requires Python 3.13 x64; building the installer also needs Inno Setup 6.

## Validation and limits

Automated editor/playback regressions, real offline audio exports and packaged
playback checks have passed. Current-user installation and uninstall were tested
on the development machine, including executable integrity and preservation of
user-created files.

This is a prerelease: clean-machine installation and full manual Windows
acceptance remain outstanding. The native interface is not fully localized into
French; saved voice-preset controls, headset bindings and time-based seeking have
not been migrated. Live paid OpenAI requests were not tested. See
[RELEASE_VALIDATION.md](https://github.com/jojolapin/taryam_text_to_speech/blob/v1.2.0-rc.3/RELEASE_VALIDATION.md)
for the detailed validation record.
