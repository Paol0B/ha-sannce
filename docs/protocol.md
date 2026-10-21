# SANNCE / Tiandy camera protocol

Specification of the Tiandy private protocol and of the camera HTTP API, as used by SANNCE Life wired IP cameras (reference: I91FW). Hardware results come from a SANNCE I91FX, firmware `NVSS_V29.0.23.20250330`.

## Conventions

- Status tags: `static` (read from the vendor client for interoperability, not yet seen on a camera), `inferred` (reasoned from the vendor client or from other results), `verified` (tested on hardware).
- A `verified` tag names the unit and the date: `verified: I91FX 2026-10-15`.
- Pointers into the vendor code are not published. A `web:<path>` reference names a file the camera's web server serves to the browser.
- The camera's address, serial number and MAC, and the owner's password, never appear here. The examples use placeholders.
- Examples live in `protocol-examples.json`. The doc cites them as `[example: <id>]`.
- Byte order and text encoding are stated per section.

## Overview and ports

The SANNCE Life app talks to the camera through Tiandy's client SDK. Each claim below ends with its status.

### Ports and connections

The I91FX serves the private protocol inside a WebSocket on port 3002, not on a plain TCP port.

- Open ports: 80, 443, 554, 3001 and 3002. (verified: I91FX 2026-10-15)
- Port 3002 serves the camera's web player WebSocket (`dataport_websocket_http`). The URL is `ws://<host>:3002`, with no path and no subprotocol. Messages are binary. Each message holds one or more packets in the layout of "Framing". Login, heartbeat and events all run inside it. (verified: I91FX 2026-10-15; static: `web:/external/noplugin-master/h5player.js.gz`)
- Port 3000 refuses connections, before and after activation. (verified: I91FX 2026-10-15)
- Port 3001 accepts a TCP connection and answers nothing to a `LOGON`. (verified: I91FX 2026-10-15)
- The LAN search reply still reports server port 3000 in field 7. The value is stale. A client uses the configured WebSocket port, 3002 by default. (verified: I91FX 2026-10-15)
- RTSP on port 554 serves video, with Digest login. `/1/1` is HEVC 3840x2160 at 20 fps with PCMA 8 kHz mono. `/1/2` is HEVC 704x576 at 20 fps with PCMA 8 kHz. `/0/1` fails with 401. Sound goes in through the backchannel: see "Backchannel". (verified: I91FX 2026-10-15)
- HTTP on port 80 serves the XML API and ONVIF, with Digest login: see "HTTP API". (verified: I91FX 2026-10-15)
- A full TCP port scan made the camera stop answering the scanning host for about a minute. (verified: I91FX 2026-10-15)

The bullets below come from the vendor client. They describe its plain TCP transport on port 3000, which the I91FX does not offer.

- The command channel is one plain TCP connection to the camera's address and port. (static)
- The app fills the port field with `3000` when a device is added by IP, and in the modify-device screens. So the vendor client's default port is 3000. The I91FX closes it, and the library defaults to 3002. (static)
- The client sends `LOGON` as the first message on the command channel. (static)
- Each video stream uses a separate data connection to the same address and port. The client opens it, then sends a `CONNECT` command that names the channel and carries the command-channel id from the logon. (static)
- Talk audio rides the command connection as data packets, not a separate connection. Details are in "Talk channel". (static)
- A data channel can also use UDP. The client then derives the address and port from the device IP, the device port and the channel number. (static)
- The vendor client has an SSL mode for the command channel. It is out of scope here. (static)

### Status summary

Examples by status, and open questions, for each area. `verified` means measured on the I91FX on 2026-10-15 or 2026-10-16. The checks in `hardware-checklist.md` move the other examples.

| area | static | inferred | verified | open questions |
|---|---|---|---|---|
| framing | 0 | 2 | 0 | 3 |
| transport | 0 | 0 | 0 | 1 |
| login | 0 | 2 | 5 | 2 |
| login_encrypted | 0 | 0 | 0 | 0 |
| heartbeat | 0 | 1 | 0 | 3 |
| events | 0 | 3 | 3 | 3 |
| talk | 0 | 4 | 0 | 3 |
| discovery | 1 | 1 | 0 | 2 |
| http | 0 | 6 | 0 | 12 |
| total | 1 | 19 | 8 | 29 |

`transport` has no examples. `login_encrypted` has no entries: the I91FX needs the salted MD5 login, which `login` covers (see "Encrypted login").

## Framing

Every message on a command or data connection is a packet: a 20-byte header, then a payload. All header integers are little-endian. The only exception is the IPv4 address in the data header, which is in network order. (static)

On the I91FX the packets travel in WebSocket binary messages. The command header (`f1 f5 ea f5`, total length at offset 6, payload length at offset 18) and the data header (`f1 f5 ea f9`, total length at offset 14) are as described here. (verified: I91FX 2026-10-15)

### Term: framed message

Later sections write "a framed message carrying fields F1..Fn". It means one command packet whose payload is F1..Fn joined by TAB and followed by `\n\n\n`. Its header has the command magic, the connection's next sequence number, and lengths computed from that payload. In a client message F1 is the device IP and F2 the route, both described under "Field lists". (static)

### Packet header

The magic number tells the two packet kinds apart. There is no type, flags or channel field: the magic is the type, and the payload text names the command. (static)

Command packet, used for every text command in both directions:

| offset | size | type | endianness | meaning |
|---|---|---|---|---|
| 0 | 4 | uint32 | little | magic `0xF5EAF5F1`, bytes `f1 f5 ea f5` |
| 4 | 2 | uint16 | little | sequence number: per-connection counter, 0 when the channel is set up, +1 per packet sent |
| 6 | 2 | uint16 | little | total length, header included |
| 8 | 10 | bytes | none | zero |
| 18 | 2 | uint16 | little | payload length |
| 20 | n | bytes | none | payload: a field list |

(static)

Data packet, used for media on data connections, and for file transfer and talk audio on the command connection:

| offset | size | type | endianness | meaning |
|---|---|---|---|---|
| 0 | 4 | uint32 | little | magic `0xF9EAF5F1`, bytes `f1 f5 ea f9` |
| 4 | 4 | uint32 | little | sequence number, separate counter, 0 when the channel is set up |
| 8 | 4 | bytes | big | IPv4 address of the peer the socket connects to |
| 12 | 2 | uint16 | little | zero |
| 14 | 2 | uint16 | little | total length, header included |
| 16 | 4 | bytes | none | zero |
| 20 | n | bytes | none | payload; if it starts with ASCII `NVS`, the receiver skips its first 8 bytes |

(static)

- Sizes: the vendor client sends at most 1440 payload bytes in a command packet and 1448 in a data packet. It accepts any packet with a total length from 20 to 2048. (static)
- On receive, the vendor client checks only the magic and the total length. It ignores the sequence number, the zero bytes and the payload length at offset 18. (static)
- A command packet with no payload (total length 20) is valid. (static)

### Field lists

The payload of a command packet is a list of text fields.

- Fields are joined by TAB (`0x09`). The last field is followed by `\n\n\n` (`0a 0a 0a`). There is no trailing TAB and no NUL byte. (static)
- The I91FX ends many of its messages with the terminator twice, six `0a` bytes: every alarm, the `CMD EXCEPTION` idle message and `USER ACTIVATION`. `LOGON FINISHED` and the empty `<ip> PROXY` message end with one. The second terminator closes an empty command, and a client skips it. [example: event_motion_start] (verified: I91FX 2026-10-15)
- Integers are written in decimal ASCII. (static)
- A field can be empty: two TABs in a row. (static)
- Client to camera, a list has the form `<device IP>`, `<route>`, then the command tokens and arguments. The device IP is the address string given at logon. The route is `PROXY` for most commands, and `IP` for `LOGON` and the data-channel `CONNECT`. (static)
- Some client commands add the token `INNER` after the route. (static)
- Camera to client, a list has the same shape: two leading fields, then the command. The route is `IP` or `PROXY`. The vendor client also needs both TABs within the first 48 bytes and a route of at most 16 bytes, and it does not check the first field. A route of `HTTP` marks an XML message, which is out of scope here. (static)
- The camera's command tokens start with `INNER`, for example `INNER\tPARAGET\tDEVICETYPE`. A client dispatches on the leading tokens. (inferred)
- A missing trailing field reads as an empty string or 0. (static)
- There is no escaping. A TAB inside a value splits the field, and `\n\n\n` inside a value ends the command. Commands that carry free text encode it themselves: `LOGON` sends the user name and password in base64, see "Login". (static)

Text encoding:

- The client sends field bytes as it gets them. It does not convert a whole message. A few commands convert one text field to the device charset first, for example OSD text. (static)
- The client names its charset in a `LOGON` field, `UTF-8` by default. (static)
- The camera names its charset, `UTF-8` or `GB2312`, in its function report. The vendor client decodes received commands in that charset, except a few such as OSD text and log queries. (static)
- A client should send UTF-8 and decode received text with the charset the camera reports. (inferred)

### Delimiting messages

One WebSocket binary message from the I91FX can hold several packets. (verified: I91FX 2026-10-15) A client appends each message to one buffer and runs the loop below. The library does so, and sends one packet per message.

Over plain TCP, the receiver appends each read to a buffer per connection. Then it loops:

1. Fewer than 20 bytes left: stop and keep them.
2. Read the 4-byte magic. If it is neither magic, skip 1 byte and retry.
3. Read the total length, at offset 6 for a command packet and 14 for a data packet. If it is outside 20 to 2048, skip 1 byte and retry.
4. Fewer bytes left than the total length: stop and keep the partial packet.
5. Hand the packet to the channel and move on by the total length.

Leftover bytes move to the front of the buffer and wait for the next read. (static)

- One message over two reads: step 4 keeps the first part, and the next read completes it. (static)
- Two messages in one read: the loop hands both out, in order. [example: framing_two_messages_one_read] (static)
- In that example, the camera-side values of header bytes 4-5 and 8-19 are guesses, because the vendor client ignores them. The first field and the route `IP` in each payload are guesses too. (inferred)
- One command packet can hold several commands, each ending with `\n\n\n`. After it strips the device IP and route fields, the vendor client splits the rest at each `\n\n\n` and runs each piece. It drops a last piece that has no terminator. (static)
- The I91FX sends such packets. One held `<ip> IP INNER USER RESERVEPHONE 2 0 <e-mail> ""` and then `INNER SUPER GETUSERNUM 2`: only the first command carries the device IP and route. (verified: I91FX 2026-10-15)
- A client reads every command of a packet, in order. It gives each later command the device IP and route of the first, skips empty commands, and drops an unterminated last piece. A payload with no terminator at all is an error. The library does this. It keeps a later command whose second field is `IP` or `PROXY` as it is: that command already carries a device IP and route. (inferred)

### Matching replies to requests

