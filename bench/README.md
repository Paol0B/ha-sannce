# Bench

The bench runs the integration in a real Home Assistant against a simulated camera, in Docker. It checks that our parts work together: the config flow, the bundled library, ffmpeg, stream and the manifest. It does not check that a camera speaks this protocol, because the simulator follows the same spec as the library. On hardware day it is the starting point.

## Requirements

- Linux with Docker and Compose 2. Tested with Docker 29.1.3 and Compose 2.40.3.
- The `.venv` from [Development](../README.md#development). `scripts/bench.sh` runs its Python.
- rsync. `scripts/vendor-lib.sh` copies the library into the integration with it.
- The `lib/` submodule, checked out: `git submodule update --init`. The camera image builds from it.
- About 4.5 GB of disk for the images. Home Assistant alone is 3.5 GB.
- Nothing else on `127.0.0.1:8123` or on the Docker subnet `172.31.250.0/24`.

## Commands

| Command | Effect |
|---|---|
| `scripts/bench.sh up [--host-network]` | Build and start the stack. Onboard Home Assistant and add the simulated camera if needed. Print the URL and the login. `--host-network` puts Home Assistant on the host network, see [Network modes](#network-modes). |
| `scripts/bench.sh down` | Stop the stack. Keep the Home Assistant state. |
| `scripts/bench.sh reset` | Stop, wipe `bench/ha-config/`, start fresh on the bridge. |
| `scripts/bench.sh test` | Reset, run the end-to-end suite on the bridge, then hassfest. |
| `scripts/bench.sh event KIND [on\|off]` | Push an event: `motion`, `vehicle`, `intrusion`, `line`, `tamper` or `video_loss`. The default is `on`. |
| `scripts/bench.sh audio FILE` | Save the last talk session as WAV. |
| `scripts/bench.sh hassfest` | Copy the library into the integration, then validate `custom_components/sannce` with hassfest. |

- `up` copies `lib/src/` into the integration and rebuilds the camera image. If Home Assistant is already running, `up` restarts it, because Home Assistant reads custom integrations only when it starts.
- `test` removes the camera from Home Assistant at the end. Run `up` to add it back.

## Network modes

| Mode | Command | Home Assistant | Use it for |
|---|---|---|---|
| Bridge, the default | `scripts/bench.sh up` | 172.31.250.20 on the bench network, published on 127.0.0.1:8123 | the end-to-end suite and everything except a browser |
| Host | `scripts/bench.sh up --host-network` | the host network, listening on 127.0.0.1:8123 | WebRTC in a browser on this machine: live view and two-way talk |

- WebRTC fails on the bridge. go2rtc offers the browser no host candidate for a Docker address, only a server-reflexive candidate with the router's public IP, and the router does not hairpin. The browser never connects, the live view falls back to HLS and two-way talk fails. On the host network go2rtc offers the host's addresses.
- The suite needs the bridge. In host mode the LAN search runs on the real LAN, so `test_lan_search_lists_the_camera_and_fills_its_identity` finds the real camera instead of the simulator.
- `up` with or without the option switches the mode and recreates the Home Assistant container. `test` and `reset` always use the bridge, also when the stack runs in host mode.
- Host mode adds `bench/compose.hostnet.yaml`. Both compose files set `BENCH_INTERNAL_URL` and `BENCH_SERVER_HOST` for Home Assistant. `ha-template/configuration.yaml` reads the first. `http_bind.py` runs before Home Assistant starts and writes the second into Home Assistant's http store, because Home Assistant 2026.10 reads `http:` from YAML only on its first start.
- A `bench/ha-config/` copied before host mode existed keeps the old `internal_url` line and may hold an `http:` block. Copy the `internal_url` line from `bench/ha-template/configuration.yaml`, delete the `http:` block, or run `reset`.
- Security: in host mode Home Assistant listens on 127.0.0.1 only, because the owner login is weak. go2rtc's WebRTC port 18555/tcp and its UDP ports listen on all interfaces, so other machines on the LAN can reach them.

## Addresses

| Service | Address | Login |
|---|---|---|
| Home Assistant | http://127.0.0.1:8123 in both modes, and http://172.31.250.20:8123 on the bench network in bridge mode | `dev` / `sannce-bench` |
| Camera | 172.31.250.10: private protocol 3002 over WebSocket, HTTP 80, RTSP 554, LAN search UDP 3000 and 4000 | `admin` / `admin123` |
| Control API | http://172.31.250.10:8099 | none |

- `bench/compose.yaml` sets the camera login once. The simulator and the RTSP server both take it from there.
- RTSP `/1/1` is 1280x720 H.264 with AAC audio. `/1/2` is 640x360 H.264 with G.711 A-law audio. The video is 4:2:0 (`yuv420p`), so browsers and hardware decoders accept it. Both streams show a test pattern and a 440 Hz tone, for example `rtsp://admin:admin123@172.31.250.10:554/1/2`.
- The simulator answers RTSP on 554 and relays video from mediamtx on 8554. It adds the backchannel track the real camera has and records what it receives.
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
- Run it against the bridge, not host mode.
- It writes its test audio to `bench/media/`.
- A run takes about two minutes, because the event, reconnect, reauth and WebRTC checks wait on real timers.

## Hardware day

1. `scripts/bench.sh up`.
2. In Home Assistant, add SANNCE again and type the I91FW's IP and password. On the bridge the container reaches the LAN through Docker NAT. LAN search does not cross NAT, so use the IP. With `up --host-network` the container is on the LAN, so LAN search works.
3. To check the camera without Home Assistant, run `.venv/bin/python -m sannce_aio probe IP --pass PASSWORD` from this machine.
4. Work through [docs/hardware-checklist.md](../docs/hardware-checklist.md).

`scripts/bench.sh reset` and `scripts/bench.sh test` wipe the Home Assistant config, and the end-to-end suite removes every SANNCE entry. All three delete the real camera's entry too. Add it again afterwards.

## Notes

- The demo text-to-speech engine belongs to Home Assistant's Demo integration. Loading it adds a Demo entry with demo devices. Ignore them, or disable the Demo entry.
- Home Assistant runs as root, so `bench/ha-config/` holds root-owned files. `reset` deletes them from a container.
- `bench/ha-config/` and `bench/media/` are git-ignored.
- Live view and two-way talk in a browser on this machine need `up --host-network`, see [Network modes](#network-modes).
- The suite sends go2rtc a WebRTC offer for Fluent. It checks that the answer accepts audio and that go2rtc opens the camera's backchannel. No browser takes part, so no audio flows.
- go2rtc keeps the camera's backchannel open about 30 s after a WebRTC session ends. The WebRTC test waits for it to close, so it adds about 30 s to the run.
- If the config holds another owner, `up` retries the `dev` login for up to 5 minutes, then stops with `error: signing in to http://127.0.0.1:8123 as dev: still 'login refused' after 300 s`. Run `scripts/bench.sh reset`.
