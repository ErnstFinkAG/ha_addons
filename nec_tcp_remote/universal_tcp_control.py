import socket
import sys
import json

CONFIG_PATH = "/data/options.json"

def get_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception as e:
        print(f"Config load error: {e}")
        return {}

def send_command(cmd, ip, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((ip, port))
        s.sendall((cmd + "\r").encode())
        response = s.recv(128).decode(errors="ignore").strip()
        s.close()
        return response
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: universal_tcp_control.py <device_name> <on|off|status|custom> [custom_command]")
        sys.exit(1)

    device_name = sys.argv[1]
    action = sys.argv[2].lower()
    config = get_config()
    devices = config.get("devices", [])
    device = next((d for d in devices if d["name"].lower() == device_name.lower()), None)

    if not device:
        print(f"Device '{device_name}' not found. Available: {[d['name'] for d in devices]}")
        sys.exit(2)

    commands = device.get("commands", {})
    cmd = commands.get(action)
    if not cmd and action == "custom" and len(sys.argv) > 3:
        cmd = sys.argv[3]
    if not cmd:
        print("Unknown action. Available: %s" % ", ".join(commands.keys()))
        sys.exit(2)

    ip = device.get("ip_address", "127.0.0.1")
    port = int(device.get("port", 1234))
    print(send_command(cmd, ip, port))
