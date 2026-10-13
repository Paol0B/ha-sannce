# SANNCE for Home Assistant

Home Assistant integration for SANNCE wired IP cameras. It talks to the camera over your LAN and needs no cloud account.

SANNCE Life cameras are Tiandy OEM devices. The reference model is the I91FW (4K, PoE, white light and infrared). Other models may work.

## Status

Not verified on hardware. The protocol comes from static analysis of the SANNCE Life app. No part of it has run on a real camera yet. The tests use a simulator built from the same spec. They show the code matches the spec, not the camera. Expect fixes after the first run.

- [docs/protocol.md](docs/protocol.md) is the protocol spec. Each claim is tagged `static`, `inferred` or `verified`. Nothing is `verified` yet.
- [docs/hardware-checklist.md](docs/hardware-checklist.md) lists the checks to run when a camera is on the bench.

## Requirements

- Home Assistant 2026.10 or newer. Older versions are untested.
- A camera on the same LAN, activated, with an admin password.
- TCP from Home Assistant to the camera: port 3000 (events, speaker), 80 (settings) and 554 (video).
- A fixed camera address. The integration does not follow address changes.
- The `ffmpeg` binary, for the siren and the speaker. The official container image has it.

## Install

### HACS

Add this repository to HACS as a custom repository with the category Integration. Download SANNCE, then restart Home Assistant.

### Manual

Copy `custom_components/sannce` to `<config>/custom_components/sannce`, then restart Home Assistant. The folder includes the camera library, so nothing else needs installing.

### Container, over SSH

```sh
scripts/deploy.sh HOST [CONTAINER] [CONFIG_PATH]
```

The script refreshes the bundled library from `lib/src/`, copies `custom_components/sannce` to `HOST` with rsync, then runs `docker restart`.

| Argument | Meaning | Default |
|---|---|---|
| `HOST` | SSH target, for example `root@ha.local` | required |
| `CONTAINER` | container name | `homeassistant` |
| `CONFIG_PATH` | config directory on `HOST`, the one the container mounts as `/config` | `/config` |

Both machines need rsync. The SSH user must write to the config directory and run `docker`.

## Setup

Open Settings, Devices & services, Add integration, and pick SANNCE.

- Enter the camera address, user name and password. The user name defaults to `admin`.
- Or leave the address empty to search the LAN. Pick the camera, then enter its login. The search uses UDP multicast, so a container probably needs host networking.
- The ports are optional: private protocol 3000, HTTP 80, RTSP 554.
- If the password changes, Home Assistant asks for the new one.

Model, serial number and MAC address come from the LAN search. A camera added by typing its address usually has none of them, so Home Assistant names it after its address.

## Entities

| Platform | Entity | Notes |
|---|---|---|
| `camera` | Sub stream | RTSP `/1/2`. Enabled by default. |
| `camera` | Main stream | RTSP `/1/1`. Disabled by default. |
| `binary_sensor` | Motion, Vehicle | Pushed by the camera. |
| `binary_sensor` | Intrusion, Line crossing, Tamper | Pushed by the camera. Tamper is the lens cover. |
| `binary_sensor` | Video loss | Diagnostic. |
| `light` | Floodlight | The white light. Off means auto, see Known limits. |
| `select` | Light mode | Infrared, Color or Smart. |
| `switch` | Person detection, Vehicle detection, Motion detection | Configuration entities. |
| `siren` | Siren | Plays a generated tone on the camera speaker. Tones `alarm` and `chime`, up to 300 s. |
| `media_player` | Speaker | Plays TTS and media-source audio on the camera speaker. Supports stop. |

The camera reports which features it has. The integration creates Motion, Vehicle, Floodlight, Light mode and the detection switches only when it does. Siren, Speaker, Intrusion, Line crossing, Tamper and Video loss always appear.

Events arrive at once. The light, light mode and detection settings refresh every 60 seconds and after each command. A change made in the vendor app shows up within a minute.

A dropped camera connection makes every entity unavailable, not off, until it returns. A failed settings read does the same for the light, the light mode and the switches.

## Known limits

