# Hardware checklist

Run these checks when the camera arrives (work order step 4). Each check gives:

- the examples it confirms;
- the open questions of `protocol.md` it answers;
- the command or capture to run;
- the result `protocol.md` predicts.

The examples live in `protocol-examples.json`. Their `uncertain` field lists what is guessed: read it first.

A check marked **Done** ran on an I91FX on 2026-10-15, and its Result block holds the measured values. Its steps stay for another camera. A check marked **Partly done** answered only some of its points. A section marked **Superseded** tests a path the integration no longer uses.

The I91FX serves the private protocol in a WebSocket on port 3002, and port 3000 is closed. The captures and filters below were written for plain TCP on port 3000. On the I91FX use port 3002. The client's WebSocket frames are masked, so a text filter such as `frame contains "LOGON"` matches camera frames only.

Replace `IP` with the camera address and `PW` with the admin password. Percent-encode special characters of `PW` inside URLs. Activate the camera and set its admin password before you start. Put the PC and the phone on the camera's LAN.

## 1. Camera-level checks

### 1.1 Ports and RTSP streams

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Ports and connections"):

- Open ports: 80, 443, 554, 3001 and 3002. Port 3000 refuses connections, before and after activation. The expectation below that port 3000 is open was wrong.
- Port 3001 accepts a TCP connection and answers nothing to a `LOGON`. Port 3002 serves the web player's WebSocket, which carries the private protocol.
- `/1/1` is HEVC 3840x2160 at 20 fps with PCMA 8 kHz mono. `/1/2` is HEVC 704x576 at 20 fps with PCMA 8 kHz. RTSP uses a Digest login.
- A full TCP port scan made the camera stop answering the scanning host for about a minute. Scan only the ports you need.

Steps, for another camera:

```sh
nmap -p 80,443,554,3000 IP
ffprobe -rtsp_transport tcp "rtsp://admin:PW@IP:554/1/1"
ffprobe -rtsp_transport tcp "rtsp://admin:PW@IP:554/1/2"
```

Expect ("Ports and connections", "Channel numbering"):

- Port 3000 is open: the private protocol.
- Port 554 is open: RTSP.
- Port 80 is open: the web server for the HTTP API (inferred).
- Port 443: `protocol.md` makes no claim. Record its state.
- Both `ffprobe` calls open a stream. `/1/1` should be the main stream and `/1/2` the sub stream. Record the codec, the resolution and the audio track of each.

### 1.2 RTSP channel numbering

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Channel numbering"): `/0/1` fails with 401.

Steps, for another camera:

```sh
ffprobe -rtsp_transport tcp "rtsp://admin:PW@IP:554/0/1"
```

Expect a failure. RTSP channels start at 1 ("Channel numbering").

## Captures and notes

Later checks read these captures. Take each one once and reuse it.

**App capture** shows what the official app sends.

1. In SANNCE Life, add the camera by IP address with port 3000. Do not use a QR code or a cloud account: that path may not talk to the camera on the LAN.
2. In PCAPdroid, select SANNCE Life as the target app, set the dump mode to PCAP file and start the capture.
3. Do in the app what the check says. Force-stop the app first when the check needs a fresh login.
4. Stop PCAPdroid and copy the PCAP file to the PC as `app.pcap`.

PCAPdroid relays each connection itself, so its TCP segment boundaries are not the camera's. It may also not forward UDP multicast. Use the PC capture for both.

**PC capture** shows the exact wire behaviour of the PC's own session.

```sh
sudo tcpdump -i any -s 0 -w pc.pcap host IP and tcp port 3000
```

Run it while the library probe (`python -m sannce_aio probe IP`) or a script built on `nvs/protocol.py` talks to the camera.

Open either file in Wireshark with the filter `tcp.port == 3000`. To read one stream as hex, right-click a packet and choose Follow, TCP Stream, Hex Dump.

Notes:

- A capture holds the password (base64 is not encryption) and the serial number. Replace both before you commit one.
- Copy the model, the serial number and the MAC from the camera label. Checks 4.5 and 8.2 search for them.
- Before a check changes a setting, save its current value. Put it back afterwards.
- Run the checks marked "run last" after all others. They can drop the connection or lock the account.

## 2. Framing

### 2.1 Header, sequence numbers and the camera's first fields

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Login", "Delimiting messages"):

- The camera echoes the first field of the client's `LOGON`. The web player sends the fixed address `192.168.0.2`.
- The route is `IP` on the login replies and `INNER LOGON FINISHED`, and `PROXY` on `MOTIONDETECT` events, idle messages and the `VIDEOLOST` message after login. The route of the other alarm kinds was not seen.
- One WebSocket binary message from the camera can hold several frames.
- Not recorded: header bytes 4-5 and 8-17 of camera frames, and the client sequence numbers. The sequence numbers of the examples stay guesses.

Steps, for another camera:

Confirms: `framing_two_messages_one_read`. Settles the guessed sequence numbers of `framing_parameter_get_request` (1), `heartbeat_request` (2), `logoff_request` (5), `talk_start_request` (8) and `talk_stop_request` (12).

Answers:
> framing: What does the camera put in the first field and the route field of its own messages? (blocks: test fixtures for the frame decoder)

Take a PC capture of a login plus 60 seconds of idle time. List the segments:

```sh
tshark -r pc.pcap -Y 'tcp.port == 3000 && tcp.len > 0' -T fields -e frame.time_relative -e ip.src -e tcp.len -e tcp.payload
```

Expect ("Packet header", "Delimiting messages"):

- Every command packet starts with `f1 f5 ea f5`. The total length at offset 6 gives the start of the next packet.
- Client sequence numbers start at 0 and rise by 1 per client packet, heartbeats included.
- Count the `USER LOGON` packets before the first heartbeat. `framing_parameter_get_request` assumes one and `heartbeat_request` assumes two.
- The camera's route field is `IP` or `PROXY`. Record its first field and its header bytes 4-5 and 8-19.
- Find a segment that holds two camera packets, or one packet split over two segments. The login reply is a candidate. The receiver rule must split both. If none occurs, record that.

### 2.2 Sequence and length fields (run last)

Answers:
> framing: Does the camera check the sequence number or the payload length at offset 18 of a command header? (blocks: frame encoder)

After login, send the `framing_parameter_get_request` message three times:

- unchanged;
- with the sequence number (bytes 4-5) set to `ffff`;
- with the payload length (bytes 18-19) set to `0000`.

Encode the message with the library, patch the bytes and send. Record the traffic:

```sh
sudo tcpdump -i any -s 0 -w seq.pcap host IP and tcp port 3000
```

Expect: `protocol.md` makes no camera-side claim. The vendor client ignores both fields on receive. If all three sends get the same reply, the camera ignores both fields. If the second or third gets no reply or closes the connection, the camera checks that field.

### 2.3 GETPARAM type 20

Confirms: `framing_parameter_get_request`.

Answers:
> framing: Does `GETPARAM` type 20 return `INNER PARAGET PTZ_PROTOCOL`, and how is its channel range written before the COM port, address and device-type fields? (blocks: device info)

Look for the request in the app capture with the filter `tcp.port == 3000 && frame contains "GETPARAM"`. If the app sends none, send the example from the PC after login. Read the reply with `tcp.port == 3000 && frame contains "PTZ_PROTOCOL"`.

Expect ("Reading one parameter"): `INNER PARAGET PTZ_PROTOCOL ...`, then `INNER CMD GETPARAM FINISHED 2 0`. The session id in `FINISHED` echoes the request. Record the reply fields in order: channel range, COM port, address, device-type string. A different reply name, such as `DEVICETYPE`, disproves the claim.

