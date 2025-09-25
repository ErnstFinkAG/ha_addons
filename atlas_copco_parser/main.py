import json
import os
import time
import socket
import logging
import binascii
from pathlib import Path
import paho.mqtt.client as mqtt

# === Load Configuration ===
with open("/data/options.json", "r") as f:
    config = json.load(f)

ips = [ip.strip() for ip in config["ip"].split(",")]
names = [name.strip() for name in config["name"].split(",")]
types = [t.strip().lower() for t in config["type"].split(",")]
interval = int(config["interval"])
timeout = int(config["timeout"])
verbose = config["verbose"]

mqtt_host = config["mqtt_host"]
mqtt_port = config["mqtt_port"]
mqtt_user = config["mqtt_user"]
mqtt_password = config["mqtt_password"]
discovery_prefix = config["discovery_prefix"]
scaling_overrides = json.loads(config["scaling_overrides"])

# === Logging ===
logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                    format='[%(asctime)s] %(levelname)s: %(message)s')

# === Predefined Hex Question Sets ===
QUESTIONS = {
    "gs15vs23a": """
30020130022430022630022730022a30026630032130032230032e30032f30033030070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071730071830071b30072530072630072730074330074c30074d30075430075530075630075730210130210530210a30220130220a30051f30052030052130052730052830052930052a300e03300e04300e05300e2a300ef3310e23310e27310e2b310e3b31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300909300914300108
""",
    "gs15vp13": """
30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300108
"""
}

# === MQTT Setup ===
mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(mqtt_user, mqtt_password)
mqtt_client.connect(mqtt_host, mqtt_port, 60)

# === Helpers for BER-TLV Decoding (ASN.1-like) ===
def parse_ber_tlv(data):
    i = 0
    decoded = {}
    while i < len(data):
        if i + 2 > len(data):
            break
        tag = data[i:i+2].hex()
        i += 2
        if i >= len(data):
            break
        length = data[i]
        i += 1
        if i + length > len(data):
            break
        value = data[i:i+length]
        i += length
        decoded[tag] = value
    return decoded

def decode_value(value_bytes):
    try:
        return int.from_bytes(value_bytes, byteorder="big", signed=True)
    except Exception:
        return None

def publish_sensor(device_name, sensor_id, value):
    unique_id = f"{device_name}_{sensor_id}"
    object_id = f"{device_name}/{sensor_id}"
    topic = f"{discovery_prefix}/sensor/{unique_id}/config"
    state_topic = f"atlas_copco/{device_name}/{sensor_id}/state"

    payload = {
        "name": sensor_id,
        "state_topic": state_topic,
        "unique_id": unique_id,
        "device": {
            "identifiers": [device_name],
            "name": device_name,
            "manufacturer": "Atlas Copco",
            "model": "MK5s Touch"
        }
    }

    mqtt_client.publish(topic, json.dumps(payload), retain=True)
    mqtt_client.publish(state_topic, value)

def send_hex_query(ip, port, hex_string, timeout):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect((ip, port))
        s.sendall(binascii.unhexlify(hex_string))
        response = s.recv(8192)
        return response

def process_controller(ip, name, controller_type):
    hex_query = QUESTIONS.get(controller_type)
    if not hex_query:
        logging.error(f"Unknown controller type: {controller_type}")
        return

    try:
        logging.info(f"Polling {name} at {ip} ({controller_type})")
        response = send_hex_query(ip, 502, hex_query.replace("\n", "").strip(), timeout)
        logging.debug(f"Raw response from {ip}: {binascii.hexlify(response)}")

        data = parse_ber_tlv(response)
        for sensor_id, raw in data.items():
            value = decode_value(raw)
            if sensor_id in scaling_overrides:
                try:
                    value *= float(scaling_overrides[sensor_id])
                except Exception:
                    logging.warning(f"Invalid scaling for {sensor_id}")
            if value is not None:
                publish_sensor(name, sensor_id, value)
                logging.info(f"Published {sensor_id} = {value}")
            else:
                logging.warning(f"Failed to decode value for {sensor_id}")
    except Exception as e:
        logging.error(f"Error polling {ip}: {e}")

# === Main Loop ===
while True:
    for ip, name, t in zip(ips, names, types):
        process_controller(ip, name, t)
    logging.info(f"Sleeping for {interval} seconds...")
    time.sleep(interval)