- The sequence number does not match replies: the vendor client never reads it on receive. (static)
- Replies echo the request's command tokens under `INNER`. For example, the reply to `CMD\tGETPARAM` is `INNER\tCMD\tGETPARAM\tFINISHED`. A client routes each received command by its leading tokens. (static for the SDK side, inferred for the camera side)
- `GETPARAM` carries a session id. The vendor client takes it from a counter that starts at 1 at channel setup and grows by 1 before each use, so the first id is 2; after 999 it wraps to 1. Snapshot and ITS queries share the counter. The `FINISHED` reply returns the id and a result code, and the id matches the reply to its request. (static)
- The vendor client runs one `GETPARAM` at a time and waits up to 5 seconds for its reply. (static)
- It waits up to 10 seconds for the reply to other commands. (static)
- `FINISHED` result codes: 0 success, 1 and 2 failure, 4 still working (the client restarts its wait). (static)

### Reading one parameter

The client never sends a literal `PARAGET` request for the device type. It reads one parameter on demand with `CMD\tGETPARAM`. The camera answers with `INNER\tPARAGET\t<name>\t<values>`, then `INNER\tCMD\tGETPARAM\tFINISHED\t<session id>\t<result>`. (static for the request, inferred for the reply order)

`GETPARAM` request fields:

| field | value | meaning |
|---|---|---|
| 1 | device IP | address string given at logon |
| 2 | `PROXY` | route |
| 3 | `CMD` | command class |
| 4 | `GETPARAM` | command |
| 5 | decimal | parameter type; `20` reads the device type |
| 6 | decimal | channel, 0-based; a negative channel is sent as 0 |
| 7 | decimal | session id |

(static)

- Parameter type 20 reads the device type of the channel. The vendor client takes three values from the answer: COM port number, PTZ address and a device-type string of up to 32 bytes. (static)
- Only the `INNER\tPARAGET\tPTZ_PROTOCOL` and `INNER\tPARAGET\tPTZ_PROTOCOL_EX` messages carry those three values: COM port, address and device-type string for each channel in the reply. So type 20 most likely returns `INNER\tPARAGET\tPTZ_PROTOCOL`, and "device type" is the PTZ protocol of a channel, not the camera model. (inferred)
- `INNER\tPARAGET\tDEVICETYPE`, despite its name, carries per-port values, not these three. (static)
- The example reads the PTZ device type of channel 0 on `192.168.1.10`. Two values in it depend on earlier traffic: header bytes 4-5 (sequence 1, assuming `LOGON` was the only earlier packet) and the session id field `2` (assuming no earlier `GETPARAM`, snapshot or ITS query). [example: framing_parameter_get_request] (inferred)
- The example's sequence 1 is illustrative. The login packet count varies with the two-phase exchange (see "Login"), so the sequence may be 1 or 2.
- The vendor client takes the camera model, firmware version and factory id from the messages it gets at logon, with no request. (static)
- All device-level parameters: `<device IP>\tPROXY\tCMD\tGETDEVICEPARAM`, with no arguments. The camera ends its answer with `INNER\tCMD\tGETDEVICEPARAM\tFINISHED`. One channel: `CMD\tGETCHANNELPARAM\t<channel>`. (static for the requests, inferred for the reply)
- A few parameters do use a literal `PARAGET` request: route, optional `INNER`, `PARAGET`, the name tokens, then the arguments. (static)

## Login

The I91FX logs a client in with a two-phase exchange on the command channel, inside the WebSocket. The client sends `USER LOGON` with the credentials in base64. The camera answers `LOGONFAILED 3` and a salt, which asks for the salted MD5 form. The client sends a second `USER LOGON` with salted MD5 hashes. The camera then sends the channel data and `INNER LOGON FINISHED`. (verified: I91FX 2026-10-15; static: `web:/external/noplugin-master/h5player.js.gz`)

The steps, in order:

1. Client: `<ip> IP USER LOGON <b64 user> <b64 pass> "" 3 UTF-8 805306367 1`. [example: logon_request]
2. Camera: `<ip> IP INNER USER LOGONFAILED 3 1 1 <b64 salt> 0 0`. The salt decodes to 8 bytes and changes on every connection. [example: logon_reply_needs_md5]
3. Client: `<ip> IP USER LOGON <b64 md5(user+salt)> <b64 md5(pass+salt)> "" 3 UTF-8 0 1`. [example: logon_md5_request]
4. Camera: `INNER CMDID <id>`, `INNER LOGON CHANNELDATA FINISHED`, many `INNER PARAGET ...` messages, `<ip> IP INNER LOGON FINISHED`, then `<ip> PROXY INNER ALARM VIDEOLOST 0 0`. [example: logon_reply_success]

(verified: I91FX 2026-10-15; static: `web:/external/noplugin-master/h5player.js.gz`)

- The camera echoes the first field of the client's message. The web player sends the fixed address `192.168.0.2`. The library sends the camera's address. (verified: I91FX 2026-10-15)
- Both client messages have route `IP`. The `LOGONFAILED` replies and `INNER LOGON FINISHED` have route `IP` too. The `VIDEOLOST` message has route `PROXY`. The routes of the other messages in step 4 were not recorded. (verified: I91FX 2026-10-15)

### LOGON request

The first request is a framed message (see "Term: framed message"). F1 is the device IP and F2 the route; the LOGON route is `IP`, not `PROXY`. The vendor SDK sends F1..F12. The web player and the library send F1..F11, and the I91FX accepts that form. (static for the SDK form; verified for the 11-field form: I91FX 2026-10-15)

| field | value | type | meaning |
|---|---|---|---|
| F1 | `192.168.1.10` | string | device IP, the address given at logon |
| F2 | `IP` | string | route |
| F3 | `USER` | string | command class |
| F4 | `LOGON` | string | command |
| F5 | `YWRtaW4=` | ASCII base64 | user name, up to 16 bytes before encoding |
| F6 | `YWRtaW4xMjM=` | ASCII base64 | password, up to 16 bytes before encoding |
| F7 | empty | string | session token: empty on first logon, the saved token on a re-logon |
| F8 | `3` | decimal ASCII | `3` in the web player's message and in the library's; the vendor SDK sends 0; the meaning of 3 is not decoded |
| F9 | `UTF-8` | string | client charset, up to 16 bytes; `UTF-8` by default |
| F10 | `805306367` | decimal ASCII | constant `0x2fffffff` in the first request; `0` in the MD5 request |
| F11 | `1` | decimal ASCII | new-client-support flag; 1 by default |
| F12 | empty | ASCII base64 | optional second credential, up to 32 bytes; the vendor SDK sends it empty for a user and password logon; the web player and the library leave it out |

(static; verified for F1 to F11 with F8 `3`: I91FX 2026-10-15)

- F7 and F12 do not come from the credentials. F9 is the charset string the client declares. (static)
- The example logs on as `admin` / `admin123` to `192.168.1.10`. F7 is empty on a first logon. The sequence number is 0 because LOGON is the first packet on the connection. [example: logon_request] (verified: I91FX 2026-10-15)

Text encoding and special bytes:

- The client base64-encodes the user name into F5 and the password into F6 before it builds the field list. A TAB, newline or non-ASCII byte in either value becomes ASCII base64, so it never reaches the TAB-delimited field layer as a literal separator. (static)
- The raw credential bytes are encoded as given. The client charset is `UTF-8` by default (F9), so a non-ASCII credential should be its UTF-8 bytes, then base64. (static)
- Example: the password `ad<TAB>min` (bytes `61 64 09 6d 69 6e`) encodes to F6 `YWQJbWlu`. The field carries no literal `0x09`; the only `0x09` bytes in the message are the field separators. [example: logon_request_password_with_tab] (static)

### Salted MD5 phase

When the camera answers `LOGONFAILED 3`, the client sends a second `USER LOGON` on the same connection. (verified: I91FX 2026-10-15; static: `web:/external/noplugin-master/h5player.js.gz`)

- F5 is the base64 of the raw MD5 digest of the user name followed by the salt. F6 is the same for the password. The text is UTF-8. The salt is the first 8 bytes of the decoded salt field, the ninth field of the reply when the device IP counts as the first.
- F7 stays empty, F8 stays `3`, F9 stays `UTF-8`, F10 is `0` and F11 is `1`.
- The example uses the placeholder salt `00 01 02 03 04 05 06 07`. [example: logon_md5_request]

### Refusal

`LOGONFAILED` carries a reason code after the command. (verified: I91FX 2026-10-15)

| reason | meaning | seen |
|---|---|---|
| 3 | send the salted MD5 form; the salt follows | after the first request |
| 2 | the credentials are wrong | after the MD5 request, with a wrong password |
| 4 | not known; the web player stops its retries on it too | no |

- A wrong password changes nothing before step 3: the camera still answers the first request with `LOGONFAILED 3`. The refusal comes where `INNER CMDID` would come: `<ip> IP INNER USER LOGONFAILED 2 1 1 <b64 salt> 1 0`. [example: logon_reply_refused] (verified: I91FX 2026-10-15)
- The web player stops retrying on reasons 2 and 4. (static: `web:/external/noplugin-master/h5player.js.gz`)
- Only one wrong password was tried, to avoid a lockout. What the camera sends for an account lock or for too many users is not known: see "Open questions".
- A client treats a `LOGONFAILED` with a reason other than 3, and a second `LOGONFAILED 3`, as a refusal of the credentials. The library raises an authentication error then. A close or a timeout during login is a connection error instead, and the library retries it. (inferred)

### Successful reply

The I91FX ends a successful login with these camera messages, in order: `INNER CMDID <id>`, `INNER LOGON CHANNELDATA FINISHED`, many `INNER PARAGET ...` messages, `<ip> IP INNER LOGON FINISHED`, then `<ip> PROXY INNER ALARM VIDEOLOST 0 0`. The login ends at `INNER LOGON FINISHED`. A client does not stop at `CHANNELDATA FINISHED`. (verified: I91FX 2026-10-15)

`INNER CMDID <id>` carries the command id. `INNER LOGON FINISHED` marks a successful login. (static)

- Neither message carries device id, model, serial, firmware or channel count. The vendor client reads no field of `INNER LOGON FINISHED`. (static)
- The vendor client takes model, firmware and factory id from the messages it gets during logon, and channel count and other per-channel data from the function report (`INNER\tPARAGET\tFUNCASSEMBLE`). These are separate messages, not the login reply; their field layout is deferred. See "Open questions" and "Reading one parameter". (static)
- The example is the `INNER LOGON FINISHED` message. The camera echoes the client's first field and uses route `IP`. Header bytes 4-5 and 8-17 were not recorded. [example: logon_reply_success] (verified: I91FX 2026-10-15)

### LOGOFF request

Logoff is a framed message `USER\tLOGOFF`. After a plain second login phase it carries the user name in cleartext as F5. (static)

| field | value | type | meaning |
|---|---|---|---|
| F1 | `192.168.1.10` | string | device IP |
| F2 | `IP` | string | route |
| F3 | `USER` | string | command class |
| F4 | `LOGOFF` | string | command |
| F5 | `admin` | string | user name, cleartext after a plain second phase |

(static)