### 2.4 Charset

Answers:
> framing: Which charset does the I91FW report, and does it accept UTF-8 in text fields? (blocks: device and channel names)

Take an app capture of a login. Use the filter `tcp.port == 3000 && (frame contains "GB2312" || frame contains "UTF-8")`. The camera packet that holds the name is its function report. Then rename the channel in the app to a name with an accented letter, if the app allows it. Read the name back in the capture and in the picture overlay.

Expect ("Text encoding"): the report names `UTF-8` or `GB2312`. With `UTF-8`, the accented letter travels as UTF-8 bytes in both directions (`c3 a9` for e with an acute accent). With `GB2312`, decode the names the camera sends as GB2312. To test UTF-8 on such a camera, send the name as UTF-8 from the PC and read it back: garbled text means the camera does not accept UTF-8. The app's rename may not test this, because the app converts OSD text to the device charset before it sends.

## 3. Transport

### 3.1 Data connections

Answers:
> transport: Which transport (TCP, UDP or multicast) does the app use for video and talk data channels? (blocks: talk channel)

Take an app capture: open live view, then hold talk for 5 seconds. List the conversations with the camera and the `CONNECT` messages:

```sh
tshark -r app.pcap -q -z conv,tcp,ip.addr==IP -z conv,udp,ip.addr==IP
tshark -r app.pcap -Y 'frame contains "CONNECT"' -T fields -e frame.number -e ip.dst -e tcp.dstport
```

Expect ("Ports and connections", "Transport: the command connection, not a new socket"):

- Each video stream is a second TCP connection to `IP:3000` that starts with `CONNECT`.
- Talk audio travels on the command connection as data packets (`tcp.payload contains f1:f5:ea:f9`), with no new connection.
- UDP flows to the camera mean a UDP data channel. Record the ports.

## 4. Login

### 4.1 Login path: plaintext or encrypted

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Login"):

- The I91FX asks for a salted MD5 login. The base64 `LOGON` gets `LOGONFAILED 3` and an 8-byte salt. A second `LOGON` with `md5(user+salt)` and `md5(pass+salt)` in base64 gets `INNER CMDID`, the channel data and `INNER LOGON FINISHED`. The algorithm comes from the camera's web player, `/external/noplugin-master/h5player.js.gz`.
- The library's `SaltedLogin` does this. The plaintext second phase is not used.
- The app's own second phase was not captured.
- `logon_request`, `logon_reply_needs_md5`, `logon_md5_request` and `logon_reply_success` are `verified`.

The steps below are for another camera.

Confirms: `logon_request`, `logon_reply_needs_md5`, `logon_md5_request`, `logon_reply_success`.

Answers:
> login: Which second LOGON phase does the camera ask for: salted MD5, plain or encrypted? The encrypted path is out of scope. (blocks: encrypted login)

Take a PC capture while the library probe logs in (`python -m sannce_aio probe IP`). Compare the messages with the four examples above. A first reply of `LOGONFAILED 3` means the camera wants the salted MD5 login, which `SaltedLogin` does. Any other reply means the camera needs another login. Then force-stop SANNCE Life, start an app capture, and open the camera. Use the filter `tcp.port == 3000 && frame contains "LOGON"`, and diff the app's `LOGON` bytes against the library's. Record the second phase in full, with the password redacted.

Expect ("Login"): `protocol.md` documents both phases of the I91FX login.

### 4.2 Credential encoding

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("LOGON request"): F5 and F6 of the first request are the base64 of the user name and the password. The camera accepted that form. A wrong password was refused only after the MD5 request (see 4.4). Not tested: a TAB or a non-ASCII letter in the password, so `logon_request_password_with_tab` stays `inferred`.

Steps, for another camera:

Confirms: `logon_request_password_with_tab`.

Decode F5 and F6 from the 4.1 capture. Replace `F6_FROM_CAPTURE` with the field text:

```sh
echo 'F6_FROM_CAPTURE' | base64 -d | xxd
```

Expect ("LOGON request"): the user name and the password as typed. No literal TAB sits inside F5 or F6.

Optional: set a test password with a non-ASCII letter, if the app and the camera accept one. Write the new password down first. Log in with the app and decode F6: it should hold the UTF-8 bytes. Most cameras refuse a TAB in a password. If the app or the web page refuses one, record "TAB not testable": the base64 rule covers it. Change the password back afterwards.

### 4.3 Logoff

Confirms: `logoff_request`.

After the 4.1 capture, close the camera view in the app. Use the filter `tcp.port == 3000 && frame contains "LOGOFF"`.

Expect ("LOGOFF request"):

- After a plain second phase: `<ip> IP USER LOGOFF admin`, with the user name in clear.
- After an encrypted second phase: an encrypted user name.
- After a first-phase-only login: no `LOGOFF`.
- Record the real sequence number. The example guesses 5.

### 4.4 Failure replies (run last)

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Refusal"): one wrong password, one attempt only, to avoid a lockout. The camera answered the first request with `LOGONFAILED 3` as usual. It answered the MD5 request with `<ip> IP INNER USER LOGONFAILED 2 1 1 <salt> 1 0`: reason 2, bad credentials (`logon_reply_refused`). The web player stops retrying on reasons 2 and 4. Not tried: an account lock (`LOGONLOCK`) and too many users.

Answers:
> login: What does the camera send for an account lock (`LOGONLOCK`) and for too many users? (blocks: auth error mapping)

Take an app capture of one login with a wrong password. Use the filter `tcp.port == 3000 && frame contains "LOGON"`. Record the camera's reply bytes after each `USER LOGON`.

Optional, and only on your own camera: repeated wrong passwords may lock the account. For the `LOGONLOCK` reply, repeat until the camera locks. Record the reply and time how long the lock lasts. For too many users, keep sessions open from several clients until the camera refuses one. Record the reply and the session count.

Expect ("Refusal"): `protocol.md` has reason 2 for bad credentials and no reply for a lock or for too many users. Record the reply of a lock and its reason.

### 4.5 Device info source

Design ruling: `protocol.md` found no HTTP endpoint and no logon-reply field for the model, the serial number, the firmware or the MAC. The library's `info` stays partial until this check finds the source.

Answers:
> login: Which fields carry device id, model, serial, firmware and channel count, and in what order? They are not in the login reply but in the function report and the parameters sent at logon. (blocks: device registry)

> http: Which request returns the model, serial and MAC? The app reads only versions from `/CGI/System/deviceInfo`. (blocks: `info` in `http.py`)

Search each candidate source for the label values:

1. Discovery reply: field 22 (model name), field 24 (serial number) and field 2 (MAC). See 8.2.
2. Private protocol: the camera's answer to `<IP> PROXY CMD GETDEVICEPARAM` (no arguments; it ends with `INNER CMD GETDEVICEPARAM FINISHED`), and the `PARAGET` messages the app receives at login. In an app or PC capture, replace `SERIAL` with the label serial number. Then repeat for the model and for the MAC in both octet orders:

   ```sh
   tshark -r app.pcap -Y 'tcp.port == 3000 && frame contains "SERIAL"' -T fields -e frame.number -e ip.src
   strings -a app.pcap | grep -a PARAGET | sort | uniq -c
   ```

   The second command lists every `PARAGET` name the camera sent. Look for a device record.
3. HTTP: `curl --digest -u admin:PW -s "http://IP/CGI/System/deviceInfo"`, then search the reply.
4. HTTP capabilities: search the replies of check 9.4 too.
5. ONVIF: `GetDeviceInformation` returns the manufacturer, model, firmware version, serial number and hardware id.

   ```sh
   curl --digest -u admin:PW -s -X POST "http://IP/onvif/device_service" -H 'Content-Type: application/soap+xml; charset=utf-8' -d '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>'
   ```

