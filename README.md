# SANNCE for Home Assistant

Home Assistant integration for SANNCE wired IP cameras. It talks to the camera over your LAN and needs no cloud account.

SANNCE Life cameras are Tiandy OEM devices. The reference model is the I91FW (4K, PoE, white light and infrared). Other models may work.

## Status

Not verified on hardware. The protocol comes from static analysis of the SANNCE Life app. No part of it has run on a real camera yet. The tests use a simulator built from the same spec. They show the code matches the spec, not the camera. Expect fixes after the first run.

- [docs/protocol.md](docs/protocol.md) is the protocol spec. Each claim is tagged `static`, `inferred` or `verified`. Nothing is `verified` yet.
- [docs/hardware-checklist.md](docs/hardware-checklist.md) lists the checks to run when a camera is on the bench.

## Supported devices

- SANNCE wired cameras that pair with the SANNCE Life app. They are Tiandy OEM devices and speak Tiandy's private protocol on port 3000.
- The reference model is the I91FW. No camera has run this code yet, see Status.
- Cameras for the SANNCE HOME app run a different platform. They are not supported.
- One camera per entry. NVRs are not supported: the integration uses channel 1 for settings and video.

## Requirements

- Home Assistant 2026.10 or newer. Older versions are untested.
- A camera on the same LAN, activated, with an admin password.
- TCP from Home Assistant to the camera: port 3000 (events, speaker), 80 (settings) and 554 (video).
- A fixed camera address works best. The integration can follow a new address in one case only. Home Assistant must see the camera's DHCP request. The entry must also match the camera's MAC address or serial number. See Discovery.
- The `ffmpeg` binary, for the speaker only. The siren builds its tone in Python. The official container image has ffmpeg.

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

Both machines need rsync 3.0 or newer. The SSH user must write to the config directory and run `docker`.

## Setup

Open Settings, Devices & services, Add integration, and pick SANNCE.

- Enter the camera address, user name and password. The user name defaults to `admin`.
- Or leave the address empty to search the LAN. Pick the camera, then enter its login. The search uses UDP multicast, so a container probably needs host networking.
- The ports are optional: private protocol 3000, HTTP 80, RTSP 554.
- If the password changes, Home Assistant asks for the new one.

After the login, the integration runs a short LAN search for the address you typed. If the camera answers, the entry gets the model, serial number and MAC address the login did not give. Home Assistant names the camera after its model. If it does not answer, for example across Docker NAT, Home Assistant names the camera after its address.

### Discovery

Home Assistant also finds cameras by itself. Its DHCP watcher reports devices whose MAC address starts with a prefix the IEEE registry assigns to Tiandy: `3C:DA:6D`, `BC:51:6C` or `E4:E6:6C`. It also reports a camera already in Home Assistant, whatever its prefix, when the entry stores its MAC address.

The integration runs the short LAN search for the address. A camera that answers shows up under Discovered with its model. One that does not answer shows up too, as `SANNCE (<ip>)`. The login decides: a device that is not a SANNCE camera fails it. Confirm the camera and enter its login.

When a known camera gets a new address over DHCP, the integration updates the entry and reloads it. It does so only when one of these proves it is the same camera:

- The MAC address in the DHCP request matches the one stored in the entry.
- The serial number the camera reports in the LAN search matches the entry's serial number.

An address alone never updates an entry. The integration never moves an entry to an address that another entry holds. An entry that stores neither a MAC address nor a serial number keeps its address. Home Assistant sees DHCP traffic only on the host network.

### Reconfigure

To change the address, the login or the ports, open the entry's menu and pick Reconfigure. Leave the password empty to keep the current one. The integration checks the new settings with the camera before it saves them. It refuses an address that another entry uses. It also refuses an address that answers with another camera's serial number or MAC address. A camera at a new address may report no serial number or MAC address to compare. Then nothing proves it is the same camera, so the entry drops the serial number and MAC address it stored.

## Entities

| Platform | Entity | Notes |
|---|---|---|
| `camera` | Sub stream | RTSP `/1/2`. Enabled by default. |
| `camera` | Main stream | RTSP `/1/1`. Disabled by default. |
| `binary_sensor` | Motion, Vehicle | Pushed by the camera. |
| `binary_sensor` | Intrusion, Line crossing, Tamper | Pushed by the camera. Tamper is the lens cover. Disabled by default. |
| `binary_sensor` | Video loss | Diagnostic. Disabled by default. |
| `light` | Floodlight | The white light. Off means auto, see Known limits. |
| `select` | Light mode | Infrared, Color or Smart. |
| `switch` | Person detection, Vehicle detection, Motion detection | Configuration entities. |
| `siren` | Siren | Plays a generated tone on the camera speaker. Tones `alarm` and `chime`, up to 300 s. |
| `media_player` | Speaker | Plays TTS and media-source audio on the camera speaker. Supports stop. |

