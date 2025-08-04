import socket
import json
import time
import threading
import paho.mqtt.client as mqtt

CONFIG_PATH = "/data/options.json"

def get_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def send_tcp_command(ip, port, cmd):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((ip, port))
        s.sendall((cmd + "\r").encode())
        try:
            response = s.recv(128).decode(errors="ignore").strip()
        except Exception:
            response = ""
        s.close()
        return response
    except Exception as e:
        return f"Error: {e}"

def on_message(client, userdata, msg):
    config = userdata['config']
    devices = config.get('devices', [])
    topic = msg.topic
    payload = msg.payload.decode().strip().lower()
    for device in devices:
        topic_base = device['name']
        if topic == f"{topic_base}/command":
            cmd = device['commands'].get(payload)
            if not cmd and payload.startswith("raw:"):
                cmd = payload[4:]
            if cmd:
                response = send_tcp_command(device['ip_address'], device['port'], cmd)
                client.publish(f"{topic_base}/status", response)
            else:
                client.publish(f"{topic_base}/status", f"Unknown command: {payload}")

def main():
    config = get_config()
    mqtt_host = config.get("mqtt_host")
    mqtt_port = config.get("mqtt_port")
    mqtt_user = config.get("mqtt_user")
    mqtt_pass = config.get("mqtt_pass")
    devices = config.get("devices", [])
    client = mqtt.Client(protocol=mqtt.MQTTv5, callback_api_version=5)
    client.user_data_set({"config": config})
    if mqtt_user:
        client.username_pw_set(mqtt_user, mqtt_pass)
    client.on_message = on_message
    client.connect(mqtt_host, mqtt_port, 60)
    for device in devices:
        client.subscribe(f"{device['name']}/command")
    client.loop_forever()

if __name__ == "__main__":
    main()
