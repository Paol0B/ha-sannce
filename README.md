# SANNCE for Home Assistant

Home Assistant integration for SANNCE wired IP cameras. It talks to the camera over your LAN and needs no cloud account.

SANNCE Life cameras are Tiandy OEM devices. The reference model is the I91FW (4K, PoE, white light and infrared). The camera reports it as I91FX. Other models may work.

## Status

Measured on the I91FX by hand (SANNCE I91FX, sold as I91FW, firmware `NVSS_V29.0.23.20250330`, 2026-10-15): login, motion and person events, floodlight, built-in sounds, and sound through the RTSP backchannel.

The acceptance run with Home Assistant on that camera is done (2026-10-15):

- Two walk-bys turned Person and Motion on for about 15 s, then off.
- On the video, the floodlight goes on, to 30 % and off.
- Volume drives the speaker. Motion sensitivity and Siren on event reach the camera.
- The generated `alarm` tone is heard and stops at once on turn_off. TTS through the speaker is heard.
- Two-way talk from the wall card works twice in a row through the RTSP relay, with the live view up and Home Assistant on the host network. On a Docker bridge network WebRTC does not connect, see Live push-to-talk.

Not verified on the camera:

- The vehicle event and tamper.
- Whether turn_off cuts a spoken warning short, and whether a warning is longer than the 5 s replay interval.
- Whether motion plays the sound that Siren on event links.
- The camera's light mode after the floodlight goes off.
- Clear and Fluent each playing in a dashboard.

[docs/hardware-checklist.md](docs/hardware-checklist.md), Acceptance, has each result.

Everything else comes from the vendor app's code and from the simulator the tests use. The simulator follows the same spec as the code, so it shows the code matches the spec, not the camera.

- [docs/protocol.md](docs/protocol.md) is the protocol spec. Each claim is tagged `static`, `inferred` or `verified`. The I91FX results are `verified`.
- [docs/hardware-checklist.md](docs/hardware-checklist.md) lists the checks to run when a camera is on the bench.

## Supported devices

- SANNCE wired cameras that pair with the SANNCE Life app. They are Tiandy OEM devices and speak Tiandy's private protocol. The I91FX carries it over a WebSocket on port 3002.
- The reference model is the I91FW. Only the I91FX has been measured, see Status.
- Cameras for the SANNCE HOME app run a different platform. They are not supported.
- One camera per entry. NVRs are not supported: the integration uses channel 1 for settings and video.

## Requirements

- Home Assistant 2026.10 or newer. Older versions are untested.
- A camera on the same LAN, activated, with an admin password.
- TCP from Home Assistant to the camera: port 3002 (events), 80 (settings) and 554 (video and speaker).
- A fixed camera address works best. The integration can follow a new address in one case only. Home Assistant must see the camera's DHCP request. The entry must also match the camera's MAC address or serial number. See Discovery.
- The `ffmpeg` binary, for the Speaker only. The siren needs none. The official container image has ffmpeg.

## Install

### HACS