Expect ("Successful reply", "Device info"): the logon reply carries none of the four values. The app reads only versions from the HTTP `deviceInfo`, but the camera may send more. Record the source and the field name or index for each of: the model, the serial number, the firmware, the MAC, the device id and the channel count.

## 5. Heartbeat

### 5.1 Heartbeat and the camera's answer

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Heartbeat", "Camera reply"): the web player sends an empty command frame every 5 s. The camera sends `<ip> PROXY INNER CMD EXCEPTION 0 0` (sometimes `2 0` or `4 0`) and an empty `<ip> PROXY` message about every 10 s. A session stayed up 25 minutes with no drop. Not known: whether these messages answer the heartbeat.

Steps, for another camera:

Confirms: `heartbeat_request`.

Answers:
> heartbeat: Does the camera answer each heartbeat, and with which bytes? The vendor client shows only that an empty camera packet is valid. (blocks: heartbeat reply fixture)

Take a PC capture: log in and stay idle for 60 seconds. Use the segment listing from 2.1 and read the idle window.

Expect ("Heartbeat message and sender", "Camera reply"):

- The client sends a 20-byte packet every 3 seconds: `f1 f5 ea f5`, a sequence number, `14 00`, then zeros.
- The sequence number rises by 1 each time.
- For the camera, record whether it sends nothing, a 20-byte packet, or a packet with a payload during the idle window.

### 5.2 Camera silence timeout

Answers:
> heartbeat: After how much silence does the camera close a command connection? (blocks: keepalive margin in `nvs/connection.py`)

Record the whole session. `timeout` ends the capture 10 minutes after it starts, which caps the wait. In terminal 1, start the capture:

```sh
sudo timeout 600 tcpdump -i any -n -s 0 -w silence.pcap host IP and tcp port 3000
```

In terminal 2, log in with the library probe and let it send heartbeats for 10 seconds. Then freeze it so it sends nothing. `PID` is the probe's process id (`pgrep -f sannce_aio`):

```sh
kill -STOP PID
```

Now and then, run `ss -tn dst IP`. When the connection shows `CLOSE-WAIT` or is gone, stop `tcpdump` with Ctrl-C. Otherwise the cap stops it. Then read the two times:

```sh
tshark -r silence.pcap -Y 'ip.dst == IP && tcp.len > 0' -T fields -e frame.time_epoch -e tcp.len | tail -1
tshark -r silence.pcap -Y 'ip.src == IP && (tcp.flags.fin == 1 || tcp.flags.reset == 1)' -T fields -e frame.time_epoch -e tcp.flags.fin -e tcp.flags.reset | head -1
```

The first line is the last packet the PC sent: the last heartbeat. The second is the camera's first FIN or RST. The limit runs from the last packet the camera received, so subtract the first time from the second.

Expect ("Silence timeout"): `protocol.md` has no camera-side value. The vendor client drops a session after 30 seconds. Record the camera's limit. If no FIN or RST shows up within the cap, record "no close within 10 minutes".

### 5.3 MODULE HEARTBEAT

Answers:
> heartbeat: Does the camera expect a `MODULE HEARTBEAT RESPONSE` from the client, and what do its integer and string mean? (blocks: camera message decoder)

Leave a logged-on app idle for 10 minutes under app capture. Use the filter `tcp.port == 3000 && frame contains "MODULE"`.

Expect ("Heartbeat message and sender"):

- The camera may send `INNER CMD MODULE HEARTBEAT <n>`. Nothing shows that it expects a reply.
- Record the interval and the values of `<n>`.
- If the app never sends `RESPONSE` and the session stays up, the camera does not need one.
- If no such message shows up, record "not seen".

## 6. Events

For every event check:

- Keep a client logged on: the app under app capture, or the library probe under PC capture.
- Use the filter `tcp.port == 3000 && frame contains "ALARM"`. It also matches `INNER ONVIF VCAALARM`.
- A message reads `<ip> <route> INNER ALARM <KIND> <channel> <state> ...`. The route is `PROXY` for `MOTIONDETECT` on the I91FX and unknown for the other kinds: record it.
- Record every other alarm kind that appears (`VIDEOLOST`, `INPORT`, `NOTIFY`, `CMD ALARM ALERT`). `protocol.md` lists their fields.

### 6.1 Upload without a subscribe message

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Enabling event upload"): the library sends no subscribe message, and events arrive after login. The camera's own detection settings decide which events it sends: see 6.3.

Steps, for another camera:

Answers:
> events: Does the camera gate alarm upload on its own config, or push to every logged-on client? The client side shows no subscribe message. (blocks: event setup step)

Log in from the PC with the library probe and walk in front of the camera. The probe sends no subscribe message, because `protocol.md` has none. Then turn one alarm or notification setting off, walk again, and turn it back on. Repeat for each setting the app offers for the camera.

Expect ("Enabling event upload"): events arrive without a subscribe message (inferred). Record which camera setting, if any, stops them.

### 6.2 Motion start and stop

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Start and stop"):

- While a person is in view the camera sends `<ip> PROXY INNER ALARM MOTIONDETECT 0 1 <id>` once per second. `<id>` is 16 digits. At the end it sends one `... MOTIONDETECT 0 0 <same id>`.
- The third field is the event id, not a target name. There is no separate stop command.
- `event_motion_start` and `event_motion_stop` are `verified`. Not recorded: the count of starts without a stop, so the library keeps its 10-second timer.

Steps, for another camera:

Confirms: `event_motion_start`, `event_motion_stop`.

Answers:
> events: What alarm-state codes does the camera send for start and stop, and does it always send a stop? (blocks: event timeout tuning)

Walk in, stand still for 10 seconds, walk out. Repeat ten times. Use the filter `tcp.port == 3000 && frame contains "MOTIONDETECT"`.

Expect ("Start and stop"):

- `INNER ALARM MOTIONDETECT 0 1` at the start and `INNER ALARM MOTIONDETECT 0 0` at the stop: channel 0, then the state.
- There is no separate stop command.
- Count the starts that have no stop. Any one justifies the library's timeout.
- Record the third field if it appears, and the time from start to stop.

### 6.3 Person detection

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Start and stop", "Human and vehicle", "Event sources and side effects"):

- A. ONVIF offers `VideoSource/MotionAlarm`, `RuleEngine/CellMotionDetector/Motion`, `RuleEngine/TamperDetector/Tamper`, `VideoSource/SignalLoss`, `VideoSource/ImageTooDark` and `VideoAnalytics/tnshik:MotionAlarm`. There is no person or vehicle topic.
- B. With person and vehicle detection on and all-motion off, an object that moved with no person in view gave no event. A person in view gave `MOTIONDETECT`.
- Outcome: gated `MOTIONDETECT`. `event_smart_person` is `verified`. Not recorded: the run with all-motion on.

Steps, for another camera:

Design ruling: the port-3000 channel has motion and vehicle events but no distinct person event. The Home Assistant person sensor needs another source.

Confirms: `event_smart_person`.

Two candidates exist: ONVIF human-detection events, or `MOTIONDETECT` gated by the smart person-only filter.

A. ONVIF. Find the events service:

```sh
curl --digest -u admin:PW -s -X POST "http://IP/onvif/device_service" -H 'Content-Type: application/soap+xml; charset=utf-8' -d '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>Events</Category></GetCapabilities></s:Body></s:Envelope>' | grep -oE '<[A-Za-z]*:?XAddr>[^<]*'
```

Put the events address in place of `EVENTS_XADDR`, then list the topics:

