# Bench

The bench runs the integration in a real Home Assistant against a simulated camera, in Docker. It checks that our parts work together: the config flow, the bundled library, ffmpeg, stream and the manifest. It does not check that a camera speaks this protocol, because the simulator follows the same spec as the library. On hardware day it is the starting point.

## Requirements

- Linux with Docker and Compose 2. Tested with Docker 29.1.3 and Compose 2.40.3.
- The `.venv` from [Development](../README.md#development). `scripts/bench.sh` runs its Python.
- rsync. `scripts/vendor-lib.sh` copies the library into the integration with it.
- About 4.5 GB of disk for the images. Home Assistant alone is 3.5 GB.
- Nothing else on `127.0.0.1:8123` or on the Docker subnet `172.31.250.0/24`.

## Commands

| Command | Effect |
|---|---|
| `scripts/bench.sh up` | Build and start the stack. Onboard Home Assistant and add the simulated camera if needed. Print the URL and the login. |
| `scripts/bench.sh down` | Stop the stack. Keep the Home Assistant state. |
| `scripts/bench.sh reset` | Stop, wipe `bench/ha-config/`, start fresh. |
| `scripts/bench.sh test` | Reset, run the end-to-end suite, then hassfest. |
| `scripts/bench.sh event KIND [on\|off]` | Push an event: `motion`, `vehicle`, `intrusion`, `line`, `tamper` or `video_loss`. The default is `on`. |
| `scripts/bench.sh audio FILE` | Save the last talk session as WAV. |
| `scripts/bench.sh hassfest` | Validate `custom_components/sannce` with hassfest. |

- `up` copies `lib/src/` into the integration and rebuilds the camera image. If Home Assistant is already running, `up` restarts it, because Home Assistant reads custom integrations only when it starts.
- `test` removes the camera from Home Assistant at the end. Run `up` to add it back.

## Addresses

| Service | Address | Login |
|---|---|---|
| Home Assistant | http://127.0.0.1:8123, and http://172.31.250.20:8123 on the bench network | `dev` / `sannce-bench` |
| Camera | 172.31.250.10: private protocol 3000, HTTP 80, RTSP 554, LAN search UDP 3000 and 4000 | `admin` / `admin123` |
| Control API | http://172.31.250.10:8099 | none |

- `bench/compose.yaml` sets the camera login once. The simulator and the RTSP server both take it from there.
- RTSP `/1/1` is 1280x720 H.264 with AAC audio. `/1/2` is 640x360 H.264 with G.711 A-law audio. The video is 4:2:0 (`yuv420p`), so browsers and hardware decoders accept it. Both streams show a test pattern and a 440 Hz tone, for example `rtsp://admin:admin123@172.31.250.10:554/1/2`.
- Only this machine and the bench network reach the camera and the control API.

## Control API

The camera runs the simulator's control API. Its requests are in the table in [lib/README.md](../lib/README.md#simulator). For example:

```sh
curl -s http://172.31.250.10:8099/state
curl -s --json '{"kind": "motion", "active": true}' http://172.31.250.10:8099/event
curl -s --json '{"seconds": 5}' http://172.31.250.10:8099/drop
```

## End-to-end suite

`scripts/bench.sh test` is the full run. To run the suite against a bench that is already up:

```sh
.venv/bin/python -m pytest tests/e2e -q -p no:homeassistant --bench
```

- Without `--bench` the tests skip. With `--bench` and no bench, the run stops with `bench is not running: scripts/bench.sh up`.
- `tests/e2e/conftest.py` defines `--bench`, so the command line must name `tests/e2e` or a file in it. Without that path pytest stops with `unrecognized arguments: --bench`.
- The suite needs `-p no:homeassistant`, because the Home Assistant pytest plugin blocks sockets.
- Each module that uses the camera first removes every SANNCE entry, resets the simulator and adds the camera. It removes the entry again when it ends. The setup tests remove the entries and reset the simulator around each test. So do not point the suite at a Home Assistant you care about.
- It writes its test audio to `bench/media/`.
- A run takes about a minute, because the event, reconnect and reauth checks wait on real timers.

## Hardware day

1. `scripts/bench.sh up`.
2. In Home Assistant, add SANNCE again and type the I91FW's IP and password. The container reaches the LAN through Docker NAT. LAN search does not cross NAT, so use the IP.
3. To check the camera without Home Assistant, run `.venv/bin/python -m sannce_aio probe IP --pass PASSWORD` from this machine.
4. Work through [docs/hardware-checklist.md](../docs/hardware-checklist.md).

`scripts/bench.sh reset` and `scripts/bench.sh test` wipe the Home Assistant config, and the end-to-end suite removes every SANNCE entry. All three delete the real camera's entry too. Add it again afterwards.

## Notes

- The demo text-to-speech engine belongs to Home Assistant's Demo integration. Loading it adds a Demo entry with demo devices. Ignore them, or disable the Demo entry.
- Home Assistant runs as root, so `bench/ha-config/` holds root-owned files. `reset` deletes them from a container.
- `bench/ha-config/` and `bench/media/` are git-ignored.
- Live view in a browser on this machine reaches go2rtc on 172.31.250.20. The suite does not test WebRTC.
- If the config holds another owner, `up` retries the `dev` login for up to 5 minutes, then stops with `error: signing in to http://127.0.0.1:8123 as dev: still 'login refused' after 300 s`. Run `scripts/bench.sh reset`.