- **Floodlight off means auto.** Turning the light off hands the lamp back to the camera. It does not force the lamp off. The entity reads on only while the lamp is forced on. A lamp the camera lit by itself reads off. For a lamp that never lights, set Light mode to Infrared.
- **No person sensor.** The camera sends motion and vehicle events, not a person event. A person most likely arrives as plain Motion. Person detection is a switch that turns the camera's person filter on or off. Check 6.3 of the hardware checklist looks for a real person source, such as ONVIF.
- **Detection switches may be locked.** The Motion detection switch writes only the camera's all-motion flag. The vendor app sets person and vehicle together with that flag and locks them while it is on. The app also refuses to turn person and vehicle off in Smart light mode. The camera may enforce the same rules. Then the person and vehicle switches can read off while the camera treats them as on. Some changes can fail. Not verified. Checks 9.6 and 9.7 of the hardware checklist cover it. The protocol spec has details in its Light mode and Motion detection sections.
- **Siren and speaker replies are inferred.** Both send audio over the camera's talk channel. The camera's replies to start, refuse and end come from the vendor SDK code, not from a camera. The library always reports the talk capability. Every camera gets a siren and a speaker, even one without a speaker. One sound plays at a time, and a new sound replaces the current one.
- **Rule sensors may stay silent.** Intrusion, Line crossing, Tamper and Video loss exist on every camera. The I91FW may never send those events. Disable the ones you do not need.
- **Events clear on a timer.** The camera may not send a stop event. A sensor turns off 10 seconds after the last start.
- **Customize light mode reads as unknown.** The integration reads the vendor app's Customize mode but cannot set it.
- **No encryption.** The private login sends the password in base64, and the RTSP URL carries it. Use a trusted LAN.

When you report a problem, attach the diagnostics file from the device page. It redacts the host, user name, password, serial number and MAC address.

## Live push-to-talk

The speaker plays audio that Home Assistant produces. It does not carry your voice live. Live push-to-talk needs three more pieces, and none is verified on this camera.

- The camera's RTSP backchannel (ONVIF two-way audio). The vendor advertises two-way audio, but nothing confirms the backchannel.
- go2rtc, to carry microphone audio to that backchannel. The go2rtc built into Home Assistant may not pass it. If it does not, run go2rtc as a separate container.
- A card with a microphone button, such as WebRTC Camera or Advanced Camera Card. Open the dashboard over HTTPS, because browsers block the microphone on plain HTTP.

To try it, add the main stream to go2rtc:

```yaml
streams:
  sannce: rtsp://admin:PASSWORD@192.168.1.10:554/1/1
```

Then use the stream in the WebRTC Camera card:

```yaml
type: custom:webrtc-camera
url: sannce
media: video,audio,microphone
```

Both snippets are untested. If the camera has no backchannel, a bridge from go2rtc to the library's talk channel is needed. It is not written.

## Development

The camera library `sannce-aio` lives in `lib/` ([lib/README.md](lib/README.md)). A copy sits in `custom_components/sannce/sannce_aio/`, and only `custom_components/sannce/lib.py` imports it. `manifest.json` lists no requirements until the library is on PyPI.

After you change `lib/src/`, run `scripts/vendor-lib.sh`. `scripts/deploy.sh` runs it too.

The test tools need Python 3.14.2 or newer, as Home Assistant 2026.10 does.

```sh
python -m venv .venv
.venv/bin/python -m pip install pytest-homeassistant-custom-component PyTurboJPEG==1.8.3
.venv/bin/python -m pip install -e "./lib[dev]"
```

- `PyTurboJPEG` is imported by Home Assistant's camera component. Home Assistant 2026.10 pins version 1.8.3.
- `ha-ffmpeg` is the Python package of Home Assistant's ffmpeg integration. A real install needs it for the siren and the speaker. The tests do not: they mark the ffmpeg component as loaded.

Run the tests from the repository root.

```sh
.venv/bin/python -m pytest tests/components/sannce -q
.venv/bin/python -m pytest lib/tests tests/docs -q -p no:homeassistant
```

The Home Assistant pytest plugin blocks sockets, so the library tests run without it.

To try the library alone against a camera, run `python -m sannce_aio probe HOST --pass PASSWORD` after the install above. It switches the white light on and back unless you add `--no-light`.