```sh
curl --digest -u admin:PW -s -X POST "EVENTS_XADDR" -H 'Content-Type: application/soap+xml; charset=utf-8' -d '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><GetEventProperties xmlns="http://www.onvif.org/ver10/events/wsdl"/></s:Body></s:Envelope>' | grep -oiE '[A-Za-z0-9]*(human|person|people|vehicle|motion)[A-Za-z0-9]*' | sort -u
```

If port 80 does not serve ONVIF, find the port with `nmap -p- IP`. A `NotAuthorized` fault means the service wants a WS-Security user token: read the topics with an ONVIF client instead.

B. Gated motion. In the app, or with check 9.7, set person detection on and vehicle and all-motion off. Walk in front of the camera. Then move something that is not a person, such as a curtain or a pet. Then set all-motion on and repeat.

Expect ("Human and vehicle"): `protocol.md` has no person message. A person rides in `INNER ALARM MOTIONDETECT` (type 0), byte for byte the same as `event_motion_start`.

- Under A, a topic with human, person or people in its name is the person source. Record its full path.
- Under B, events for the person but not for the other movement mean the person-only filter gates `MOTIONDETECT`. Events for both mean it does not. Read the optional third field of each event: it may name the target.
- Record the outcome: an ONVIF topic, gated `MOTIONDETECT`, or neither. Neither means no person sensor on this firmware.

### 6.4 Vehicle

Not done: no vehicle was in view on 2026-10-15.

Confirms: `event_smart_vehicle`.

Answers:
> events: What does the camera send for a real vehicle: `MOTIONDETECT_CAR`? (blocks: Vehicle binary sensor)

Set vehicle detection on and the others off. Put a vehicle in view. Use the filter `tcp.port == 3000 && frame contains "MOTIONDETECT_CAR"`.

Expect ("Human and vehicle"): `INNER ALARM MOTIONDETECT_CAR 0 1`, then state 0 at the stop.

### 6.5 Lens cover

Not done on 2026-10-15.

Confirms: `event_video_cover`.

Switch on the tamper (video cover) alarm in the app if it is off. Cover the lens for 10 seconds, then uncover it. Use the filter `tcp.port == 3000 && frame contains "VIDEOCOVER"`.

Expect ("Event messages and their fields"): `INNER ALARM VIDEOCOVER 0 1` when covered and state 0 when cleared.

### 6.6 VCA rules

Confirms: `event_vca_intrusion`.

Answers:
> events: Which `VCA` A4 values mean intrusion, line crossing, area and the other analytics? (blocks: VCA kind mapping)

> events: What is the target-type code for human vs vehicle inside the `VCA` and `ONVIF VCAALARM` target arrays? (blocks: per-target person/vehicle kinds)

If the app offers intrusion or line-crossing rules for this camera, switch on one rule at a time and trigger it. Use the filter `tcp.port == 3000 && frame contains "VCA"`. Read A4, the rule type, and the target groups that follow A12.

Expect ("Event messages and their fields"):

- `INNER ALARM VCA <channel> <state> 0 <A4> ...`.
- A4 = 2 means intrusion and A4 = 0 means line crossing. Both are inferred from the app's alarm names.
- Record A4 for every rule type the camera offers, and the target-type codes for a person and for a vehicle.
- Look for `INNER ONVIF VCAALARM` too.
- If the camera offers no rules or sends no `VCA`, record that.

## 7. Talk

**Superseded 2026-10-15** by the RTSP backchannel. The I91FX answers `CMD TALK BEGIN` over the WebSocket with `BEGIN OK`, but plays nothing that arrives on that path. The speaker uses the backchannel instead: see `protocol.md`, "Backchannel", for the measured session. Run 7.1 and 7.2 only to study the private talk path; the integration does not depend on them.

### 7.1 Start, codec and audio

Confirms: `talk_start_request`, `talk_audio_frame_g711a`, `talk_stop_request`.

Answers:
> talk: What `id:rate` pairs does `TALKCODER_LIST` return for the I91FW, and which codec does the camera accept? (blocks: talk codec choice)

> talk: Does `CMD TALK BEGIN` need the optional audio encode-type and sample-rate fields, and what values does the camera expect? (blocks: talk start fields)

Take an app capture: open the camera, hold the talk button for 5 seconds, speak, and release. Use two filters. The first shows the commands, the replies and `TALKCODER_LIST`. The second shows the audio packets.

```text
tcp.port == 3000 && frame contains "TALK"
tcp.port == 3000 && tcp.payload contains f1:f5:ea:f9
```

Expect ("Request, accept and refuse", "Audio frame layout", "Codecs, sample rate, frame size and pacing"):

- The start request is `<ip> NVR 0 <empty> CMD TALK BEGIN`. Record whether the encode type and the sample rate follow it.
- The camera accepts with `INNER NVR 0 ... BEGIN OK` on route `IP`.
- `INNER PARAGET TALKCODER_LIST` carries a leading integer, the channel, a count and `id:rate` pairs. Record every pair. Id 1 is G711A.
- Each audio payload starts `4e 56 52 00 09 00 09 00 09 4e 56 53 00`.
- Four bytes of the device IP follow, byte-swapped: `0a 01 a8 c0` for `192.168.1.10`.
- For G711A, the sub-header `00 01 28 00` and 80 audio bytes come next. Four packets carry each 40 ms of speech.
- The camera speaker plays the voice.
- The end is `CMD TALK END`, answered by `END OK`.

### 7.2 Busy refusal

Confirms: `talk_refused_busy`.

Answers:
> talk: The channel-talk reply uses route `IP` and the command prefix `INNER NVR` (from the vendor client). What are the unread tokens 3-5 between the channel and `BEGIN`, and what exactly makes the camera send `BEGIN ERROR`? (blocks: talk reply fixture)

Use two clients. Phone A holds talk. Client B starts talk on the same channel: a second phone under PCAPdroid, or the library with a PC capture. On B, use the filter `tcp.port == 3000 && frame contains "TALK"`.

Expect ("Stopping talk and the busy case"):

- B receives `<ip> IP INNER NVR 0 ... BEGIN ERROR`.
- The vendor client reads the channel at index 2 and the result at index 7, counted from `INNER`.
- Record tokens 3-5 and the header bytes exactly.
- Then start talk with a channel number the camera does not have. Note whether that also gives `BEGIN ERROR`.

## 8. Discovery

### 8.1 Request and answer path

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Ports and groups"): the camera answers a seek from UDP port 3000, by unicast to the sender's port 6001.

Steps, for another camera:

Confirms: `discovery_seek_request`.

Answers:
> discovery: Does the I91FW answer on UDP 3000, on 4000 or on both, and does it reply by unicast to the request's source port 6001 or by multicast? (blocks: `discovery.py` socket setup)

Run from the repository root. In terminal 1, record the UDP traffic:

```sh
sudo tcpdump -i any -n -s 0 -w disc.pcap 'udp and (port 6001 or port 3000 or port 4000)'
```

In terminal 2, send the example from source port 6001 to both groups and to the camera, on both ports:

```sh
HEX=$(jq -r '.examples[] | select(.id == "discovery_seek_request") | .hex' docs/protocol-examples.json)
for dst in 234.56.78.9 239.255.255.250 IP; do
  for port in 3000 4000; do
    echo "$HEX" | xxd -r -p | nc -u -w 2 -p 6001 "$dst" "$port"
  done
done
```

With `tcpdump` still running, open the app's add-by-LAN-search screen on the phone for 30 seconds. Then stop `tcpdump` and list who sent what to whom:

```sh
tshark -r disc.pcap -T fields -e frame.time_relative -e ip.src -e udp.srcport -e ip.dst -e udp.dstport -e udp.length
```