- The vendor client sends this form only after a plain second phase. After a base64 logon with no second phase it sends no LOGOFF and just closes the socket. After an encrypted second phase it sends an encrypted user name, which is out of scope here. (static)
- The example logs off `admin`. Its sequence number depends on how many packets went before, so it is a guess. [example: logoff_request] (inferred)

## Encrypted login

The I91FX needs the salted MD5 login, which "Login" describes. The vendor client also has an encrypted login path with RSA and AES, which is out of scope here. The "Status summary" table keeps this area empty. (static)

## Heartbeat and logoff

On the I91FX, the client sends an empty command packet every 5 seconds and drops the connection after 20 seconds without any data from the camera. The web player does so, and the library follows it. The camera sends its own idle messages about every 10 seconds. A session stayed up 25 minutes with no drop. (static: `web:/external/noplugin-master/h5player.js.gz`; verified: I91FX 2026-10-15)

The vendor SDK uses 3 seconds for the heartbeat and 30 seconds for the silence limit. The sections below give both. Logoff is under "LOGOFF request" in "Login".

### Heartbeat message and sender

The heartbeat is a command packet with no payload: the 20-byte header and nothing else. It is not a framed message, because it has no fields and no `\n\n\n` (see "Term: framed message"). (static)

| offset | size | type | endianness | meaning |
|---|---|---|---|---|
| 0 | 4 | uint32 | little | magic `0xF5EAF5F1`, bytes `f1 f5 ea f5` |
| 4 | 2 | uint16 | little | sequence number: the command connection's counter, +1 per packet sent |
| 6 | 2 | uint16 | little | total length, always `20` (`14 00`) |
| 8 | 10 | bytes | none | zero |
| 18 | 2 | uint16 | little | payload length, always `0` |

(static)

- Only the sequence number varies. A heartbeat uses the same counter as every command, so it shifts later sequence numbers. The counter starts at 0 on each new connection. (static)
- The example uses sequence 2, which assumes the two `LOGON` packets were the only earlier traffic. A real heartbeat carries the counter's current value. [example: heartbeat_request] (inferred)
- The client sends it on the command connection. The vendor client sends it while the logon runs and after it succeeds. (static)

Other messages with "heartbeat" in the name:

- Data connections get no heartbeat. (static)
- `INNER\tCMD\tMODULE\tHEARTBEAT\t<n>` is a camera message. It carries one integer. The vendor client reads it and treats the message like any other. (static)
- The client can send a reply. It is a framed message. After the device IP, the route and an optional `INNER`, its fields are `CMD`, `MODULE`, `HEARTBEAT`, `RESPONSE`, an integer and a string of at most 16 bytes. Nothing shows that the camera expects it. See "Open questions". (static)

### Interval

On the I91FX the interval is 5 seconds: the web player sends an empty command frame that often, and the library does the same. (static: `web:/external/noplugin-master/h5player.js.gz`)

The vendor SDK's interval is 3 seconds. (static)

- The value is a constant, and no setting changes it. Other traffic does not delay or replace a heartbeat. (static)

### Camera reply

The vendor client never waits for a heartbeat answer and never matches one. (static)

- On the I91FX the camera sends two idle messages about every 10 seconds: `<ip> PROXY INNER CMD EXCEPTION <n> 0`, where `<n>` is 0 and sometimes 2 or 4, and an empty `<ip> PROXY` message. A client counts both as proof of life and does not pass them on as events. (verified: I91FX 2026-10-15; the library does the same)
- Whether these messages answer the heartbeat is not known: they come every 10 seconds and the heartbeat every 5. See "Open questions".
- The vendor client counts any complete packet from the camera, command or data, with or without payload, as proof of life. (static)
- An empty command packet (total length 20) from the camera is valid, but nothing marks it as a heartbeat answer. (static)
- So the vendor client keeps a logged-on session only if the camera sends at least one packet every 30 seconds. (static)
- An empty reply, in the layout above, would count as proof of life. The vendor client does not show that the camera sends one, and it cannot tell an answer from a camera timer. (inferred)
- There is no `heartbeat_reply` example, because the vendor client does not show what the camera sends. See "Open questions".

### Silence timeout

The client side below is the vendor client's. The camera side is not known: see "Open questions".

- On the I91FX, the web player reconnects after 20 seconds without data from the camera. The library drops the connection after the same time and reconnects with its usual back-off. With idle messages every 10 seconds, the limit spans two of them. (static: `web:/external/noplugin-master/h5player.js.gz`; inferred for the margin)
- Logged-on session: the vendor client drops the session 30 to 31 seconds after the last packet from the camera. (static)
- Logon phase: the vendor client closes the connection more than 10 seconds after the logon began, or after the last non-empty command packet from the camera. (static)
- Data channels: each data connection has its own limit of 30 seconds without a data packet. (static)
- After the logged-on timeout the vendor client closes the command connection without sending `LOGOFF`. (static)
- A client should send the heartbeat every 5 seconds on the I91FX, count any received packet as proof of life, and treat 20 seconds of silence as a lost session. The vendor SDK uses 3 and 30 seconds. (inferred)

## Event push

The camera pushes alarm events as framed messages on the command channel (see "Term: framed message"). The I91FX uses route `PROXY` for `MOTIONDETECT` and `VIDEOLOST`: `<ip> PROXY INNER ALARM <KIND> <channel> <state> [<id>]`. (verified: I91FX 2026-10-15) The other kinds (`MOTIONDETECT_CAR`, `VIDEOCOVER`, `VCA`) were not seen on the I91FX, so their route is not known. Their examples use `IP`. The vendor client and the library accept `IP` or `PROXY`. (inferred) After the device IP and route, each one starts `INNER\tALARM\t<KIND>`, or `INNER\tCMD\tALARM\tALERT`, or `INNER\tONVIF\tVCAALARM`. (static)

### Enabling event upload

No. The client sends no subscribe or enable message. Events arrive on the logged-on connection. (verified: I91FX 2026-10-15; static)

- No `ALARM UPLOAD`, `ALARM SUBSCRIBE` or `ALARM ENABLE` command string exists in the vendor client. (inferred)
- The camera's own detection settings decide which events it sends: see "Start and stop". (verified: I91FX 2026-10-15)

### Event messages and their fields

All fields are decimal-ASCII integers or TAB-separated strings, following the device IP, the route, and the `INNER ALARM` (or `INNER CMD ALARM`) tokens. Arguments below are numbered from the first field after those tokens.

`INNER\tALARM\tMOTIONDETECT` and `INNER\tALARM\tMOTIONDETECT_CAR` carry the same fields. (static)

| arg | type | meaning |
|---|---|---|
| A1 | int | channel, 0-based |
| A2 | int | alarm state: nonzero active, 0 cleared |
| A3 | string, <=32 | optional trailing field; the vendor client does not read it; the I91FX sends a 16-digit event id here (verified: I91FX 2026-10-15) |

- The vendor client reads A1 and A2 and ignores A3. (static)

`INNER\tALARM\tVIDEOCOVER` has the same three fields. (static)

- A2 is the cover state of the channel. [example: event_video_cover] (static)

`INNER\tALARM\tVIDEOLOST` carries A1 channel and A2 video-loss state. (static)

- The I91FX sends `<ip> PROXY INNER ALARM VIDEOLOST 0 0` right after login. (verified: I91FX 2026-10-15)

`INNER\tALARM\tINPORT` carries A1 port, A2 state, A3 channel (the camera may leave it out), A4 string. (static)

`INNER\tALARM\tVCA` is variable length. (static)

| arg | type | meaning |
|---|---|---|
| A1 | int | channel, 0-based |
| A2 | int | alarm state |
| A3 | int | reserved |
| A4 | int | rule/event type (seen: 0, 1, 2, 15, 30, 54, 58, 62, 64, 98) |
| A5, A6 | int | rule parameters |
| A7 | string | time, `h:m:s:ms` |
| A8, A9 | int | rule parameters |
| A10 | int or CSV or string | rule-specific, chosen by A4 |
| A11 | int | rule parameter |
| A12 | int | target-group count; that many CSV groups follow |
| ... | CSV | per target: type and `h:m:s:ms` time |
| An | int | rule count; that many CSV rules follow |
| last-1 | string, <=32 | rule name |
| last | string, <=256 | extra |

- A4 selects the analytic. The exact value-to-rule map is not fully decoded, so it is an open question. [example: event_vca_intrusion] (static)
- `INNER\tONVIF\tVCAALARM` is a separate ONVIF-format VCA alarm. Its fields are not decoded here. (static)

`INNER\tALARM\tNOTIFY` is a generic envelope: A1 sub-type, A2 channel, A3 state, A4..A7 ints, A8 and A9 strings. A1 names the kind of alarm. (static)

| A1 sub-type | meaning |
|---|---|
| 0 | video loss |
| 1 | exception / offline; A4 = 1 marks a separate case |
| 2 | motion |
| 3 | video cover |
| 5 | alarm input |
| 20 (`0x14`) | not decoded; carries a packed date in A8 |
| 257 (`0x101`) | not decoded |

`INNER\tCMD\tALARM\tALERT` is the smart-alert message. It carries A1..A7 ints, A8 time `h:m:s:ms`, A9 a packed date string, and A10. A1 is the channel. No field carries a start or stop state, so this message is one-shot. (static)

### Start and stop

Start and stop ride in one message as the alarm-state field (A2), not as separate commands. There is no stop command. (static)

- On the I91FX, while a person is in view, the camera sends `<ip> PROXY INNER ALARM MOTIONDETECT 0 1 <id>` once per second. `<id>` is a 16-digit number. At the end of the event it sends one `... MOTIONDETECT 0 0 <same id>`. [example: event_motion_start] [example: event_motion_stop] (verified: I91FX 2026-10-15)
- A client reads state 1 as the start or a refresh, and state 0 as the end of the event at once. The library keeps a 10-second timer as a fallback for a lost stop. (inferred: library behaviour)
- The smart filter gates `MOTIONDETECT`. With person and vehicle detection on and all-motion off, an object that moved with no person in view gave no event. (verified: I91FX 2026-10-15)
- A2 nonzero means active and 0 means cleared. The vendor client reads A2 of `VIDEOCOVER` and `VIDEOLOST` as the channel's current alarm state. The state codes of the other alarms are inferred from the field name and from that use. (inferred)
- `ALARM ALERT`, `VCA` and `ONVIF VCAALARM` carry no clean on/off state. So a client cannot rely on a stop for every event and must time out stale events. (static)
- The camera sent a stop at the end of the events seen. Nothing proves it always does, so the library timeout stands regardless. (inferred)

### Human and vehicle

Vehicle has its own command, `INNER\tALARM\tMOTIONDETECT_CAR`. Human motion has no own command; it rides in `INNER\tALARM\tMOTIONDETECT`, the same message as plain motion, so a person is indistinguishable from pixel motion at this command. (static)

