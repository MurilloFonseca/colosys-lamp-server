#!/usr/bin/env python3
"""Smart lamp simulator for the FIWARE "Descomplicado" stack (Ultralight over MQTT).

Same topics and payload format as the course's esp32_mockup_SmartLamp.py, plus:
  * temperature and humidity (the course mockup only sends luminosity),
  * a reply on /cmdexe after each command (without it Orion keeps the command PENDING),
  * the broker address as an argument (the course mockup has the teacher's IP hard-coded).

    pip install paho-mqtt
    python lamp_simulator.py --device lamp-ab12cd            # broker on localhost:1883
    python lamp_simulator.py --device lamp001 --broker 192.168.0.10 --apikey TEF
"""
import argparse
import random
import time
import warnings

import paho.mqtt.client as mqtt

warnings.filterwarnings("ignore", category=DeprecationWarning)   # paho 2.x: callback API v1 notice


def make_client(client_id: str) -> mqtt.Client:
    try:
        # paho-mqtt 2.x requires the callback API version (the old signatures keep working)
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id)
    except AttributeError:
        return mqtt.Client(client_id=client_id)          # paho-mqtt 1.x


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-d", "--device", required=True, help="device id returned when the lamp was registered")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--apikey", default="TEF")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between measurements")
    args = ap.parse_args()

    base = f"/{args.apikey}/{args.device}"
    topic_attrs, topic_cmd, topic_cmdexe = f"{base}/attrs", f"{base}/cmd", f"{base}/cmdexe"

    lamp_on = False
    luminosity, temperature, humidity = 50.0, 24.0, 55.0

    def payload() -> str:
        # Ultralight: key|value|key|value  (object ids from the device provisioning: l, t, h, s)
        return f"l|{luminosity:.0f}|t|{temperature:.1f}|h|{humidity:.0f}|s|{'on' if lamp_on else 'off'}"

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to {args.broker}:{args.port}, listening on {topic_cmd}")
            client.subscribe(topic_cmd)
            client.publish(topic_attrs, payload())
        else:
            print(f"Connection refused (rc={rc})")

    def on_message(client, userdata, msg):
        nonlocal lamp_on
        text = msg.payload.decode(errors="replace")
        print(f"<- {text}")
        # Ultralight command: <deviceId>@<command>|<params>
        target, _, rest = text.partition("@")
        command = rest.split("|", 1)[0]
        if target != args.device or command not in ("on", "off"):
            print("   (ignored)")
            return
        lamp_on = command == "on"
        client.publish(topic_cmdexe, f"{args.device}@{command}|OK")    # command result
        client.publish(topic_attrs, payload())                         # new state right away
        print(f"   lamp is now {'ON' if lamp_on else 'OFF'}")

    client = make_client(f"sim-{args.device}")
    client.on_connect, client.on_message = on_connect, on_message
    client.connect(args.broker, args.port, keepalive=60)
    client.loop_start()

    try:
        while True:
            time.sleep(args.interval)
            # gentle random walk; the lamp being on makes the room brighter
            luminosity = clamp(luminosity + random.uniform(-4, 4) + (3 if lamp_on else -1), 0, 100)
            temperature = clamp(temperature + random.uniform(-0.3, 0.3), 15, 35)
            humidity = clamp(humidity + random.uniform(-1, 1), 20, 95)
            client.publish(topic_attrs, payload())
            print(f"-> {payload()}")
    except KeyboardInterrupt:
        print("\nStopping simulator")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