Expect ("Ports and groups", "Seek request", "Search cadence"):

- The phone sends four 40-byte datagrams per search, at 0 and at 20 seconds. They leave from port 6001, go to both groups on ports 3000 and 4000, and carry the example's payload.
- The camera most likely answers by unicast to port 6001 of the sender (inferred).
- Record which sends drew a reply, the reply's source port, and whether the reply was unicast or went to a group.
- A switch with IGMP snooping can keep multicast away from the PC. The capture can then miss the phone's datagrams or a multicast reply. A missing packet proves nothing.

### 8.2 Reply bytes

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Seek reply"):

- The envelope is `be be e5 e5 00 00 00 00 ea 01`: id 0, flag 0, length 490.
- Counted from `NEWM4V00`: field 0 `CMD`, 1 `NVSS`, 2 the MAC in reversed octet order and lower case, 7 `3000` (stale, the port is closed), 8 `6000`, 9 `4`, 10 `80`, 13 `NVSS_V29.0.23.20250330`, 14 `7.1.25.407`, 20 activation (`0` before activation), 22 `I91FX`, 24 the serial number, 32 the IP, 35 an Aliyun product key, 38 an RSA public key, 39 `1`.
- Not recorded: the bytes before `NEWM4V00`, field 11 (product model number), the unnamed fields 16-19, 21, 23, 25-31, 34, 36 and 37, and field 20 (activation) after activation.
- `discovery_reply` stays `inferred`: its values are placeholders.

Steps, for another camera:

Confirms: `discovery_reply`.

Answers:
> discovery: What does a real reply carry before `NEWM4V00`? (blocks: discovery reply fixtures)

> discovery: Does the camera send its MAC in reversed octet order, and in which letter case? (blocks: MAC as device identity)

> discovery: Which values does the I91FX send for field 11 (product model number), for field 20 (activation) after activation, and for the unnamed fields 16-19, 21, 23, 25-31, 34, 36 and 37? (blocks: device filter, activation check)

Save one reply. Print its 10-byte envelope, then its fields numbered from the `NEWM4V00` marker:

```sh
tshark -r disc.pcap -Y 'udp.srcport == 3000 || udp.srcport == 4000' -T fields -e udp.payload | head -1 > reply.hex
xxd -r -p reply.hex | head -c 10 | xxd
xxd -r -p reply.hex | tail -c +11 | tr -d '\n' | tr '\t' '\n' | awk '/NEWM4V00/ {f = 1; n = 0; print "marker: " $0; next} f {print n++ ": " $0; next} {print "before: " $0}' | cat -v
```

The `marker:` line holds `NEWM4V00` and any bytes before it in the same piece. A `before:` line is a TAB-separated piece ahead of the marker. Field N is the line that starts `N:`. The count starts after the marker, so a prefix does not shift it.

Expect ("Seek reply"):

- The envelope is `be be e5 e5`, the id, the flag and the length. Record the id and the flag, and any bytes before `NEWM4V00`.
- Field 0 is `CMD` and field 1 is `NVSS`.
- Field 2 is the MAC. Its octets should come in the reverse order of the label. Record the letter case.
- Record field 7 (server port), 9 (device type; 4 for an IP camera), 10 (HTTP port), 12 (factory id), 20 (activation; 1 when activated), 22 (model name), 24 (serial number) and 32 (IP).
- Record fields 8 (client port) and 11 (product model number).
- Record the fields `protocol.md` leaves unnamed: 16-19, 21, 23, 25-31, 34, 36-37 and 39.

### 8.3 MAC prefix for DHCP discovery

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Seek reply"): the MAC prefix is `D0:3B:F4`. It is none of the three Tiandy prefixes, so the `dhcp` list in `manifest.json` gets `D03BF4*`.

Steps, for another camera:

`custom_components/sannce/manifest.json` asks Home Assistant to report DHCP requests from MAC addresses with the prefixes the IEEE registry assigns to Tiandy Technologies: `3C:DA:6D`, `BC:51:6C` and `E4:E6:6C` (MA-L, `standards-oui.ieee.org/oui/oui.txt`, read on 2026-10-13), and with the I91FX's own prefix `D0:3B:F4`.

Read the MAC on the camera label, or from the PC:

```sh
ping -c 1 IP && ip neigh show IP
```

Expect the first three octets to be one of the four prefixes. If not, add the camera's prefix to the `dhcp` list in `manifest.json` and to `CAMERA_PREFIXES` in `tests/components/sannce/test_manifest.py`.

## 9. HTTP

Unless a check says otherwise, every request uses `curl --digest -u admin:PW`, and `-i` prints the reply headers. HTTP channel numbers start at 1: use `1`.

### 9.1 Login: Digest or session

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Authentication"):

- Digest MD5 with realm `CGI` and qop `auth` works for every path tried. The user name `admin` in lower case passes as well as `Admin`.
- `GET /CGI/Security/SessionCheck` answers with `session`, `key` and `iterations`, so the session login exists. The session login itself was not recorded.
- The form of the Digest header was not recorded, so the question about the standard form stays open.
- Before activation, `GET /CGI/System/ActivationStatus` answers without a login: `<activated>inactive</activated><administrator>Admin</administrator>`. After activation it says `active`.

Steps, for another camera:

Design ruling: the library tries the SHA-256 session login first and falls back to Digest. This check shows which one the I91FW needs.

Answers:
> http: Which login does the I91FW accept for these calls: the session (`HttpSession` header), Digest, or both? What are its Digest realm and qop? (blocks: auth in `http.py`)

> http: Does the camera accept the standard Digest form that aiohttp sends (`uri` is the request path, `qop` and `algorithm` unquoted), or only the app's form (absolute `uri`, quoted `qop` and `algorithm`)? (blocks: `DigestAuthMiddleware` setup)

```sh
curl -i "http://IP/ISAPI/Security/userCheck?username=admin&passwd=PW"
curl --digest -u admin:PW -i "http://IP/ISAPI/Security/userCheck?username=admin&passwd=PW"
curl --digest -u admin:PW -i "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
curl -i "http://IP/CGI/Security/SessionCheck"
```

Expect ("Authentication"):

- Call 1: `401` with a `WWW-Authenticate: Digest` header. Record the realm, the qop, the algorithm and whether `opaque` appears.
- Call 2: `200` with `statusString` `OK`. curl sends the standard Digest form, which is the form aiohttp sends. So the standard form works.
- Call 3: `200` and a `MotionDetection` body. Digest works for the settings paths, not only for `userCheck`.
- Call 4: a `SessionCheck` reply with `session`, `key` and `iterations` means the session login exists. A `404` or an error means Digest is the only login.

If call 2 returns `401` with the right password, the camera may accept only the app's Digest form. Send it:

```sh
U="http://IP/ISAPI/Security/userCheck?username=admin&passwd=PW"
C=$(curl -si "$U" | tr -d '\r' | grep -i '^www-authenticate')
realm=$(echo "$C" | sed -n 's/.*realm="\([^"]*\)".*/\1/p')
nonce=$(echo "$C" | sed -n 's/.*nonce="\([^"]*\)".*/\1/p')
qop=$(echo "$C" | sed -n 's/.*qop="\([^"]*\)".*/\1/p')
cnonce=$(date +%s%3N | md5sum | cut -d' ' -f1)
ha1=$(printf '%s' "admin:$realm:PW" | md5sum | cut -d' ' -f1)
ha2=$(printf '%s' "GET:$U" | md5sum | cut -d' ' -f1)
resp=$(printf '%s' "$ha1:$nonce:00000001:$cnonce:$qop:$ha2" | md5sum | cut -d' ' -f1)
curl -i -H "Authorization: Digest username=\"admin\",realm=\"$realm\",nonce=\"$nonce\",uri=\"$U\",cnonce=\"$cnonce\",nc=00000001,response=\"$resp\",qop=\"$qop\",algorithm=\"MD5\"" "$U"
```