- A person in view gives `MOTIONDETECT` on the I91FX: with person and vehicle detection on and all-motion off, a person did and other movement did not. [example: event_smart_person] (verified: I91FX 2026-10-15)
- While all-motion detection is on, a client cannot tell a person from other movement. (inferred)
- The `_CAR` suffix names the vehicle case; the app's alarm names confirm the person/car split. No vehicle has been in view yet, so `MOTIONDETECT_CAR` is not seen on the I91FX: see "Open questions". [example: event_smart_vehicle] (inferred)
- Finer target classification appears only inside the VCA target array (A12 groups) and the ONVIF VCA alarm, not as a top-level field. Those target-type codes are not decoded. (inferred)

### Event channel numbering

The event channel is 0-based, the same space as `GETPARAM`. (static)

- The vendor client uses the message channel as it is, with no `+1` or `-1`, and rejects a negative channel. (static)

### Message to library kind

| message | kind | status |
|---|---|---|
| `INNER ALARM MOTIONDETECT` | motion | static |
| `INNER ALARM MOTIONDETECT` (smart human) | person | verified |
| `INNER ALARM MOTIONDETECT_CAR` | vehicle | inferred |
| `INNER ALARM VCA`, A4 = 2 | intrusion | inferred |
| `INNER ALARM VCA`, A4 = 0 | line | inferred |
| `INNER ALARM VIDEOCOVER` | tamper | inferred |
| `INNER ALARM VIDEOLOST` | video_loss | static |
| `INNER ALARM INPORT` | (alarm input, no kind) | static |
| `INNER ALARM NOTIFY` | (envelope, maps to the row above) | static |
| `INNER CMD ALARM ALERT` | (smart alert) | static |
| `INNER ONVIF VCAALARM` | (onvif vca) | static |

- `motion` and `person` share one command, so the library reads both as the same event; only vehicle is distinct. (inferred)
- `intrusion` and `line` share the VCA command and differ by A4; the value map is an open question. The app's alarm names cover motion, loss, cover and the smart types. (inferred)

## Talk channel

Talk is one-way: the client sends microphone or announcement audio to the camera speaker. The client opens talk with a `CMD TALK BEGIN` command on the command channel, waits for the camera to accept, then streams encoded audio as data packets on that same connection, and ends with `CMD TALK END`. (static)

On the I91FX, talk over the WebSocket makes no sound. `<ip> PROXY CMD TALK BEGIN 1 8000` gets `PROXY INNER CMD TALK BEGIN OK`, and `TALK END` gets the matching `END OK`, but audio sent as data packets after that plays nothing. (verified: I91FX 2026-10-15) The two trailing numbers are the encode type 1 (G711A) and the sample rate 8000. (inferred) The library has no talk path. Sound reaches the speaker through the RTSP backchannel: see "Backchannel". The rest of this section is what the vendor client sends.

The vendor client has two talk forms that share the same command words. (static)

- Single talk: `CMD TALK BEGIN` with route `PROXY` and no channel. (static)
- Channel talk: route `NVR`, then the channel number, then `CMD TALK BEGIN`. (static)

### Request, accept and refuse

An IP-added camera uses the channel-talk request. The app uses channel talk for an IP camera added by IP, and single talk only for one added by DDNS. (static)

The channel number on the wire is the app channel minus 1. A single-channel IP camera has app channel 1, so it talks to wire channel 0. (static for the subtraction, inferred for app channel 1)

Channel-talk `BEGIN` request fields (client to camera):

| field | value | meaning |
|---|---|---|
| F1 | `192.168.1.10` | device IP |
| F2 | `NVR` | route token for channel talk |
| F3 | `0` | channel, 0-based, decimal ASCII |
| F4 | empty | reserved, always empty |
| F5 | `CMD` | command class |
| F6 | `TALK` | command |
| F7 | `BEGIN` | start |
| F8, F9 | decimal | optional: audio encode type and sample rate, added only when the camera advertises a talk coder list |

(static)

- The single-talk request drops F3 and F4 and uses route `PROXY`: `192.168.1.10\tPROXY\tCMD\tTALK\tBEGIN`. (static)
- The example is the channel-talk `BEGIN` for channel 0 on `192.168.1.10`, without the optional audio fields. The sequence number depends on earlier traffic, so it is a guess. [example: talk_start_request] (inferred)

The camera answers on the command channel with the result token appended. Single talk gets `INNER\tCMD\tTALK\tBEGIN\tOK`, `INNER\tCMD\tTALK\tBEGIN\tERROR` or `INNER\tCMD\tTALK\tEND\tOK`. The channel-talk reply starts with `INNER\tNVR`. A camera message carries route `IP` or `PROXY` (see "Field lists"). So the channel reply is `<ip>\tIP\tINNER\tNVR\t<channel>\t...\tBEGIN\t<OK|ERROR>`, not the request's `NVR` route. (static for the SDK side, inferred for the camera side)

- In the channel-talk reply the vendor client counts tokens from `INNER`, after the IP and route are stripped, the same base as for the alarms. So channel is at index 2, the `BEGIN`/`END` token at 6 and `OK`/`ERROR` at 7; indexes 3-5 are not read. Do not confuse this base with the request table above, which is 1-based and counts the route as F2. `BEGIN OK` accepts, `BEGIN ERROR` refuses, and `END OK` acknowledges the end. (static)
- On accept the client sends audio in the codec it chose for the request: see "Codecs, sample rate, frame size and pacing". On refuse it stops talk. (static)
- `TALKREFUSE` is a separate client-to-camera command (`CMD TALKREFUSE <n>`); it is not the camera's refuse. The camera refuses by `CMD TALK BEGIN ERROR`. (static)

### Transport: the command connection, not a new socket

The audio travels on the command connection. The client wraps each audio frame in a data packet (magic `0xF9EAF5F1`) and writes it to the command connection, the same connection that carried `LOGON`. The app opens no new TCP connection for talk. (static)

- A data packet on a command connection is already expected; the framing section notes it for file transfer. Talk audio is the other case. (static)
- The vendor client also has a two-way talk mode on a separate data connection, which is out of scope here. (static)
- The camera IP at offset 8 of the data header is the socket peer in network order. The sequence number is a separate data counter. (static)

### Audio frame layout

Each audio frame is a data packet whose payload carries a short audio sub-header and one encoded block. The channel-talk payload starts with `NVR`, lists the channel, then embeds an `NVS` block with the device IP and the audio. (static)

Channel-talk payload (inside the `0xF9EAF5F1` data packet), G711A, channel 0:

| offset | size | type | endianness | meaning |
|---|---|---|---|---|
| 0 | 4 | bytes | none | `NVR\0` (`4e 56 52 00`) |
| 4 | 1 | byte | none | TAB (`0x09`) |
| 5 | n | bytes | none | channel numbers as raw bytes, comma-separated; one byte `0x00` for channel 0 |
| 5+n | 1 | byte | none | TAB (`0x09`) |
| 6+n | 1 | byte | none | zero |
| 7+n | 1 | byte | none | TAB (`0x09`) |
| 8+n | 4 | bytes | none | `NVS\0` (`4e 56 53 00`) |
| 12+n | 4 | bytes | see note | device IP, byte-swapped by the sender |
| 16+n | 4 | bytes | none | audio sub-header `00 01 <code> 00` |
| 20+n | k | bytes | none | encoded audio |

(static)

- The single-talk payload has no `NVR` prefix and no channel list: `NVS\0`, the byte-swapped IP, the 4-byte audio sub-header, then the audio. (static)
- The IP in the `NVS` block is not in network order. Its four bytes come in reverse order, so `192.168.1.10` becomes `0a 01 a8 c0`. (static)
- The audio sub-header third byte encodes the block size: the frame carries `code * 2` audio bytes. It is `0x28` (40) for G711A and G711U, `0x16` for ADPCM, `0x0a` for G726. AMR has no sub-header and uses the encoder's own length. (static)
- The `NVS` skip-8 rule in the framing section is the vendor client's receive rule, which skips 8 bytes only when a payload starts with `NVS`. The channel payload starts with `NVR`, so that rule would not apply, but the camera is the receiver here and its parsing is not visible. (inferred)
- The example is one channel-0 G711A frame of 80 audio bytes. The 80 audio bytes are G711A of PCM silence, a placeholder: real bytes depend on the microphone. The data sequence number also depends on earlier audio. [example: talk_audio_frame_g711a] (inferred)

### Codecs, sample rate, frame size and pacing

The codec ids: 1 G711A, 2 G711U, 3 ADPCM, `0x24` (36) G726, `0x15` (21) AMR. (static)

- Channel talk uses one codec per logon and channel, chosen at request time. The client starts from the channel's encoder, 1 by default. If the camera advertises a coder list, the client picks an id from `TALKCODER_LIST`, falling back to id 1 then id 2. The sample rate is the lowest the camera lists for the chosen id, else 8000. (static)
- Single talk is different: the vendor client sends the audio in every codec the device is set to, with no acceptance check. (static)
- The camera reports its codecs as `INNER PARAGET TALKCODER_LIST`: a leading integer, the channel, a count, then up to 40 `id:rate` pairs. (static)
- The sample rate is 8000 Hz: the chosen rate defaults to 8000 and the app captures 8 kHz mono PCM16. (static)
- The app feeds 640-byte PCM16 frames. The vendor client splits each 640-byte frame into 4 sub-frames of 80 samples and sends one data packet per sub-frame; AMR uses 2 sub-frames. A G711A sub-frame is 80 audio bytes. (static)
- Pacing comes from the microphone. The app reads 640-byte frames from the microphone and sends each at once, which is 40 ms of audio at 8 kHz. The vendor client adds no timer. (inferred)

### Stopping talk and the busy case

Talk stops with a `CMD TALK END` command that mirrors the start: `CMD TALK END` with route `PROXY` for single talk, and route `NVR` plus channel for channel talk. Both wait for `CMD TALK END OK`. (static)

- The example is the channel-talk `END` for channel 0. Its sequence number is a guess. [example: talk_stop_request] (inferred)
- The camera refuses channel talk with `INNER\tNVR\t<channel>\t...\tBEGIN\tERROR` on route `IP`. A likely trigger is another client already holding talk; the vendor client does not show it. The app also refuses a second talk of its own before it sends anything. [example: talk_refused_busy] (static for the parse, inferred for the camera trigger)
- In the busy example, route `IP` and the `INNER\tNVR` prefix follow the vendor client. The channel sits at token index 2, the result at 7, both counted from `INNER`; indexes 3-5 are not read, so their values are a guess that mirrors the request. The vendor client ignores the camera header bytes. [example: talk_refused_busy] (inferred)

### Talk channel numbering

Channel talk is 1-based in the app and 0-based on the wire. The app subtracts 1, so app channel 1 is wire channel 0. A single-channel IP camera is assumed to be app channel 1, hence wire channel 0. (static for the subtraction, inferred for app channel 1)

## Backchannel

The I91FX plays sound that a client sends over the ONVIF RTSP backchannel. The library uses it for every sound it sends. The private protocol's talk path plays nothing: see "Talk channel". (verified: I91FX 2026-10-15)