HACS cannot install the integration yet. HACS downloads only the files git tracks, and the camera library copy is not one of them. HACS works once `sannce-aio` is on PyPI and `manifest.json` lists it under `requirements`, see [docs/release.md](docs/release.md#after-the-first-pypi-release). Until then, use Manual or Container, over SSH.

### Manual

Clone the repository with its `lib` submodule, as Development says, and run `scripts/vendor-lib.sh`. It copies the camera library into `custom_components/sannce/sannce_aio/` with rsync. Then copy `custom_components/sannce` to `<config>/custom_components/sannce` and restart Home Assistant. Nothing else needs installing.

### Container, over SSH

```sh
scripts/deploy.sh HOST [CONTAINER] [CONFIG_PATH]
ENGINE=podman scripts/deploy.sh HOST homeassistant /path/to/config
```

The script copies the camera library into the integration with `scripts/vendor-lib.sh`, copies `custom_components/sannce` to `HOST` with rsync, then restarts the container. It needs the `lib` submodule, see Development.

| Argument | Meaning | Default |
|---|---|---|
| `HOST` | SSH target, for example `root@ha.local` | required |
| `CONTAINER` | container name | `homeassistant` |
| `CONFIG_PATH` | config directory on `HOST`, the one the container mounts as `/config` | `/config` |

The environment variable `ENGINE` picks the container engine: `docker` (default) or `podman`. Any other value stops the script before it copies anything.

Both machines need rsync 3.0 or newer. The SSH user must write to the config directory and run the engine.

## Setup

Open Settings, Devices & services, Add integration, and pick SANNCE.

- Enter the camera address, user name and password. The user name defaults to `admin`.
- Or leave the address empty to search the LAN. Pick the camera, then enter its login. The search uses UDP multicast, so a container probably needs host networking.
- The ports are optional: web port 3002, HTTP port 80, RTSP port 554. The web port is the camera's WebSocket, used for events. An entry made with an earlier version moves from port 3000 to 3002 when Home Assistant starts. Another port stays as it is.
- If the password changes, Home Assistant asks for the new one.

After the login, the integration runs a short LAN search for the address you typed. If the camera answers, the entry gets the model, serial number and MAC address the login did not give. Home Assistant names the camera after its model. If it does not answer, for example across Docker NAT, Home Assistant names the camera after its address.

### Discovery

Home Assistant also finds cameras by itself. Its DHCP watcher reports devices whose MAC address starts with a prefix the IEEE registry assigns to Tiandy: `3C:DA:6D`, `BC:51:6C` or `E4:E6:6C`, or with `D0:3B:F4`, the prefix of the I91FX. It also reports a camera already in Home Assistant, whatever its prefix, when the entry stores its MAC address.

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
| `camera` | Clear | RTSP `/1/1`, the main stream. |
| `camera` | Fluent | RTSP `/1/2`, the sub stream. |
| `binary_sensor` | Motion, Person, Vehicle | Pushed by the camera. Motion is on during a motion or vehicle event. Person is unavailable while the Motion detection switch is on. |
| `binary_sensor` | Intrusion, Line crossing, Tamper | Pushed by the camera. Tamper is the lens cover. Disabled by default. |
| `binary_sensor` | Video loss | Diagnostic. Disabled by default. |
| `light` | Floodlight | On, off and brightness. See Known limits. |
| `select` | Floodlight mode | Infrared, Color or Smart. The mode the camera returns to when the Floodlight goes off. |
| `siren` | Siren | Default tone `alarm`: a generated siren, 800 and 1000 Hz, through the camera speaker. Tones `sound_1` to `sound_N` are the camera's spoken warnings, replayed every 5 s. Up to 300 s. |
| `switch` | Person detection, Vehicle detection, Motion detection | Configuration entities. |
| `switch` | Siren on event | Configuration entity. Makes the camera play its first spoken warning on motion. Off by default, and the integration never turns it on. |
| `number` | Volume, Motion sensitivity | Configuration entities, 0 to 100. Volume sets the speaker loudness, for the siren and the Speaker. Verified on the I91FX: quieter at 30 %. |
| `media_player` | Speaker | Plays TTS and media-source audio on the camera speaker. Supports stop. |

The camera reports which features it has. The integration creates an entity only when the camera has its feature. That covers Motion, Person, Vehicle, Floodlight, Floodlight mode, Siren, Speaker, the switches and the numbers. The Speaker and the `alarm` tone need the RTSP backchannel. Clear, Fluent, Intrusion, Line crossing, Tamper and Video loss always appear. Intrusion, Line crossing, Tamper and Video loss start disabled. Enable the ones you need on the device page.

## Data updates

The camera pushes its events over the private protocol, so the binary sensors change at once. The floodlight, its mode, the detection switches, Siren on event, Volume and Motion sensitivity are read over HTTP every 60 seconds, after each command and after a reconnect. A change made in the vendor app shows up within a minute.

A dropped camera connection makes every entity unavailable, not off, until it returns. The log gets one info line when the connection drops and one when it returns. A failed settings read makes the light, the select, the switches and the numbers unavailable. If the camera refuses the login 3 times while reconnecting, the integration stops retrying and Home Assistant asks for the password again.

## Use cases

- Get a phone notification when a vehicle stops at the gate.
- Light the yard and speak a warning when someone walks up at night.
- Sound the siren from an alarm automation.
- Turn person and vehicle detection off while you are home, and on when you leave. The camera may lock these switches, see Known limits.

## Automation examples

The entity IDs below assume the camera is named I91FX. Check yours on the device page. `notify.notify` and `tts.home_assistant_cloud` are placeholders: replace them with your own notify action and TTS entity.

Notify on a vehicle:

```yaml
automation:
  - alias: Vehicle at the gate
    triggers:
      - trigger: state
        entity_id: binary_sensor.i91fx_vehicle
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: A vehicle is at the gate.
```

Light the yard and speak a warning at night, then turn the lamp off after two minutes. The camera returns to the mode in Floodlight mode:

```yaml
automation:
  - alias: Warn at night
    triggers:
      - trigger: state
        entity_id: binary_sensor.i91fx_motion
        to: "on"
    conditions:
      - condition: state
        entity_id: sun.sun
        state: below_horizon
    actions:
      - action: light.turn_on
        target:
          entity_id: light.i91fx_floodlight
      - action: tts.speak
        target:
          entity_id: tts.home_assistant_cloud
        data:
          media_player_entity_id: media_player.i91fx_speaker
          message: You are on camera.
      - delay: "00:02:00"
      - action: light.turn_off
        target:
          entity_id: light.i91fx_floodlight
```

Sound the siren for 30 seconds:

```yaml
action: siren.turn_on
target:
  entity_id: siren.i91fx_siren
data:
  tone: alarm
  duration: 30
```

## Known limits

- **Floodlight on rewrites the camera's timed window.** The camera refuses a plain manual on. The integration lights the lamp with a timed window from 00:00 to 23:59, in Color mode, so the lamp goes dark for that one minute at 23:59. A camera that used its own timed light mode loses its window.
- **Floodlight off returns to the Floodlight mode.** Turning the light off moves the camera to the mode the Floodlight mode select shows. The entity reads on only while the lamp is forced on. A lamp the camera lit by itself reads off. To stop the camera lighting the lamp, set Floodlight mode to Infrared.
- **Custom light mode.** If the camera is left in the vendor app's Custom light mode, Floodlight mode shows the last mode chosen in Home Assistant. Turning the floodlight off then moves the camera to that mode. The integration cannot set Custom.
- **Person needs all-motion detection off.** Person is unavailable while the camera's all-motion detection (the Motion detection switch) is on, because the camera does not tell a person from other motion then. There is no animal detection, no recording switch and no push-notification switch.
- **Detection switches may be locked.** The Motion detection switch writes only the camera's all-motion flag. The vendor app sets person and vehicle together with that flag and locks them while it is on. The app also refuses to turn person and vehicle off in Smart light mode. The camera may enforce the same rules. Then the person and vehicle switches can read off while the camera treats them as on. Some changes can fail. Not verified. Check 9.7 of the hardware checklist covers it. The protocol spec has details in its Light mode and Motion detection sections.
- **The built-in tones are spoken warnings.** `sound_1` to `sound_3` are the camera's recorded voice messages, not a siren. The siren sends the chosen one again every 5 s until the duration ends or you turn it off, up to 300 s. The stop action and the length of each message are not yet confirmed on the camera.
- **The siren and the Speaker share the camera speaker.** It plays one sound at a time. A Speaker play (TTS or media) stops the `alarm` tone and turns the siren off. Turning the siren on with `alarm` stops a Speaker play. Stopping the Speaker leaves the siren alone.
- **go2rtc holds the speaker channel.** After a two-way audio (WebRTC) session, Home Assistant's go2rtc keeps the camera's audio channel open for about 30 s. A speaker play in that window may be refused.
- **A dropped live view may stay open.** After a network drop during a live view that followed a talk, go2rtc may keep the camera stream open with no viewer until Home Assistant restarts.
- **Two talkers mix.** Two people talking at the same time on the same camera mix their audio.
- **Rule sensors may stay silent.** Intrusion, Line crossing, Tamper and Video loss exist on every camera. The I91FX may never send those events, so they start disabled. Enable the ones you need.
- **Events clear on a timer.** The camera sends one stop at the end of an event. If a stop is lost, a sensor turns off 10 seconds after the last start.
- **The camera clock needs NTP.** Set up NTP on the camera. Without it the I91FX clock read year 2000 after a reboot. Event times in Home Assistant use Home Assistant's own clock.
- **No encryption.** The WebSocket is plain `ws://`. The first login message sends the password in base64, and the RTSP URL carries it. Use a trusted LAN.
- **Most DHCP prefixes are unconfirmed.** `3C:DA:6D`, `BC:51:6C` and `E4:E6:6C` come from the IEEE registry, not from a camera. Check 8.3 of the hardware checklist confirms them. `D0:3B:F4` is the I91FX's own.

## Troubleshooting

- **Cannot reach the camera.** Check that Home Assistant reaches ports 3002, 80 and 554 on the camera, for example with `nc -vz IP 3002`.
- **Login failed.** The user name is usually `admin`. Use the password set when the camera was activated. After a password change, Home Assistant asks for the new one.
- **The LAN search finds nothing.** The search uses UDP multicast on ports 3000 and 4000. A Home Assistant container needs host networking for it. Type the address instead.
- **The camera is not discovered.** Home Assistant sees DHCP traffic only on the host network. The camera's MAC address must start with one of the prefixes under Discovery.
- **Entities are unavailable.** The camera connection dropped. The log says `Camera IP is unavailable`. The integration keeps retrying and waits up to 60 seconds between tries.
- **A rule sensor never turns on.** Intrusion, Line crossing, Tamper and Video loss start disabled. The camera may also never send those events.
- **The Speaker entity is missing.** It appears only when the camera offers the RTSP backchannel on `/1/1`.
- **The speaker stays silent.** It needs the `ffmpeg` binary. The log names the ffmpeg error. A play right after a WebRTC session may be refused, see Known limits.
- **The siren will not start.** The service call fails with the camera's reason. A failure after the start only appears in the log.

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

Home Assistant's own go2rtc carries your voice to the camera. It reads `camera.<base>_fluent` over RTSP and opens the camera's ONVIF backchannel. Any card with a microphone button works, such as WebRTC Camera or camera-wall-card. Open the dashboard over HTTPS, because browsers block the microphone on plain HTTP.

Video reaches go2rtc through a small RTSP relay in the integration, on `127.0.0.1` and a free port. Both camera entities give the relay's URL, with the camera's login and path. The relay passes the stream unchanged. go2rtc sets up the backchannel again for each new talk on a stream it already reads, and the camera refuses that repeat. The relay answers it in the camera's place, so talk works more than once. Home Assistant's built-in go2rtc runs on the same host and reaches the relay. A go2rtc server on another host cannot. The Speaker and the siren open their own connection to the camera.

The bench checks that go2rtc accepts audio from a client and opens the backchannel of the simulated camera, also for a second talk while the first is attached. No browser takes part, so no audio flows there. On the I91FX, talk from the wall card works twice in a row with the live view up, with Home Assistant on the host network. On a Docker bridge network WebRTC does not connect, because go2rtc offers no host candidate for a Docker address.

## Development

The camera library `sannce-aio` is the git submodule `lib/`, from the repository `Paol0B/sannce-aio` ([lib/README.md](lib/README.md)). Clone with it:

```sh
git clone --recurse-submodules https://github.com/Paol0B/ha-sannce.git
```

In a clone made without `--recurse-submodules`, run `git submodule update --init`. After a pull that moves `lib`, run `git submodule update`.

`scripts/vendor-lib.sh` copies the library into `custom_components/sannce/sannce_aio/`, without the simulator, its control API and the CLI. Git ignores that copy. Only `custom_components/sannce/lib.py` imports it. `manifest.json` lists no requirements until the library is on PyPI.

Run `scripts/vendor-lib.sh` before mypy and the Home Assistant tests, and again after `lib/` changes. `scripts/quality.sh`, `scripts/bench.sh` and `scripts/deploy.sh` run it themselves.

To change the library:

1. `git submodule update` leaves `lib/` on a detached HEAD. Run `git -C lib switch master`, or make a branch there.
2. Commit in `lib/` and push to `sannce-aio`. CI here fails while the `lib` commit is not on master of `sannce-aio`.
3. In this repository, `git add lib` and commit the new pointer. `git push --recurse-submodules=check` refuses to push while the `lib` commit is not pushed.

What CI runs, how to release the library and what is still open are in [docs/release.md](docs/release.md).

The test tools need Python 3.14.2 or newer, as Home Assistant 2026.10 does.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` pins the test tools, mypy and an editable install of `lib/`. CI jobs `quality` and `e2e` install that file. The `library` job installs only `./lib[dev]`. The `hassfest` and `hacs` jobs install no Python packages.

- `PyTurboJPEG` is imported by Home Assistant's camera component. Home Assistant 2026.10 pins version 1.8.3.
- `ha-ffmpeg` is the Python package of Home Assistant's ffmpeg integration. A real install needs it, because the manifest requires the ffmpeg integration. The speaker uses it. The test suite mocks the ffmpeg component, so the tests do not need it.
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

To try the library alone against a camera, run `python -m sannce_aio probe HOST --pass PASSWORD` after the install above. It switches the white light on and back unless you add `--no-light`. Forcing the lamp on rewrites the camera's timed window, and the probe does not restore it.

## Bench

`scripts/bench.sh up` starts Home Assistant 2026.10.1 and a simulated camera in Docker, with this integration loaded. `scripts/bench.sh test` starts them fresh, then runs the end-to-end suite and hassfest. A browser on this machine needs `scripts/bench.sh up --host-network` for WebRTC. See [bench/README.md](bench/README.md).