Expect `200` with `statusString` `OK`. Then the library must build this form instead of the standard one.

If call 4 returns a `SessionCheck` reply, run the session login too, even when call 3 works. `adminPW` is the user name followed by the password:

```sh
R=$(curl -s "http://IP/CGI/Security/SessionCheck")
S=$(echo "$R" | sed -n 's:.*<session>\(.*\)</session>.*:\1:p')
K=$(echo "$R" | sed -n 's:.*<key>\(.*\)</key>.*:\1:p')
N=$(echo "$R" | sed -n 's:.*<iterations>\(.*\)</iterations>.*:\1:p')
H=$(printf '%s' 'adminPW' | sha256sum | cut -d' ' -f1 | tr a-f A-F)
for _ in $(seq "$N"); do H=$(printf '%s%s' "$H" "$K" | sha256sum | cut -d' ' -f1 | tr a-f A-F); done
L=$(curl -s -X POST "http://IP/CGI/Security/Logon" -H 'Content-Type: application/xml; charset=utf-8' -d "<User><passwd>$H</passwd><sessionTmp>$S</sessionTmp><username>admin</username></User>")
echo "$L"
SESSION=$(echo "$L" | sed -n 's:.*<session>\(.*\)</session>.*:\1:p')
curl -i -H "HttpSession: $SESSION" "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
```

Expect: a `UserLogon` reply with `statusString` `OK` and a non-empty `session`. The last call answers `200` with no Digest. If call 3 also worked, the camera accepts both logins. If call 3 failed, the camera needs the session login.

### 9.2 Port 80, reply format and byte order mark

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Where the evidence comes from"): port 80 serves the white-light, light-mode, motion-detection, capability, `PlayAudio`, `TwoWayAudio` and VMD trigger paths directly, so the cloud relay is not needed. Not recorded: the reply status line, the headers and a byte order mark, so the second question stays open.

Steps, for another camera:

Answers:
> http: Does the I91FW web server accept the app's paths and XML bodies on port 80, or only through the cloud relay? (blocks: `http.py`)

> http: What do the camera's reply status line and headers look like, and does a reply start with a byte order mark or an XML declaration? (blocks: HTTP fixtures in `simulator.py`)

```sh
curl --digest -u admin:PW -s -D - -o body.xml "http://IP/ISAPI/Image/channels/1/WhiteLight"
head -c 16 body.xml | xxd
```

Expect ("Where the evidence comes from"):

- A `200` on port 80 means the web server serves the app's paths directly (inferred).
- The examples guess `HTTP/1.1 200 OK`, `Content-Type: application/xml; charset=utf-8` and a body that starts with `<`. Record the real status line and headers.
- Record whether the body starts with `ef bb bf` (byte order mark) or `<?xml`.
- If port 80 refuses the connection, every HTTP check fails. The camera may be reachable only through the cloud relay.

### 9.3 Device info

Confirms: `http_device_info_reply`.

```sh
curl --digest -u admin:PW -i "http://IP/CGI/System/deviceInfo"
```

Expect ("Device info"): a `DeviceInfo` document with version elements (`firmwareVersion`, `hardwareVersion`, `sdkVersion`, `webVersion`, `uiVersion`, `mediaVersion` and others) and a `platformVersionList`. Compare the element names with the example and record any extras. Search the body for the model, the serial number and the MAC: see 4.5.

### 9.4 Capabilities

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result: the `contrltype` options (`0,2,3`) and the light modes are in 9.5 and 9.6. The `guardSound` capability is in 9.11. The `lightType` and `supportType` values were not recorded.

Confirms: `http_capabilities_reply`.

Answers:
> http: Which `lightType` and `supportType` values does the I91FX return? (blocks: `caps` white_light, person, vehicle)

```sh
curl --digest -u admin:PW -i -H 'Content-Type: application/xml; charset=utf-8' -d '<CapDiscription><capType><mainType>015-AlarmParam</mainType><subType>00125-MDMotionDetectionSubList</subType></capType></CapDiscription>' "http://IP/CGI/System/channels/1/capabilities"
curl --digest -u admin:PW -i -H 'Content-Type: application/xml; charset=utf-8' -d '<CapDiscription><capType>color2graylight</capType><capType>SupportLEDPowerLimit</capType><capType>colorToGrayThreshold</capType></CapDiscription>' "http://IP/CGI/System/channels/1/capabilities"
curl --digest -u admin:PW -i -H 'Content-Type: application/xml; charset=utf-8' -d '<CapDiscription><capType><mainType>001-ColorToGray</mainType><subType>00105-colorToGrayWhitelightTime</subType></capType><capType><mainType>001-ColorToGray</mainType><subType>00106-colorToGrayIRlightMax</subType></capType></CapDiscription>' "http://IP/CGI/System/channels/1/capabilities"
curl --digest -u admin:PW -i "http://IP/CGI/Device/AllCapabilities/AllCapabilities"
```

Expect ("Capabilities"): a `ChanBasicCapList` reply to each POST.

- Call 1: `support` is true and `supportType` lists `people`, `car` and `all`.
- Call 2: `lightType` lists a white lamp (`whiteLamp`, `midwhiteLamp` or `farwhiteLamp`) and infrared lamps (`nearinfraredLamp`, `midinfraredLamp` or `farinfraredLamp`). `color2graylight` has `support` true on a camera with a white light.
- Call 3: one `capTypeList` per subtype, with `capType` and `support`.
- Call 4: an `AllCapabilities` document whose `oAVideo` holds `bWhiteLight`, `bWhiteLightSet`, `bRedLight` and `bRedLightSet`.
- Record every value returned. The `contrltype` options come from 9.5 and the light modes from 9.6.

### 9.5 White light

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("White light"):

- `contrltype` lists `opt="0,2,3"`. A PUT of `contrltype` 1 (manual on, the value `http_whitelight_set_manual_on` sets) gets `statusCode` 3 and `statusString` `Device Error`.
- `contrltype` 3 with `sunSetTime` `00:00:00` and `sunRiseTime` `23:59:00` lights the lamp. It is lit from `sunSetTime` to `sunRiseTime`, with minute resolution: `23:59:59` reads back as `23:59:00`.
- The lamp lights only in light mode 3 (colour) or 4 (custom). Mode 1 keeps it off. Mode 2 lights it only on detection.
- Changing the light mode resets `contrltype`: modes 1 and 2 to 2, modes 3 and 4 to 0.
- Lamp power 30 is visibly dimmer than 100.
- From the acceptance run: writing that window in light mode 3 (colour) switches the light mode to 4 (custom).
- Not recorded: a PUT with `contrltype` alone, so that question stays open.

Steps, for another camera:

Confirms: `http_whitelight_get_reply`, `http_whitelight_set_manual_on`.

Answers (shared with 9.6 and 9.7):
> http: Does the camera accept a PUT with only the changed fields (`contrltype` alone, one detection flag, a bare `CommonEnable`), or only the whole document the app echoes? (blocks: `set_light`, `set_light_mode`, `set_detection`)

```sh
curl --digest -u admin:PW -s -o wl.xml "http://IP/ISAPI/Image/channels/1/WhiteLight"; cat wl.xml
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<WhiteLight><contrltype>1</contrltype><infraredFarLampPower>100</infraredFarLampPower><infraredLampPower>100</infraredLampPower><sunRiseTime>06:00:00</sunRiseTime><sunSetTime>18:00:00</sunSetTime></WhiteLight>' "http://IP/ISAPI/Image/channels/1/WhiteLight"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<WhiteLight><contrltype>0</contrltype></WhiteLight>' "http://IP/ISAPI/Image/channels/1/WhiteLight"
```