### Session

- RTSP runs on port 554 with Digest login. The main stream is `rtsp://<host>:554/1/1`. (verified: I91FX 2026-10-15)
- `DESCRIBE` with the header `Require: www.onvif.org/ver20/backchannel` adds an audio section to the SDP: `m=audio 0 RTP/AVP 0 8`, `a=sendonly` and `a=control:rtsp://<host>:554/1/1/trackID=3`. It offers PCMU (payload 0) and PCMA (payload 8). (verified: I91FX 2026-10-15)
- `SETUP` on that control URL with `Transport: RTP/AVP/TCP;unicast;interleaved=4-5` returns 200 with `Session: <id>;timeout=60`. `PLAY` returns 200. (verified: I91FX 2026-10-15)
- The client sends the audio as RTP packets in interleaved frames: the byte `$`, the channel byte 4, a 2-byte length, then the RTP packet. PCMA sent this way plays on the camera speaker. (verified: I91FX 2026-10-15)
- The library prefers PCMA over PCMU, because the camera's own streams carry PCMA. PCMU is offered but was not tried. (inferred)
- The library sends 160 samples (20 ms at 8 kHz) per RTP packet, paced in real time. It reads and drops the data the camera sends back. When sending falls more than 0.2 s behind, the library restarts the clock instead of sending a burst. (inferred: library behaviour)
- A generated tone sent this way stops at once when the client ends the stream. (verified: I91FX 2026-10-15)
- The session times out after 60 seconds. On a long stream the library sends `GET_PARAMETER` every 30 seconds, and the session ends with `TEARDOWN`. (verified: I91FX 2026-10-15 for the timeout in the `SETUP` reply; inferred for the effect of `GET_PARAMETER`)
- A second `SETUP` of the same track in one RTSP session gets `455 Method Not Valid in This State`. Two separate sessions may each `SETUP` and `PLAY` the backchannel (`trackID=3`) at the same time, but only the first plays: see "Speaker ownership". (verified: I91FX 2026-10-15 for the two sessions, 2026-10-16 for the first-only rule)
- The camera answers with the host the client put in its request. A `DESCRIBE` of `rtsp://127.0.0.1:18600/1/2`, with that URL as the Digest `uri`, gets 200 and `Content-Base: rtsp://127.0.0.1:18600/1/2/`. `SETUP` and `TEARDOWN` on that host work. So an RTSP relay needs no URL rewriting and no login of its own. (verified: I91FX 2026-10-15)

### Speaker ownership

The camera plays one backchannel session at a time. The test played sound on several sessions and listened through the camera's own microphone (`/1/1` audio, read through go2rtc). The microphone idles at RMS about 10. It reads about 27000 while the speaker plays at `outputVolume` 80, about 0.35 s after the audio is sent. So the microphone shows reliably whether sound plays. (verified: I91FX 2026-10-16)

| Step | Heard |
|---|---|
| Siren tone alone on a `/1/1` session | yes |
| 440 Hz beep on a second session (`/1/2`, the "talk" session) | yes |
| Siren on a new session 2 s later, talk session open and silent | no |
| Siren again after 35 s, talk session still open | no |
| Talk session closed, then siren on a new session | yes |

(verified: I91FX 2026-10-16)

- The camera plays only the first open backchannel session. It answers 200 OK to every other session and drops its audio, with no error, until the first one closes. (verified: I91FX 2026-10-16)
- An idle owner is not released after 39 seconds. (verified: I91FX 2026-10-16)
- One session can be reused. On a single session the camera played a tone sent 3 seconds after `PLAY`. It played again after each 4-second gap with no packets. It did so in three cases. The first kept the SSRC and continued the timestamps. The second jumped the timestamp by the gap. The third used a new SSRC and sequence. (verified: I91FX 2026-10-16)
- Not tested: whether a waiting session takes over when the owner closes. The simulator assumes the oldest one does.
- The library's `Speaker` opens one session. It keeps the session for 3 seconds after the last sound and moves the audio of each new owner onto it. So the library never has two sessions open at once, though one session can follow another. (inferred: library behaviour, `lib/README.md`, Speaker)

### go2rtc and the relay

Home Assistant's go2rtc 1.9.14 reads the camera through one RTSP connection and sends every talk through it.

- Adding a backchannel to a producer that is already playing calls `Reconnect()`. That closes the RTSP connection and opens a new one. The new connection runs `DESCRIBE`, then sets up every receiver, every sender kept from earlier talks, and the new backchannel, in that order. So the live view reconnects at every talk start. (static: go2rtc 1.9.14, `pkg/rtsp`)
- go2rtc keeps its backchannel open for about 30 seconds after the last WebRTC session ends, but only toward the relay. The bench tests no longer wait. They turn the siren on right after a session and check that the simulator records it. (inferred: `bench/README.md`)
- go2rtc keeps a talk sender after the talk ends. The next talk reconnects. It sets the backchannel up twice on the new session, once for the kept sender and once for the new one. The camera refused the repeat with 455. go2rtc dropped the stream, and talk kept failing until go2rtc restarted. This was with go2rtc connected straight to the camera. (verified: I91FX 2026-10-15, with go2rtc 1.9.14 run alone against the camera)
- The interleaved channel go2rtc asks for is twice the media index in the `DESCRIBE` answer. For the I91FX SDP (video, audio, backchannel) the backchannel is `interleaved=4-5`. go2rtc reads the channel back from the `Transport` header of the reply. (static: go2rtc 1.9.14, `pkg/rtsp`)
- go2rtc takes the session id only from the first `SETUP` reply that carries one, and ignores it in later replies. (static: go2rtc 1.9.14, `pkg/rtsp`)
- Every client of a stream shares go2rtc's one RTSP connection. Each client's talk is its own sender, and all senders write to the same interleaved channel. A sender keeps its browser's RTP SSRC, so the SSRC tells talkers apart. (static: go2rtc 1.9.14, `pkg/rtsp`, `packetWriter` in `consumer.go`)
- The session go2rtc holds keeps the backchannel after the talk ends. So the camera mutes every sound the library sends on its own session. This is why a siren stayed silent right after the intercom. (inferred: the ownership rule above and the go2rtc source)
- The integration's RTSP relay answers the backchannel `SETUP` itself and never forwards it, so the camera never gives the backchannel to go2rtc's session. It decodes the talk RTP that go2rtc sends on that channel and passes it to the `Speaker` by SSRC (`lib/README.md`, RTSP relay). (inferred: library behaviour)
- A relay that answered only the repeated `SETUP` let go2rtc's talk work twice in a row, with the live view up. (verified: I91FX 2026-10-15)

### Speaker acceptance

The test ran the library alone, with a `Speaker` behind an `RtspRelay`. A script played go2rtc's part through the relay: `DESCRIBE` with the backchannel `Require`, `SETUP` of the audio track, `PLAY`, then the backchannel `SETUP`. It sent PCMU talk frames on channel 4. The camera's microphone, read straight from `/1/1`, showed what played. Each source used its own tone, and the frames the `Speaker` sent matched what the microphone heard.

- The relay answered the backchannel `SETUP` with 200, the requested `Transport` and the camera's session id. (verified: I91FX 2026-10-16)
- Talk played. After 1.03 seconds of silent frames the talk ended. The alarm tone then played at once, while the client's session with its backchannel `SETUP` stayed open. This is the case that failed before. (verified: I91FX 2026-10-16)
- Talk that started during the alarm stopped it, and the talk played. (verified: I91FX 2026-10-16)
- The alarm started during talk played, and the talk was muted. When the alarm ended, the talk, still speaking, played again. (verified: I91FX 2026-10-16)
- A second SSRC on the same connection took the speaker from the first. The first SSRC stayed muted when its frames moved to a new relay connection. (verified: I91FX 2026-10-16)
- The first talk after an idle speaker waited 0.41 seconds for the session to open. A talk inside the 3-second linger reached the camera in about 2 ms. From send to microphone took 0.4 to 0.6 seconds. (verified: I91FX 2026-10-16)
- Not tested yet: talk from the wall card through Home Assistant's go2rtc.

### Volume

- `GET /ISAPI/System/TwoWayAudio/channels/1` returns `outputVolume` 80, `speakerVolume` 80 and `audioOutputType` `innerspeaker`. A PUT of the whole document is accepted. (verified: I91FX 2026-10-15)
- Sound sent over the backchannel was loud at `outputVolume` 80. (verified: I91FX 2026-10-15)
- `outputVolume` drives the speaker. At 30, both a built-in warning and sound sent over the backchannel played quieter than at 80. The library writes `outputVolume`. What `speakerVolume` does is not known. (verified: I91FX 2026-10-15)

## LAN discovery

The app finds cameras with a UDP search, not with the TCP protocol. The datagram has its own 10-byte envelope. It is not the TCP packet header. (static)

### Ports and groups

- Source port: the app opens one IPv4 UDP socket, binds it to `0.0.0.0:6001` and sends from it. So the source port is 6001. (static)
- Destination port: each search datagram goes to port 3000 and again to port 4000. (static)
- Destination addresses: the app runs in multicast mode. It sends to `234.56.78.9`, then to `239.255.255.250`. One search is four datagrams: group 1 port 3000, group 1 port 4000, group 2 port 3000, group 2 port 4000. Both groups get the same datagram. (static)
- Socket setup: the app joins both groups on the default interface and sends with multicast TTL 64. (static)
- The vendor client also has a broadcast mode that sends to `255.255.255.255`. The app never selects it. (static)
- Reply port: the app reads replies on the same socket, so on UDP 6001. It takes any datagram with the right magic, from any source address and port. (static)
- The I91FX answers a seek from UDP port 3000, by unicast to the sender's port 6001. (verified: I91FX 2026-10-15; static)
- The vendor client can also send the same datagram to one IP on ports 3000 and 4000. The app never does. (static)

### Seek request

Every discovery datagram, in both directions, is a 10-byte envelope followed by a text payload.

| offset | size | type | endianness | meaning |
|---|---|---|---|---|
| 0 | 4 | uint32 | little | magic `0xE5E5BEBE`, bytes `be be e5 e5` |
| 4 | 2 | uint16 | little | id: 0 in every request the app sends |
| 6 | 2 | uint16 | little | flag: 0 in every request the app sends; non-zero asks the receiver to acknowledge |
| 8 | 2 | uint16 | little | payload length |
| 10 | n | bytes | none | payload: ASCII text |

(static)

The search payload is 30 bytes: five fields joined by TAB (`0x09`), then `\n\n\n`.

| field | value | meaning |
|---|---|---|
| 0 | `IP` | literal text, where a TCP field list has the device IP |
| 1 | `IP` | literal text, where a TCP field list has the route |
| 2 | `NEWM4V00` | protocol marker |
| 3 | `CMD` | command class |
| 4 | `SEEKNVSS` | command: search for cameras |

(static for the bytes, inferred for the meaning of fields 0 and 1)