The camera reports which features it has. The integration creates Motion, Vehicle, Floodlight, Light mode and the detection switches only when it does. Siren, Speaker, Intrusion, Line crossing, Tamper and Video loss always appear. Intrusion, Line crossing, Tamper and Video loss start disabled. Enable the ones you need on the device page.

## Data updates

The camera pushes its events over the private protocol, so the binary sensors change at once. The light, light mode and detection settings are read over HTTP every 60 seconds, after each command and after a reconnect. A change made in the vendor app shows up within a minute.

A dropped camera connection makes every entity unavailable, not off, until it returns. The log gets one info line when the connection drops and one when it returns. A failed settings read makes the light, the light mode and the switches unavailable. If the camera refuses the login 3 times while reconnecting, the integration stops retrying and Home Assistant asks for the password again.

## Use cases

- Get a phone notification when a vehicle stops at the gate.
- Light the yard and speak a warning when someone walks up at night.
- Sound the siren from an alarm automation.
- Turn person and vehicle detection off while you are home, and on when you leave. The camera may lock these switches, see Known limits.

## Automation examples

The entity IDs below assume the camera is named I91FW. Check yours on the device page. `notify.notify` and `tts.home_assistant_cloud` are placeholders: replace them with your own notify action and TTS entity.

Notify on a vehicle:

```yaml
automation:
  - alias: Vehicle at the gate
    triggers:
      - trigger: state
        entity_id: binary_sensor.i91fw_vehicle
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: A vehicle is at the gate.
```

Light the yard and speak a warning at night, then hand the lamp back to the camera after two minutes:

```yaml
automation:
  - alias: Warn at night
    triggers:
      - trigger: state
        entity_id: binary_sensor.i91fw_motion
        to: "on"
    conditions:
      - condition: state
        entity_id: sun.sun
        state: below_horizon
    actions:
      - action: light.turn_on
        target:
          entity_id: light.i91fw_floodlight
      - action: tts.speak
        target:
          entity_id: tts.home_assistant_cloud
        data:
          media_player_entity_id: media_player.i91fw_speaker
          message: You are on camera.
      - delay: "00:02:00"
      - action: light.turn_off
        target:
          entity_id: light.i91fw_floodlight
```

Sound the siren for 30 seconds:

```yaml
action: siren.turn_on
target:
  entity_id: siren.i91fw_siren
data:
  tone: alarm
  duration: 30
```

## Known limits

- **Floodlight off means auto.** Turning the light off hands the lamp back to the camera. It does not force the lamp off. The entity reads on only while the lamp is forced on. A lamp the camera lit by itself reads off. To stop the camera lighting the lamp, set Light mode to Infrared.
- **No person sensor.** The camera sends motion and vehicle events, not a person event. A person most likely arrives as plain Motion. Person detection is a switch that turns the camera's person filter on or off. Check 6.3 of the hardware checklist looks for a real person source, such as ONVIF.
- **Detection switches may be locked.** The Motion detection switch writes only the camera's all-motion flag. The vendor app sets person and vehicle together with that flag and locks them while it is on. The app also refuses to turn person and vehicle off in Smart light mode. The camera may enforce the same rules. Then the person and vehicle switches can read off while the camera treats them as on. Some changes can fail. Not verified. Check 9.7 of the hardware checklist covers it. The protocol spec has details in its Light mode and Motion detection sections.
- **Siren and speaker replies are inferred.** Both send audio over the camera's talk channel. The camera's replies to start, refuse and end come from the vendor SDK code, not from a camera. The library always reports the talk capability. Every camera gets a siren and a speaker, even one without a speaker. One sound plays at a time, and a new sound replaces the current one. Stopping the speaker does not stop the siren.
- **Rule sensors may stay silent.** Intrusion, Line crossing, Tamper and Video loss exist on every camera. The I91FW may never send those events, so they start disabled. Enable the ones you need.
- **Events clear on a timer.** The camera may not send a stop event. A sensor turns off 10 seconds after the last start.
- **Customize light mode reads as unknown.** The integration reads the vendor app's Customize mode but cannot set it.
- **No encryption.** The private login sends the password in base64, and the RTSP URL carries it. Use a trusted LAN.
- **DHCP prefixes are unconfirmed.** They come from the IEEE registry, not from a camera. Check 8.3 of the hardware checklist confirms them.

