import socket
import json
import time
import paho.mqtt.client as mqtt

CONFIG_PATH = "/data/options.json"

def get_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def send_tcp_command(ip, port, cmd):
    print(f"[DEBUG] Sending TCP command '{cmd}' to {ip}:{port}")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((ip, port))
        s.sendall((cmd + "\r").encode())
        try:
            response = s.recv(128).decode(errors="ignore").strip()
            print(f"[DEBUG] TCP response: {response}")
        except Exception as e:
            print(f"[DEBUG] No response or error reading response: {e}")
            response = ""
        s.close()
        print(f"[DEBUG] Successfully sent '{cmd}' to {ip}:{port}")
        return response
    except Exception as e:
        print(f"[ERROR] TCP command failed: {e}")
        return f"Error: {e}"

def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[DEBUG] Connected to MQTT broker with result code {rc}")
    config = userdata['config']
    devices = config.get('devices', [])
    for device in devices:
        topic = f"{device['name']}/command"
        print(f"[DEBUG] Subscribing to topic: {topic}")
        client.subscribe(topic)

def on_message(client, userdata, msg):
    print(f"[DEBUG] Received MQTT message on {msg.topic}: {msg.payload.decode()}")
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
                pub_topic = f"{topic_base}/status"
                print(f"[DEBUG] Publishing response to {pub_topic}: {response}")
                client.publish(pub_topic, response)
            else:
                print(f"[DEBUG] Unknown command '{payload}' for device {topic_base}")
                client.publish(f"{topic_base}/status", f"Unknown command: {payload}")

def main():
    config = get_config()
    # For debug: Print config (redact password for logs)
    safe_config = config.copy()
    safe_config["mqtt_pass"] = "***"
    print(f"[DEBUG] Loaded config: {safe_config}")
    # Parse devices from devices_json string if needed (for string-style config)
    if "devices_json" in config:
        try:
            config['devices'] = json.loads(config['devices_json'])
        except Exception as e:
            print(f"[ERROR] Unable to parse devices_json: {e}")
            config['devices'] = []
    mqtt_host = config.get("mqtt_host")
    mqtt_port = config.get("mqtt_port")
    mqtt_user = config.get("mqtt_user")
    mqtt_pass = config.get("mqtt_pass")
    devices = config.get("devices", [])
    print(f"[DEBUG] Connecting to MQTT broker at {mqtt_host}:{mqtt_port} as {mqtt_user}")
    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.user_data_set({"config": config})
    client.on_connect = on_connect
    client.on_message = on_message
    if mqtt_user:
        client.username_pw_set(mqtt_user, mqtt_pass)
    try:
        client.connect(mqtt_host, mqtt_port, 60)
    except Exception as e:
        print(f"[ERROR] Failed to connect to MQTT broker: {e}")
        return
    client.loop_forever()

if __name__ == "__main__":
    main()