- The whole datagram is 40 bytes. It has no input: no address, no MAC, no credentials. [example: discovery_seek_request] (static)
- No request the app sends asks for an acknowledgement: every datagram carries flag 0. So the search has no retry. (static)
- Other requests use the same envelope and marker with other command words: `XCHGIP`, `XMODAD`, `XCHGIPV6`, `XMODADVI`, `XCHGPORT`, `XCHGOSD`, `MODIFYPWD`, `RESETPASSWORD`, `REBOOT`, `SETRESERVE`, `DHCP`. They change device settings and are out of scope here. (static)

### Seek reply

The vendor client does not show what the camera sends. This section is what the app reads from a reply.

A receiver handles a datagram in four steps.

1. Envelope: the magic must match, or the receiver drops the datagram. If the flag is not 0, the receiver sends a 10-byte acknowledgement (same id, flag 0, length 0) to the datagram's source address and port, then goes on. If the flag and the length are both 0, the datagram is an acknowledgement and is dropped. Otherwise it parses the bytes from offset 10. The app never compares the length field with the datagram size. (static)
2. Unit: the parser scans for `NEWM4V00` followed by a TAB and ignores any bytes before it. The unit ends at the first `\n\n\n`. The scan repeats on the rest of the datagram, so one datagram can hold several units. (static)
3. Fields: the parser splits the unit at each TAB and keeps empty fields. A field missing at the end reads as empty. (static)
4. Verb: field 0 must be `CMD` and field 1 must be `NVSS`. (static)

Reply fields, counted from the first field after the marker. A number after `string` is the longest value the app keeps. It cuts longer text. A `decimal` field reads 0 when it is empty or holds any character but a digit. Field 20 (activation) is an exception: it reads 2 when empty.

| field | type | meaning | notes |
|---|---|---|---|
| 0 | string | command class | `CMD` |
| 1 | string | command | `NVSS` |
| 2 | string, 17 | MAC | `XX:XX:XX:XX:XX:XX`; the app reverses the octet order |
| 3 | string, 15 | subnet mask | |
| 4 | string, 15 | gateway | |
| 5 | string, 15 | DNS server | |
| 6 | decimal | channel count | |
| 7 | decimal | server port | the app uses it as the device port |
| 8 | decimal | client port | |
| 9 | decimal | device type | the app accepts 4 (IPC) and 12 (NVR) |
| 10 | decimal | HTTP port | |
| 11 | decimal | product model number | |
| 12 | string, 63 | factory id | the app removes the text `ID` and uses the rest as product id |
| 13 | string, 63 | firmware version | |
| 14 | string, 63 | web version | |
| 15 | none | none | not read |
| 16 | string, 63 | not known | read, not used by the app |
| 17, 18 | decimal | not known | read, not used by the app |
| 19 | none | none | not read |
| 20 | decimal | activation | 2 when empty; the app treats 1 as activated |
| 21 | decimal | not known | read, not used by the app |
| 22 | string, 63 | model name | |
| 23 | string, 63 | not known | read, not used by the app |
| 24 | string, 63 | serial number | |
| 25 | string, 31 | not known | read, not used by the app |
| 26 | decimal | not known | read, not used by the app |
| 27, 28 | string, 63 | not known | read, not used by the app |
| 29 | decimal | not known | read, not used by the app |
| 30, 31 | string, 63 | not known | read, not used by the app |
| 32 | string, 15 | IP | when empty, the source address of the datagram |
| 33 | decimal | cloud type | |
| 34 | decimal | not known | read, not used by the app |
| 35 | string, 31 | cloud product key | |
| 36 | decimal | not known | read, not used by the app |
| 37 | string, 15 | reserve type | kept only when field 38 is not empty |
| 38 | string, 255 | reserve info | the app reads a non-empty value as support for UDP activation |
| 39 | list | not known | up to 256 comma-separated decimals, not used by the app |

(static)