Edit the power and time values of the second call to match `wl.xml`. GET again after each PUT. At the end, PUT the original values back, with `contrltype` as plain text and no `opt` attribute.

Expect ("White light"):

- GET: `contrltype` carries an `opt` list such as `0,1,2,3`. Both powers run from 0 to 100. The times read `HH:MM:SS`. Record the `opt` list.
- Second call: a `ResponseStatus` with `statusCode` 1 and `statusString` `OK`. The lamp switches on (`contrltype` 1 is manual on).
- Third call: record whether the camera accepts `contrltype` alone, and what the lamp does.

### 9.6 Light mode

**Done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Light mode", "White light"): the four modes exist with the values of the table: 1 infrared, 2 smart, 3 color, 4 custom. Changing the mode resets `contrltype` (see 9.5). Not recorded: a PUT with `value` alone, and the reply of an unsupported type. The question on light-mode support stays open: it needs a camera without light mode.

Steps, for another camera:

Confirms: `http_light_mode_set_smart`.

Answers:
> http: How does the I91FW report light-mode support over HTTP? The app reads a cloud bitmask, not an HTTP reply. Does a failed `GET .../Type/4120` mean no light mode? (blocks: `caps` light_mode)

```sh
curl --digest -u admin:PW -i "http://IP/CGI/System/CommonEnable/channels/1/Type/4120"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<CommonEnable><enable>true</enable><type>4120</type><value>2</value></CommonEnable>' "http://IP/CGI/System/CommonEnable/channels/1/Type/4120"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<CommonEnable><value>3</value></CommonEnable>' "http://IP/CGI/System/CommonEnable/channels/1/Type/4120"
curl --digest -u admin:PW -i "http://IP/CGI/System/CommonEnable/channels/1/Type/9999"
```

GET `Type/4120` again after each PUT. At the end, PUT the original document back, with all three elements.

Expect ("Light mode"):

- Call 1: a `CommonEnable` document with `enable`, `type` 4120 and `value` from 1 to 4. Set each mode in the app and GET again to check the map: 1 infrared, 2 early-warning (smart dual light), 3 full colour, 4 customize.
- Call 2: the mode becomes 2. This fresh body is what the library would send.
- Call 3: record whether a body with `value` alone is accepted, and what it does to `enable` and `type`.
- Call 4: an unknown type. Record its status and body as the failure shape.
- A camera without light mode is needed to answer the second question. With one camera, record the failure shape only.

### 9.7 Motion detection

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Motion detection"), call 1 only: `enabled` true, `carEnabled` true, `allEnabled` false, `sensitivityLevel` 76. The web UI slider for the sensitivity runs from 0 to 100. `gridMap` is all zeros, yet smart events fire. The PUT calls and the two locks were not run. From the acceptance run: the Motion sensitivity number's `sensitivityLevel` reaches the camera, and it was restored.

Steps, for another camera:

Confirms: `http_motion_detection_get_reply`.

Answers:
> http: On a camera whose capability reply lacks `people`, does `enabled` mean plain motion detection? (blocks: `set_detection` on other models)

```sh
curl --digest -u admin:PW -s -o md.xml "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"; cat md.xml
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<MotionDetection><enabled>true</enabled><carEnabled>false</carEnabled><allEnabled>false</allEnabled></MotionDetection>' "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
curl --digest -u admin:PW -s "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' --data-binary @md.xml "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
```

The last call puts the original document back.

Expect ("Motion detection"):

- Call 1: `enabled` (person), `carEnabled` (vehicle) and `allEnabled` (all motion), plus `regionType`, `Grid` and `MotionDetectionLayout`.
- Call 2: a `ResponseStatus` with `statusString` `OK`.
- Call 3: `Grid` and `MotionDetectionLayout` are unchanged after a PUT with flags only. If they vanish, the library must send the whole document.
- If the I91FW lists `people` in 9.4, it cannot answer the open question. Mark it "not testable on this model".

Then test the two locks that the app applies. The PUTs below carry flags only, as in call 2. If call 2 needed the whole document, send `md.xml` with the flags changed instead.

Lock A, all-motion. Turn all-motion on with person and vehicle on. Then try to turn person and vehicle off, and read the flags back.

```sh
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<MotionDetection><enabled>true</enabled><carEnabled>true</carEnabled><allEnabled>true</allEnabled></MotionDetection>' "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<MotionDetection><enabled>false</enabled><carEnabled>false</carEnabled><allEnabled>true</allEnabled></MotionDetection>' "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
curl --digest -u admin:PW -s "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
```

Lock B, smart light mode. Set light mode 2 (smart) with person and vehicle on and all-motion off. Then try to turn person and vehicle off, and read the flags back.

```sh
curl --digest -u admin:PW -s -o ce.xml "http://IP/CGI/System/CommonEnable/channels/1/Type/4120"; cat ce.xml
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<CommonEnable><enable>true</enable><type>4120</type><value>2</value></CommonEnable>' "http://IP/CGI/System/CommonEnable/channels/1/Type/4120"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<MotionDetection><enabled>true</enabled><carEnabled>true</carEnabled><allEnabled>false</allEnabled></MotionDetection>' "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<MotionDetection><enabled>false</enabled><carEnabled>false</carEnabled><allEnabled>false</allEnabled></MotionDetection>' "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
curl --digest -u admin:PW -s "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
```

At the end, put the originals back.

```sh
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' --data-binary @ce.xml "http://IP/CGI/System/CommonEnable/channels/1/Type/4120"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' --data-binary @md.xml "http://IP/ISAPI/System/Video/inputs/channels/1/motionDetection"
```

Expect ("Light mode", "Motion detection"): the app blocks both changes on its own side, so `protocol.md` does not show what the camera does. For each lock, record the HTTP status and the `ResponseStatus` of the PUT that turns person and vehicle off, then the flags read back. The camera does one of three things:

- It accepts the change and the flags read false. The lock lives in the app only.
- It refuses the change. Record `statusString` and `subStatusCode`.
- It answers `OK` and the flags still read true. The camera ignores the change.

If 9.4 does not list `all`, Lock A cannot run. Mark it "not testable on this model".

### 9.8 Errors

Answers:
> http: Which `statusCode` and `subStatusCode` values mark a failure besides `vcaPerformanceLimit`, and which HTTP status carries them? (blocks: error mapping in `http.py`)

```sh
curl --digest -u admin:PW -i "http://IP/ISAPI/Image/channels/99/WhiteLight"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<WhiteLight><contrltype>9</contrltype></WhiteLight>' "http://IP/ISAPI/Image/channels/1/WhiteLight"
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d 'not xml' "http://IP/ISAPI/Image/channels/1/WhiteLight"
```

GET the white light again afterwards. Restore it if a call changed it.

Expect ("Errors"): a `ResponseStatus` document. `statusCode` 1 and `statusString` `OK` mean success. For each call, record the HTTP status, `statusCode`, `statusString` and `subStatusCode`. `vcaPerformanceLimit` appears when the analytics reach their load limit. Do not try to provoke it.

### 9.9 The `/CGI/Common/session` path

Answers:
> http: What does `/CGI/Common/session`, a path the vendor SDK uses, do? (blocks: auth in `http.py`)

```sh
curl -i "http://IP/CGI/Common/session"
curl --digest -u admin:PW -i "http://IP/CGI/Common/session"
```

Expect: `protocol.md` makes no claim. Record the status and the body of both calls.