## Troubleshooting

- **Cannot reach the camera.** Check that Home Assistant reaches ports 3000, 80 and 554 on the camera, for example with `nc -vz IP 3000`.
- **Login failed.** The user name is usually `admin`. Use the password set when the camera was activated. After a password change, Home Assistant asks for the new one.
- **The LAN search finds nothing.** The search uses UDP multicast on ports 3000 and 4000. A Home Assistant container needs host networking for it. Type the address instead.
- **The camera is not discovered.** Home Assistant sees DHCP traffic only on the host network. The camera's MAC address must start with one of the prefixes under Discovery.
- **Entities are unavailable.** The camera connection dropped. The log says `Camera IP is unavailable`. The integration keeps retrying and waits up to 60 seconds between tries.
- **A rule sensor never turns on.** Intrusion, Line crossing, Tamper and Video loss start disabled. The camera may also never send those events.
- **The speaker stays silent.** It needs the `ffmpeg` binary. The log names the ffmpeg error.
- **The siren will not start.** The service call fails with the camera's reason, for example that it refused talk. A failure after the tone has started only appears in the log.

For more detail, turn on debug logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.sannce: debug
```

When you report a problem, attach the diagnostics file from the device page. It redacts the host, user name, password, serial number and MAC address.

## Remove

1. Open Settings, Devices & services, SANNCE.
2. In the entry's menu, pick Delete. Home Assistant closes the camera sessions and removes the device and its entities.
3. To remove the code too, remove SANNCE in HACS, or delete `<config>/custom_components/sannce` for a manual install. Then restart Home Assistant.

## Quality scale

The integration marks every rule of the Home Assistant integration quality scale, up to Platinum, as done or exempt, except two rules that need publication: brands and dependency-transparency. Hassfest checks seven of the rules. The others rest on the file, the tests and mypy. Home Assistant grades only core integrations, so there is no official badge. [custom_components/sannce/quality_scale.yaml](custom_components/sannce/quality_scale.yaml) gives the status of every rule.

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

The camera library `sannce-aio` lives in `lib/` ([lib/README.md](lib/README.md)). A copy sits in `custom_components/sannce/sannce_aio/`, without the simulator, its control API and the CLI. Only `custom_components/sannce/lib.py` imports it. `manifest.json` lists no requirements until the library is on PyPI.

After you change `lib/src/`, run `scripts/vendor-lib.sh`. `scripts/deploy.sh` runs it too.

What CI runs, how to publish the library and what is still open are in [docs/release.md](docs/release.md).

The test tools need Python 3.14.2 or newer, as Home Assistant 2026.10 does.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` pins the test tools, mypy and an editable install of `lib/`. CI installs the same file.

- `PyTurboJPEG` is imported by Home Assistant's camera component. Home Assistant 2026.10 pins version 1.8.3.
- `ha-ffmpeg` is the Python package of Home Assistant's ffmpeg integration. A real install needs it, because the manifest requires the ffmpeg integration. The siren tone itself is built in Python. The test suite mocks the ffmpeg component, so the tests do not need it.
- `av` (PyAV) is the Python package of Home Assistant's stream integration. The manifest requires stream, because camera snapshots come from the stream. The test suite mocks the stream component too.

Type checking uses mypy in strict mode, with the settings in `mypy.ini`.

```sh
.venv/bin/python -m mypy
```

Run the tests from the repository root.

```sh
.venv/bin/python -m pytest tests/components/sannce -q
.venv/bin/python -m pytest lib/tests tests/docs -q -p no:homeassistant
```

The Home Assistant pytest plugin blocks sockets, so the library tests run without it.

`scripts/quality.sh` runs mypy, mypy again on the library as Python 3.11, the unit tests with at least 95 % line coverage per module, and hassfest's quality scale check. Hassfest checks `quality_scale.yaml` only for core integrations, so the script copies the integration into the hassfest image as a core integration that declares Platinum. It passes when hassfest reports only brands and dependency-transparency, and `quality_scale.yaml` matches its tests. It needs Docker.

To try the library alone against a camera, run `python -m sannce_aio probe HOST --pass PASSWORD` after the install above. It switches the white light on and back unless you add `--no-light`.

## Bench

`scripts/bench.sh up` starts Home Assistant 2026.10.1 and a simulated camera in Docker, with this integration loaded. `scripts/bench.sh test` starts them fresh, then runs the end-to-end suite and hassfest. See [bench/README.md](bench/README.md).