- MAC: the app accepts only 17 characters with `:` at positions 2, 5, 8, 11 and 14. It writes the six octets in reverse order, keeps the letter case, and gives an empty MAC for any other shape. The app reverses a MAC the same way before it sends one in a request. So the wire form is the reverse of the MAC the app shows. (static for the reversal, inferred for the camera's wire form)
- MAC on the I91FX: the camera sends the octets in reverse order, in lower case. (verified: I91FX 2026-10-15)
- Its prefix is `D0:3B:F4`. It is none of the three Tiandy prefixes (`3C:DA:6D`, `BC:51:6C`, `E4:E6:6C`). (verified: I91FX 2026-10-15)
- Values from the I91FX, counted from `NEWM4V00` as in the table: the envelope is `be be e5 e5 00 00 00 00 ea 01`, so id 0, flag 0 and length 490. Field 2 is the MAC. Field 7 is `3000`, a stale value because that port is closed. Field 8 is `6000`. Field 9 is `4`, an IP camera. Field 10 is `80`. Field 13 is the firmware `NVSS_V29.0.23.20250330` and field 14 is the web version `7.1.25.407`. Field 20 (activation) is `0` before activation. Field 22 is the model `I91FX`. Field 24 is the serial number and field 32 the IP. Field 35 is an Aliyun product key, field 38 an RSA public key and field 39 is `1`. (verified: I91FX 2026-10-15)
- IP: field 32 wins when it is not empty. Otherwise the IP is the source address of the datagram, so a camera can leave it empty. (static)
- App filter: the add-device and LAN-search screens drop a reply when the factory id is empty after the `ID` removal, when the IP is blank, or when the device type is not 4 or 12. Some screens also drop a reply with a cloud product key set. The activation screen needs field 38 set and shows a camera as activated when field 20 is 1. (static)
- The example is one reply with placeholder values. It uses the RFC 7042 documentation MAC `00:00:5e:00:53:2a`, which is sent reversed and in lower case as `2a:53:00:5e:00:00`, as the I91FX does. The header id and flag are 0 and 0, as the I91FX sends them. It ends at field 32: the missing fields read as empty. The values of the unnamed fields and the bytes before `NEWM4V00` are guesses. [example: discovery_reply] (inferred)
- One search can draw several replies from one camera: up to four datagrams per search, and a new search every 20 seconds. The app removes duplicates by product id, IP or MAC depending on the screen. A client should deduplicate by MAC. (inferred)

### Search cadence

- The app does not wait for replies after a seek. It handles each reply as it comes. There is no timeout and no retry. (static)
- The app searches at once, then every 20 seconds. The socket stays open between searches. (static)
- The screens decide how long to listen. Add-device by LAN starts at once and stops after 30 seconds, so seeks go out at 0 and 20 seconds. The auto-search and LAN-search screens start after 1 second and stop after 11 seconds: one seek and a 10-second window. The activation search starts at once and stops after 10 seconds: one seek. (static)

## HTTP API

The camera has an XML control API under `/CGI/` and `/ISAPI/`. Bodies are UTF-8 XML with `Content-Type: application/xml; charset=utf-8`. The app sends each request body as compact XML with no declaration. It strips a leading byte order mark from a reply. It drops unknown elements, so a real reply can hold more elements than this section lists. (static)

The examples use CRLF line ends. They leave out the `Authorization` header, which changes with every request.

### Where the evidence comes from

- The I91FX web server answers on port 80 to the white-light, light-mode, motion-detection, capability, `PlayAudio`, `TwoWayAudio` and VMD trigger paths below, with a Digest login. The cloud relay is not needed. (verified: I91FX 2026-10-15)
- The app does not send the device-info, capability, white-light, light-mode and motion-detection requests below to the camera. It sends them through the vendor cloud, which is out of scope here. So the paths, methods and bodies below are known, and the HTTP framing is not. (static)
- For a camera added by IP or DDNS the app makes none of these calls, so it makes no HTTP call for them on a LAN camera. (static)
- The app sends requests to the camera itself only in the Wi-Fi access-point setup flow: login, a time read, overlays, a server-info write and one capabilities POST for a platform setting. That flow uses `http://<ip>` with no port, so port 80, and the same `/CGI/` and `/ISAPI/` paths. So the camera's own web server very likely serves the paths below. The discovery reply also carries an HTTP port field. (inferred)
- App timeouts: 6 s to connect, 60 s to read or write. Only a 2xx status is success. For any other status the app keeps just the code. (static)

### Authentication

The app has two logins for direct HTTP. It tries the session login first. It falls back to the Digest login when `GET /CGI/Security/SessionCheck` fails. Both appear only in the access-point flow. (static)

Session login:

- Step 1: `GET /CGI/Security/SessionCheck`, with no credentials. The reply root is `SessionCheck`, with `session` (string), `key` (string) and `iterations` (int). (static)
- Step 2: `POST /CGI/Security/Logon`. The body root is `User`, with `passwd`, `sessionTmp` and `username`. `sessionTmp` is the step 1 `session`. The reply root is `UserLogon`, with `statusString`, `statusValue`, `passwdLeftValue` and `session`. The app needs `statusString` `OK` and a non-empty `session`. It ignores the two integers. (static)
- `passwd` is built in steps. First h is the uppercase hex SHA-256 of the UTF-8 text `username` followed by `password`. Then, `iterations` times, h becomes the uppercase hex SHA-256 of the UTF-8 text h followed by `key`. The last h is `passwd`. (static)
- Step 3: each later request carries the header `HttpSession: <session>`. The app reads `GET /ISAPI/System/time` every 30 s to keep the session, and restarts at step 1 when that read fails. (static)

Digest login:

- `GET /ISAPI/Security/userCheck?username=<user>&passwd=<password>`. The password travels in the query, in clear. The first request has no `Authorization` header. On a 401 the app reads `WWW-Authenticate` and repeats the same request with a Digest header. Success is a `userCheck` reply with `statusString` `OK`. (static)
- Challenge: the app reads `realm`, `nonce` and `qop` from `WWW-Authenticate`. It ignores `opaque` and `algorithm`. Its response always uses `qop`, so the camera's challenge must carry one. (static for the parse, inferred for the need)
- Header: `Digest username="<user>",realm="<realm>",nonce="<nonce>",uri="<uri>",cnonce="<cnonce>",nc=00000001,response="<response>",qop="<qop>",algorithm="MD5"`. `nc` is always `00000001`. `cnonce` is the MD5 of the current time in milliseconds. (static)
- `response` is `MD5(HA1:nonce:00000001:cnonce:qop:HA2)`, with `HA1 = MD5(user:realm:password)` and `HA2 = MD5(method:uri)`. (static)
- The app differs from the usual form in three ways. `uri` is the absolute URL it requested, with scheme and host. `qop` and `algorithm` are quoted. Its MD5 hex text is shorter than 32 characters when the digest starts with two or more `0` digits. That breaks about one hash in 256. A client should use plain 32-character hex. (static)
- Digest alone is enough on a camera with no SessionCheck: the app logs in with Digest alone there. On a camera with SessionCheck the app never sends Digest, so Digest-only access is untested. (inferred)
- On the I91FX, Digest MD5 with realm `CGI` and qop `auth` works for every path tried. The user name `admin` in lower case passes Digest as well as `Admin`. `GET /CGI/Security/SessionCheck` answers with `session`, `key` and `iterations`, so the session login exists. (verified: I91FX 2026-10-15)
- Before activation, `GET /CGI/System/ActivationStatus` answers without a login: `<activated>inactive</activated><administrator>Admin</administrator>`. After activation it answers `active`. (verified: I91FX 2026-10-15)
- The device web page takes credentials in a link, `http://<ip>?uid=<user>&pwd=<password>`. (static)

### Device info

`GET /CGI/System/deviceInfo`, with no body, returns the version set of the camera. No HTTP call in the app returns model, serial or MAC. (static for what the app sends and parses, inferred for what the camera returns and for the absence of those three)

- The reply root is `DeviceInfo`. Its elements, all strings, are `firmwareVersion`, `hardwareVersion`, `sdkVersion`, `webVersion`, `uiVersion`, `mediaVersion`, `accessModule`, `ispVersion`, `algVersion`, `algModelVersion`, `aiModuleVersion`, `m3VersionList`, `McuVersion`, `lteModuleVersion`, `wifiModuleVersion`, `firewareSpecialVersion` (spelled so) and `softSpecialVersion`. A `platformVersionList` holds `platformInfo` items, each with `name` and `version`. (static)
- The app reads no model, serial or MAC element here, and it drops unknown elements. So the camera may send more than the app reads. Whether it sends those three here is open. The app takes them from the discovery reply (fields 22, 24 and 2; see "Seek reply"). It takes model, firmware and factory id from the private-protocol logon (see "Reading one parameter"). (static for the app's sources, inferred for the camera)
- The example is a reply with placeholder versions. Its status line and headers are guesses: the app tests only for a 2xx status and reads the body. [example: http_device_info_reply] (inferred)

### Capabilities

`POST /CGI/System/channels/<ch>/capabilities` queries what the camera supports. The body root is `CapDiscription` and the reply root is `ChanBasicCapList`. The body names the query. These are the queries the app sends for the features in scope. (static for what the app sends and parses, inferred for what the camera serves)

- Person, vehicle and all-motion. Body: `<CapDiscription><capType><mainType>015-AlarmParam</mainType><subType>00125-MDMotionDetectionSubList</subType></capType></CapDiscription>`. The reply has one `capTypeList` with `support` (boolean) and `subCap/supportType` entries. (static)
- Lamp types. Body: three text elements, `<capType>color2graylight</capType>`, `<capType>SupportLEDPowerLimit</capType>` and `<capType>colorToGrayThreshold</capType>`. The reply has one `capTypeList` per name, with `capType`, `support` and `subCap/lightType` entries. (static)
- Lamp limits. Body: two `capType` objects, each with `mainType` `001-ColorToGray` and `subType` `00105-colorToGrayWhitelightTime` or `00106-colorToGrayIRlightMax`. The reply has one `capTypeList` per subtype, with `capType` and `support`. (static)

What the replies tell:

- Person, vehicle and all-motion: `support` must be true. The `supportType` entries `people`, `car` and `all` then mark person, vehicle and all-motion (the app's "Picture changes") as present. An empty list, or `support` false, means none. (static)
- White light: a `lightType` entry `whiteLamp`, `midwhiteLamp` or `farwhiteLamp` marks a white lamp. `nearinfraredLamp`, `midinfraredLamp` and `farinfraredLamp` mark infrared lamps. The app reads `lightType` from every returned item. It shows the white-light control only when `color2graylight` has `support` true and a white lamp exists. (static)
- Light mode: no HTTP reply tells. The app reads the supported light modes through the vendor cloud, which is out of scope here. With none reported, or on error, the app opens the old fill-light screen. (static)
- `GET /CGI/Device/AllCapabilities/AllCapabilities`, with no body, returns an `AllCapabilities` document. Its `oAVideo` element holds `bWhiteLight`, `bWhiteLightSet`, `bRedLight` and `bRedLightSet`. The app parses them and never reads them, so their meaning comes from the names only. (static for the parse, inferred for the meaning)
- The example answers the person, vehicle and all-motion query on channel 1, with all three present. The real set depends on the camera, and the `capType` text is a guess. [example: http_capabilities_reply] (inferred)

### White light

`GET` and `PUT /ISAPI/Image/channels/<ch>/WhiteLight` read and write the white light. The root is `WhiteLight`. A GET has no body. (static for what the app sends and parses, inferred for what the camera serves)

GET reply elements:

| element | type | meaning |
|---|---|---|
| `contrltype` | text, with attribute `opt` | control type; the text is the current value, and `opt` lists the supported values separated by commas |
| `infraredLampPower` | int | brightness of the main white lamp |
| `infraredFarLampPower` | int | brightness of the far white lamp |
| `sunSetTime` | string | switch-on time, used in timed mode |
| `sunRiseTime` | string | switch-off time, used in timed mode |

(static for the names, inferred for the camera's layout)

- `contrltype` values: 0 auto, 1 manual on, 2 manual off, 3 timed. The app labels them so and shows the brightness sliders for 0 and 1, none for 2, and the timers for 3. (static)
- The two power fields run from 0 to 100. The app multiplies its 0-10 slider by 10 before it writes. On a lamp that cannot dim, it snaps the value to 0 or 100. The value -1 makes the app report that it could not read the brightness. (inferred for the range, static for the rest)
- `sunSetTime` is the switch-on time and `sunRiseTime` the switch-off time. The app shows a GET value only when it has three colon-separated parts, so the camera most likely sends `HH:MM:SS`. (static for the roles, inferred for the format)
- Which lamp the power fields drive depends on the lamp types in "Capabilities". The far lamp exists when `farwhiteLamp` is listed. (inferred)
- The example is a GET reply for channel 1: auto mode, both lamps at 100, timer values as placeholders. The camera's element order and header lines are guesses. [example: http_whitelight_get_reply] (inferred)

The PUT body has the root `WhiteLight`. Its elements are `contrltype` as plain text with no attribute, `infraredFarLampPower`, `infraredLampPower`, `sunRiseTime` and `sunSetTime`. The app sends back the whole document from its last GET with the changed fields. It leaves out a time element that the camera did not send. The reply is a `ResponseStatus` document, see "Errors". (static)

- The example turns the light on manually on channel 1: `contrltype` 1, the other fields echoed from the GET. Whether the camera accepts a body with `contrltype` alone is not visible in the vendor client. The I91FX refuses `contrltype` 1: see below. [example: http_whitelight_set_manual_on] (inferred)

On the I91FX (verified: I91FX 2026-10-15):

- `contrltype` lists `opt="0,2,3"`. A PUT with `contrltype` 1 (manual on) is refused with `statusCode` 3 and `statusString` `Device Error`.
- Timed mode lights the lamp for the whole day: `contrltype` 3 with `sunSetTime` `00:00:00` and `sunRiseTime` `23:59:00`. The lamp is lit from `sunSetTime` to `sunRiseTime`. The times have minute resolution: `23:59:59` reads back as `23:59:00`. So the lamp goes dark for the last minute of each day. (the last sentence is inferred)
- The lamp lights only in light mode 3 (colour) or 4 (custom). Mode 1 (infrared) keeps it off. Mode 2 (smart) lights it only on detection. A client sets the mode before it writes the timed window, and the library does so.
- Changing the light mode resets `contrltype`: modes 1 and 2 set it to 2, and modes 3 and 4 set it to 0.
- Lamp power 30 is visibly dimmer than 100.
- Writing that window while the light mode is 3 (colour) switches the light mode to 4 (custom).

### Light mode

`GET` and `PUT /CGI/System/CommonEnable/channels/<ch>/Type/4120` read and write the light mode. The root is `CommonEnable`, with `enable` (boolean), `type` (int) and `value` (int). `value` is the mode. The meaning column below paraphrases the app's own text for each mode. (static for what the app sends and parses, inferred for what the camera serves)

| value | app name | meaning |
|---|---|---|
| 1 | Infrared mode | white light off; infrared fill only; picture black and white at night |
| 2 | Early-warning mode | white light and colour picture on a smart event; infrared and black and white at night on dual-light cameras, colour on full-colour ones |
| 3 | Full colour mode | infrared off; white light fills; picture always in colour |
| 4 | Customize | the user picks the fill type and its control mode |

(static)

- The app lists only the modes the camera supports. See "Capabilities". (static)
- The app hides the "link white light" option in modes 1 and 3 and shows it in modes 2 and 4. In mode 2 it refuses to switch off person and vehicle detection. (static)
- The app sets `value` on the document from its last GET and sends it whole. So `enable` and `type` return as read. For other CommonEnable types (12290, 28689, 86091) it builds `enable` true, `type` equal to the number in the path, and `value`. A fresh 4120 body most likely follows that pattern. (static for the first part, inferred for the pattern)
- The custom settings of mode 4 also read and write `/CGI/Image/channels/<ch>/irLight`, root `IrLight`. That path is not documented here. (static)
- The `irLight` `<type>` is not a live day/night state. (verified: I91FX 2026-10-15)
- The I91FX has all four modes, with the values in the table, and the mode changes `contrltype`: see "White light". (verified: I91FX 2026-10-15)
- The example sets mode 2, early-warning (smart dual light), on channel 1. [example: http_light_mode_set_smart] (inferred)

### Motion detection

`GET` and `PUT /ISAPI/System/Video/inputs/channels/<ch>/motionDetection` read and write the detection switches. The root is `MotionDetection`. The person and vehicle switches use this path for IP cameras. The same document also sits at `.../motionDetection/Model/<n>`. The dynamic-inspection screens use it, with `1` for IP cameras and `0` for recorders. (static for what the app sends and parses, inferred for what the camera serves)

| element | type | meaning |
|---|---|---|
| `enabled` | boolean | person detection |
| `carEnabled` | boolean | vehicle detection |
| `allEnabled` | boolean | generic motion, any picture change; the app calls it "Picture changes" and uses it only when the camera lists `all` |
| `regionType` | string | region type of the detection area |
| `Grid` | `rowGranularity`, `columnGranularity` (int) | detection grid size |
| `MotionDetectionLayout` | `sensitivityLevel` (int), `layout/gridMap` (string) | sensitivity and grid map |

(static)

- The person switch writes `enabled`, and the vehicle switch writes `carEnabled`. The screen shows each switch only when the capability reply lists `people` or `car`. (static)
- The "Picture changes" switch shows only when the capability reply lists `all`. It sets `allEnabled`, `enabled` and `carEnabled` to one value. While `allEnabled` is true, the app shows person and vehicle as on and locks them. (static)
- The PUT body is the whole document from the last GET, with the changed flags. A fresh document with only the flags set is also what the settings screen builds when no GET came first. The reply is a `ResponseStatus` document: `statusString` `OK` is success, and `subStatusCode` `vcaPerformanceLimit` is a refusal. See "Errors". (static)
- On the I91FX, GET returns `enabled` true, `carEnabled` true, `allEnabled` false and `sensitivityLevel` 76. The web UI slider for the sensitivity runs from 0 to 100. `gridMap` is all zeros, yet smart events fire. (verified: I91FX 2026-10-15; static for the slider range: the camera web UI)
- A PUT of the whole document with a new `sensitivityLevel` reaches the camera. (verified: I91FX 2026-10-15)
- The example is a GET reply for channel 1: person and vehicle on, all-motion off. A real reply also carries `regionType`, `Grid` and `MotionDetectionLayout`. Their values are not visible in the vendor client, so the example leaves them out. A client should send them back unchanged. [example: http_motion_detection_get_reply] (inferred)

### Warning sound

The camera has built-in warning sounds. `PUT /CGI/Event/PlayAudio` plays one. (verified: I91FX 2026-10-15)

- Body: `<PlayAudioInfo><channelID>1</channelID><type>0</type><sampleNo>0</sampleNo><action>1</action></PlayAudioInfo>`. `sampleNo` 0 played the first sound, and it was heard. `action` 1 starts the sound. (verified: I91FX 2026-10-15)
- The `guardSound` capability counts the sounds. `POST /CGI/System/channels/<ch>/capabilities` with `<CapDiscription><capType>guardSound</capType></CapDiscription>` reports `supportSoundSampleNum` 3 and `supportSoundCustomNum` 2: three built-in sounds and two custom slots. (verified: I91FX 2026-10-15)
- The built-in sounds are spoken warning messages, not siren tones. (verified: I91FX 2026-10-15, heard on the camera)
- The stop action is not confirmed. The library sends `action` 0 to stop a sound. (inferred: `action` 1 starts one)
- The length of each sound is not known. Nor is the effect of a second PUT while a sound plays. See "Open questions".
- `outputVolume` sets their loudness: see "Backchannel", Volume. (verified: I91FX 2026-10-15)
- The VMD trigger `GET /ISAPI/Event/triggers/VMD/channels/1` holds `whiteLampForBody`. The camera web UI writes a sound link in a trigger as `<id>guardsound-N</id><notificationMethod>guardsound</notificationMethod><SoundID>N</SoundID>`. A client adds that entry to the trigger's notification list and keeps the other entries. (verified for `whiteLampForBody`: I91FX 2026-10-15; static for the link body: the camera web UI, `app.min.js`)
- A PUT of the whole trigger with that entry added reaches the camera. Whether motion then plays the sound is not recorded. (verified for the PUT: I91FX 2026-10-15)

### Event sources and side effects

- `ISAPI/Event/notification/alertStream` is not supported. (verified: I91FX 2026-10-15)
- `GET /CGI/Event/notification/alertState` lists the active `VMD` alerts. Polled once per second, it tracked the same events as the private protocol. It could serve as a fallback event source. (verified: I91FX 2026-10-15; the fallback use is inferred)
- ONVIF (port 80, WS-Security digest) offers these event topics: `VideoSource/MotionAlarm`, `RuleEngine/CellMotionDetector/Motion`, `RuleEngine/TamperDetector/Tamper`, `VideoSource/SignalLoss`, `VideoSource/ImageTooDark` and `VideoAnalytics/tnshik:MotionAlarm`. There is no person or vehicle topic. PullPoint works, with no reference parameters. The analytics module is `CellMotionEngine` only. (verified: I91FX 2026-10-15)
- ONVIF reports the manufacturer as `IPC Professional`. (verified: I91FX 2026-10-15)
- `PUT ISAPI/System/Network/AlarmServer` rebooted the camera, and the alarm server never pushed anything. A client must not write it. (verified: I91FX 2026-10-15; the advice is inferred)
- The camera clock is not set. After that reboot it read the year 2000, because NTP does not work. The HTTP `Date` header and the ONVIF UTC time were off by hours. A client does not take event times from the camera. (verified: I91FX 2026-10-15; the advice is inferred)

### Channel numbering

HTTP channels start at 1. The private protocol starts at 0. RTSP starts at 1. A single-channel camera is channel 0 on the private protocol and channel 1 on HTTP and RTSP. (static for what the SDK builds, inferred for what the camera expects)

| transport | first channel | single-channel camera | mapping |
|---|---|---|---|
| private protocol: commands, events, talk | 0 | 0 | the protocol's own number |
| HTTP `/channels/<ch>/` | 1 | 1 | private channel + 1 |
| RTSP `/<channel>/<stream>` | 1 | `/1/<stream>` | private channel + 1 |
| app | 1 | 1 | same as HTTP |

- The vendor client adds 1 to the private channel in the CGI paths it builds, for example `/CGI/Smart/PlateLib/Manage/Channels/<ch>/Query`. (static)
- The app's channel number is 1-based and goes into the HTTP path unchanged. One call rejects a channel of 0 or less. An IP camera opened with no channel gets channel 1. (static)
- The vendor client builds the RTSP path as `/<channel + 1>/<stream + 1>` from its channel and stream index. So channel 0 and stream 0 give `/1/1`. (static for the +1, inferred for the 0-based input)
- The private protocol is 0-based: see "Reading one parameter", "Event channel numbering" and "Talk channel numbering". (static)
- Each HTTP example on a channel path carries an integer `channel` field, set to 1. The same camera is channel 0 on the private protocol. [example: http_whitelight_get_reply] (inferred)

### Errors

The app expects a `ResponseStatus` document as the answer to a PUT or POST. For a GET it treats an empty or unreadable body as a failure. (static for what the app expects, inferred for what the camera sends)

| element | type | meaning |
|---|---|---|
| `requestURL` | string | not read by the app |
| `statusCode` | int | 1 is success; the white-light and light-mode calls fail on any other value |
| `statusString` | string | `OK` is success; the motion-detection and login calls test this text |
| `subStatusCode` | string | reason; `vcaPerformanceLimit` is the only value the app reads |

(static)

- `vcaPerformanceLimit` makes the motion-detection PUT fail with a performance-limit error. Its likely cause is that the camera's analytics are at their load limit. The name is the only evidence. (inferred)
- The app reads `statusCode` as an integer in some calls and as a string in others. (static)
- At HTTP level the app acts on one status only. A 401 with `WWW-Authenticate` starts the Digest retry. For any other non-2xx status it keeps the code and nothing else. (static)
- The login replies `UserLogon` and `userCheck` carry `statusString`, `statusValue` and `passwdLeftValue`. `OK` is success. The name `passwdLeftValue` suggests the password attempts left. The app does not read it. (static for the fields, inferred for the meaning)
- On the I91FX, a PUT of `contrltype` 1 returns `statusCode` 3 and `statusString` `Device Error`. (verified: I91FX 2026-10-15)
- Other failure codes and reason strings are not visible in the vendor client. See "Open questions".

## Open questions

- framing: Does the camera check the sequence number or the payload length at offset 18 of a command header? (blocks: frame encoder)
- framing: Which charset does the I91FW report, and does it accept UTF-8 in text fields? (blocks: device and channel names)
- framing: Does `GETPARAM` type 20 return `INNER PARAGET PTZ_PROTOCOL`, and how is its channel range written before the COM port, address and device-type fields? (blocks: device info)
- transport: Which transport (TCP, UDP or multicast) does the app use for video and talk data channels? (blocks: talk channel)
- login: Which fields carry device id, model, serial, firmware and channel count, and in what order? They are not in the login reply but in the function report and the parameters sent at logon. (blocks: device registry)
- login: What does the camera send for an account lock (`LOGONLOCK`) and for too many users? (blocks: auth error mapping)
- heartbeat: Does the camera answer each heartbeat, and with which bytes? The vendor client shows only that an empty camera packet is valid. (blocks: heartbeat reply fixture)
- heartbeat: After how much silence does the camera close a command connection? (blocks: keepalive margin in `nvs/connection.py`)
- heartbeat: Does the camera expect a `MODULE HEARTBEAT RESPONSE` from the client, and what do its integer and string mean? (blocks: camera message decoder)
- events: Which `VCA` A4 values mean intrusion, line crossing, area and the other analytics? (blocks: VCA kind mapping)
- events: What is the target-type code for human vs vehicle inside the `VCA` and `ONVIF VCAALARM` target arrays? (blocks: per-target person/vehicle kinds)
- events: What does the camera send for a real vehicle: `MOTIONDETECT_CAR`? (blocks: Vehicle binary sensor)
- talk: The channel-talk reply uses route `IP` and the command prefix `INNER NVR` (from the vendor client). What are the unread tokens 3-5 between the channel and `BEGIN`, and what exactly makes the camera send `BEGIN ERROR`? (blocks: talk reply fixture)
- talk: What `id:rate` pairs does `TALKCODER_LIST` return for the I91FW, and which codec does the camera accept? (blocks: talk codec choice)
- talk: Does `CMD TALK BEGIN` need the optional audio encode-type and sample-rate fields, and what values does the camera expect? (blocks: talk start fields)
- discovery: What does a real reply carry before `NEWM4V00`? (blocks: discovery reply fixtures)
- discovery: Which values does the I91FX send for field 11 (product model number), for field 20 (activation) after activation, and for the unnamed fields 16-19, 21, 23, 25-31, 34, 36 and 37? (blocks: device filter, activation check)
- http: Does the camera accept the standard Digest form that aiohttp sends (`uri` is the request path, `qop` and `algorithm` unquoted), or only the app's form (absolute `uri`, quoted `qop` and `algorithm`)? (blocks: `DigestAuthMiddleware` setup)
- http: Which request returns the model, serial and MAC? The app reads only versions from `/CGI/System/deviceInfo`. (blocks: `info` in `http.py`)
- http: Does the camera accept a PUT with only the changed fields (`contrltype` alone, one detection flag, a bare `CommonEnable`), or only the whole document the app echoes? (blocks: `set_light`, `set_light_mode`, `set_detection`)
- http: How does the I91FW report light-mode support over HTTP? The app reads a cloud bitmask, not an HTTP reply. Does a failed `GET .../Type/4120` mean no light mode? (blocks: `caps` light_mode)
- http: Which `lightType` and `supportType` values does the I91FX return? (blocks: `caps` white_light, person, vehicle)
- http: Which `statusCode` and `subStatusCode` values mark a failure besides `vcaPerformanceLimit`, and which HTTP status carries them? (blocks: error mapping in `http.py`)
- http: What do the camera's reply status line and headers look like, and does a reply start with a byte order mark or an XML declaration? (blocks: HTTP fixtures in `simulator.py`)
- http: What does `/CGI/Common/session`, a path the vendor SDK uses, do? (blocks: auth in `http.py`)
- http: On a camera whose capability reply lacks `people`, does `enabled` mean plain motion detection? (blocks: `set_detection` on other models)
- http: Which `PlayAudio` action stops a sound? (blocks: siren turn_off)
- http: How long is each built-in warning sound, and what does a second `PlayAudio` PUT do while one plays? (blocks: siren replay interval)
- http: Does the camera accept a `guardsound` link on the VMD trigger, and does motion then play the sound? (blocks: `set_siren_on_event`)