### 9.10 HTTP channel numbering

Confirms: `http_whitelight_get_reply` (its `channel` field is 1).

```sh
curl --digest -u admin:PW -i "http://IP/ISAPI/Image/channels/1/WhiteLight"
curl --digest -u admin:PW -i "http://IP/ISAPI/Image/channels/0/WhiteLight"
```

Expect ("Channel numbering"): channel 1 answers `200` and channel 0 fails. HTTP channel 1 is channel 0 on the private protocol and `/1/<stream>` on RTSP.

### 9.11 Warning sounds, sound link and speaker volume

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`.

Result ("Warning sound", "Backchannel"):

- The `guardSound` capability reports `supportSoundSampleNum` 3 and `supportSoundCustomNum` 2.
- `PUT /CGI/Event/PlayAudio` with `sampleNo` 0 and `action` 1 played sound 0, and it was heard.
- `GET /ISAPI/System/TwoWayAudio/channels/1` returns `outputVolume` 80, `speakerVolume` 80 and `audioOutputType` `innerspeaker`. A PUT of the whole document is accepted. Sound over the backchannel was loud at `outputVolume` 80.
- `outputVolume` drives the speaker. At 30, both a built-in warning and sound over the backchannel played quieter than at 80. What `speakerVolume` does is not known.
- The VMD trigger holds `whiteLampForBody`.
- From the acceptance run: the Siren on event link reaches the camera, and it was restored. Not recorded: whether motion then plays the sound.
- Not recorded: the length of each sound, the stop action and a second PUT while a sound plays. The acceptance run did not check them either.

Answers:
> http: Which `PlayAudio` action stops a sound? (blocks: siren turn_off)

> http: How long is each built-in warning sound, and what does a second `PlayAudio` PUT do while one plays? (blocks: siren replay interval)

> http: Which of `outputVolume` and `speakerVolume` drives the speaker? (blocks: Volume number)

Answered 2026-10-15: `outputVolume`, see the Result above and `protocol.md`, Volume.

> http: Does the camera accept a `guardsound` link on the VMD trigger, and does motion then play the sound? (blocks: `set_siren_on_event`)

Time each sound with a stopwatch. Play sounds 0, 1 and 2 in turn:

```sh
curl --digest -u admin:PW -i -X PUT -H 'Content-Type: application/xml; charset=utf-8' -d '<PlayAudioInfo><channelID>1</channelID><type>0</type><sampleNo>0</sampleNo><action>1</action></PlayAudioInfo>' "http://IP/CGI/Event/PlayAudio"
```

While a sound plays, send the same PUT again and note whether it restarts, queues or is ignored. Then send it with `<action>0</action>` and note whether the sound stops. Try other action values only if 0 does nothing.

For the volume, GET the document, then PUT the whole document back with `outputVolume` 30 and `speakerVolume` 80. Play a sound and a backchannel stream. Repeat with the values swapped. Put the original values back at the end.

```sh
curl --digest -u admin:PW -s -o tw.xml "http://IP/ISAPI/System/TwoWayAudio/channels/1"; cat tw.xml
```

For the sound link, GET `ISAPI/Event/triggers/VMD/channels/1` into `vmd.xml`. Add the entry from "Warning sound" to its notification list, keep the other entries, and PUT the whole document. Walk in front of the camera and note whether the sound plays. PUT `vmd.xml` back at the end.

Expect ("Warning sound", "Backchannel"): `action` 0 stops a sound, and `outputVolume` sets the loudness. Record what differs.

## Acceptance

**Partly done 2026-10-15** on an I91FX, firmware `NVSS_V29.0.23.20250330`, through Home Assistant. Each item ends with its result.

Run these with the camera on the bench Home Assistant, after the end-to-end suite passes. `bench.sh test` and `bench.sh reset` delete every sannce entry, so do not run them once the real camera is added. Replace `<base>` with the entity base name. Record each result in `protocol.md` (tag `verified`, with the date) and below.

1. Walk-by: `binary_sensor.<base>_person` and `binary_sensor.<base>_motion` turn on and off. **Done.** Two walk-bys turned Person and Motion on for about 15 s, then off. This works since the library reads every command of a frame (`protocol.md`, Delimiting messages).
2. Floodlight on, on at 30 %, and off: the lamp follows. After off, the camera's light mode equals the Floodlight mode select. **Partly done.** On, 30 % and off showed on the video. Forcing the window in light mode 3 (color) switches the camera's light mode to 4 (custom). Open: the light mode after off was not recorded.
3. Siren `sound_1`, `sound_2` and `sound_3`, each with no duration, then off after 12 s. Record each sound's length, whether it repeats every 5 s, and whether off stops it at once. This settles `_REPEAT_SECONDS`, `_STOP` and the questions of 9.11. **Partly done.** The generated `alarm` tone is heard and stops at once on turn_off. The built-in sounds are spoken warnings. Open: whether a turn_off cuts a spoken warning short, and whether a warning is longer than the 5 s replay interval, were not checked. So `_REPEAT_SECONDS`, `_STOP` and the questions of 9.11 stay open.
4. Siren on event: switch it on, walk by, and the camera sounds. Switch it off. **Partly done.** The link reaches the camera, and it was restored. Open: whether a walk-by then sounds the camera was not recorded.
5. TTS on `media_player.<base>_speaker` is audible. **Done.** TTS through the speaker was heard.
6. Volume 30, then 80: the speaker and the siren get quieter and louder. If not, move `set_volume` to `speakerVolume` and repeat. **Done.** Volume (`outputVolume`) drives the speaker. Motion sensitivity also reaches the camera, and it was restored.
7. The Interfono button in the wall card, on a dashboard opened over HTTPS or on localhost: the user's voice comes out of the camera. **Partly done.** Without the relay, the first talk worked and the next one failed: go2rtc set up the backchannel again on the same RTSP session, and the I91FX answered `455 Method Not Valid in This State` (`protocol.md`, Backchannel). On a Docker bridge network WebRTC does not connect: go2rtc offers no host candidate for a Docker address. On 2026-10-15 talk worked twice in a row through an earlier relay, with the live view up. Home Assistant ran on the host network. That relay answered only the repeated `SETUP`. The relay now answers go2rtc's backchannel `SETUP` itself and passes the talk to the camera speaker. The newest start wins between talk, the `alarm` siren tone and the Speaker, and `binary_sensor.<base>_intercom` shows talk. On 2026-10-16 the new relay passed a scripted check on the camera (`protocol.md`, Speaker acceptance). Open: the Interfono button with the new relay.
8. `camera.<base>_clear` and `camera.<base>_fluent` play in the dashboard. Open: not recorded on 2026-10-15. Item 7 ran with the live view up.
9. Day and night source: cover the lens for 30 s and read `GET /CGI/Image/channels/1/irLight` before and during. Record whether `<type>` moves from `color` to `gray`. **Done.** The `irLight` `<type>` is not a live state, so there is no day/night sensor.
10. Tamper, optional: enable tamper detection in the camera web UI, cover the lens, and check `binary_sensor.<base>_tamper` (enable the entity first). Put the camera setting back. Open: not done on 2026-10-15.
11. Leave siren on event off at the end. **Done.** The link was restored, see item 4.

## Recording results

- When a check confirms an example, set its `status` to `verified` in `docs/protocol-examples.json`, copy that file to `lib/tests/data/protocol-examples.json`, and change its tag in `protocol.md`.
- When a check disproves an example, correct the example, copy the file the same way, and correct the text first. `tests/docs/test_lib_examples_copy.py` fails while the two files differ.
- Answer each open question in its section of `protocol.md`, then delete it from "Open questions".
- Update the status summary table in "Overview and ports".
