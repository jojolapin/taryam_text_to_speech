# Interface and export correction — 1.2.0-rc.2

The first native candidate overemphasized standard controls and lost the original
interface's visual identity. Export and paragraph batch export remained under File,
but their prominent controls disappeared. The native interface omitted bitrate and
author controls. This was a regression in the replacement interface.

Following the user's choice, the correction retains the native editor and restores
the original blue/violet palette, rounded panels, colorful transport controls and
a visible audio export panel. This recreates the visual direction; it is not an
exact copy of the former web layout.

| Control | Corrected behavior |
| --- | --- |
| Generate audio | Exports the complete selected bookmark to a chosen file |
| Batch export | One output file per paragraph, in a chosen folder |
| Format | MP3 or WAV directly on the main screen |
| MP3 bitrate | 64, 128, 192, 256 or 320 kbps for offline Piper |
| MP3 author | Optional artist/author metadata for offline MP3 files |
| Progress / cancel | Visible in the export panel |
| WAV / online speech | Bitrate is disabled where it does not apply |

Real output checks exposed a pre-existing encoder issue: higher bitrates were
silently limited for low-sample-rate voices. LAME now resamples when needed and
receives bounded PCM blocks to avoid an upsampling buffer failure. All five offered
bitrates were checked against decoded MP3 metadata. Author tags were also verified.
The buffer strategy is consistent with the [encoder wrapper source](https://github.com/chrisstaite/lameenc/blob/main/lameenc.c).

Validation: 182 Python tests pass. Eight real export scenarios pass: five single MP3
bitrates, single WAV, batch MP3 and batch WAV. Evidence is in
`build/qa/gui-export-final/export-results.json`. Source real-audio playback checks
pass in `build/qa/gui-final-source/smoke-result.json`; both themes were inspected.

The corrected package is built separately under `dist/colorful-candidate/` and
passes all six real-audio playback checks, exit 0, with no errors
(`build/qa/gui-packaged/smoke-result.json`). Its portable ZIP and executable have
SHA-256 checksums. The previous candidate remains separate.
See RELEASE_VALIDATION.md for the continuing limits: manual Windows acceptance,
clean-machine installation, native localization and remaining legacy conveniences.
This correction does not claim that every feature of the former interface is restored.
Generated executables, test profiles and distribution backups stay outside Git.

The subsequent 1.2.0-rc.3 branding update restores “TextSpeak Pro™ by JojoLapin Inc.”
in the header and About dialog, plus a permanent copyright footer. Its executable
is built separately under `dist/branded-candidate/`. It passes all six packaged
playback checks (`build/qa/trademark-packaged/smoke-result.json`), and the full
182-test Python / 83-test JavaScript suites pass before publication.
