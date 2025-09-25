#!/usr/bin/env python3
# Atlas Copco Parser — Home Assistant add-on
# VERSION: 0.0.1
#
# This version mirrors the PowerShell script:
#   - multiple Question Strings, one per Device Type.
#

import os, json, threading, time, signal, re, hashlib
from typing import Dict, Any, List, Optional, Tuple
import requests
import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"
SELF_PATH = __file__
VERSION = "0.0.1"


#---Question Strings for Controller Types GA15VS23A and GA15VP13---

QUESTION_GA15VS23A = (
"30020130022430022630022730022a30026630032130032230032e30032f30033030070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071730071830071b30072530072630072730074330074c30074d30075430075530075630075730210130210530210a30220130220a30051f30052030052130052730052830052930052a300e03300e04300e05300e2a300ef3310e23310e27310e2b310e3b31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300909300914300108"
)

QUESTION_GA15VP13 = (
"30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300108"
)


# ------ GA15VS23A ------
SENSORS_GA15VS23A: Dict[str, Dict[str, Any]] = {
    "machine_status":         {"pair":"3001.08","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"measurement","name":"Machine Status"},
    "controller_temperature": {"pair":"3002.01","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Controller Temperature"},
    "compressor_outlet":      {"pair":"3002.24","part":"hi","decode":"_div1000","unit":"bar","device_class":"pressure","state_class":"measurement","name":"Compressor Outlet"},
    "ambient_air":            {"pair":"3002.26","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Ambient Air"},
    "relative_humidity":      {"pair":"3002.27","part":"hi","decode":"_id","unit":"%","device_class":"humidity","state_class":"measurement","name":"Relative Humidity"},
    "element_outlet":         {"pair":"3002.2A","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Element Outlet"},
    "aftercooler_pcb_temp":   {"pair":"3002.66","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Aftercooler Drain PCB Temperature"},
    "running_hours":          {"pair":"3007.01","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Running Hours"},
    "motor_starts":           {"pair":"3007.03","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Motor Starts"},
    "load_relay":             {"pair":"3007.04","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Load Relay"},
    "vsd_1_20":               {"pair":"3007.05","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 1–20%"},
    "vsd_20_40":              {"pair":"3007.06","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 20–40%"},
    "vsd_40_60":              {"pair":"3007.07","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 40–60%"},
    "vsd_60_80":              {"pair":"3007.08","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 60–80%"},
    "vsd_80_100":             {"pair":"3007.09","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 80–100%"},
    "fan_starts":             {"pair":"3007.0B","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Fan Starts"},
    "accumulated_volume":     {"pair":"3007.0C","part":"u32","decode":"_times1000","unit":"m³","device_class":None,"state_class":"total_increasing","name":"Accumulated Volume"},
    "module_hours":           {"pair":"3007.0D","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Module Hours"},
    "emergency_stops":        {"pair":"3007.0E","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Emergency Stops"},
    "direct_stops":           {"pair":"3007.0F","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Direct Stops"},
    "recirculation_starts":   {"pair":"3007.17","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Starts"},
    "recirculation_failures": {"pair":"3007.18","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Failures"},
    "low_load_hours":         {"pair":"3007.1B","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Low Load Hours"},
    "available_hours":        {"pair":"3007.25","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Available Hours"},
    "unavailable_hours":      {"pair":"3007.26","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Unavailable Hours"},
    "emergency_stop_hours":   {"pair":"3007.27","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Emergency Stop Hours"},
    "display_hours":          {"pair":"3007.43","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Display Hours"},
    "boostflow_hours":        {"pair":"3007.4C","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Boostflow Hours"},
    "boostflow_activations":  {"pair":"3007.4D","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Boostflow Activations"},
    "emergency_stops_running":{"pair":"3007.54","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Emergency Stops During Running"},
    "drain1_op_time":         {"pair":"3007.55","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Drain 1 Operation Time"},
    "drain1_switching":       {"pair":"3007.56","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Drain 1 Switching Actions"},
    "drain1_manual":          {"pair":"3007.57","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Drain 1 Manual Drainings"},
    "motor_rpm_requested":    {"pair":"3021.01","part":"lo","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Motor Requested RPM"},
    "motor_rpm_actual":       {"pair":"3021.01","part":"hi","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Motor Actual RPM"},
    "flow":                   {"pair":"3021.05","part":"u32","decode":"_id","unit":"%","device_class":None,"state_class":"measurement","name":"Flow"},
    "motor_amperage":         {"pair":"3021.0A","part":"hi","decode":"_id","unit":"A","device_class":"current","state_class":"measurement","name":"Motor Amperage"},
    "fan_rpm_requested":      {"pair":"3022.01","part":"lo","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Fan Motor Requested RPM"},
    "fan_rpm_actual":         {"pair":"3022.01","part":"hi","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Fan Motor Actual RPM"},
    "fan_motor_amperage":     {"pair":"3022.0A","part":"hi","decode":"_id","unit":"A","device_class":"current","state_class":"measurement","name":"Fan Motor Amperage"},
    "service_a_1":            {"pair":"3113.50","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 1"},
    "service_a_2":            {"pair":"3113.51","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 2"},
    "service_b_1":            {"pair":"3113.52","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 1"},
    "service_b_2":            {"pair":"3113.53","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 2"},
    "service_d_1":            {"pair":"3113.54","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service D 1"},
    "service_d_2":            {"pair":"3113.55","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service D 2"},
}


# ------ GA15VP13 ------
SENSORS_GA15VP13: Dict[str, Dict[str, Any]] = {
    "machine_status":         {"pair":"3001.08","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"measurement","name":"Machine Status"},
    "compressor_outlet":      {"pair":"3002.01","part":"hi","decode":"_div1000","unit":"bar","device_class":"pressure","state_class":"measurement","name":"Compressor Outlet"},
    "element_outlet":         {"pair":"3002.03","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Element Outlet"},
    "ambient_air":            {"pair":"3002.05","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Ambient Air"},
    "controller_temperature": {"pair":"3002.08","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Controller Temperature"},
    "running_hours":          {"pair":"3007.01","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Running Hours"},
    "motor_starts":           {"pair":"3007.03","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Motor Starts"},
    "load_cycles":            {"pair":"3007.04","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Load Cycles"},
    "vsd_1_20":               {"pair":"3007.05","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 1–20%"},
    "vsd_20_40":              {"pair":"3007.06","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 20–40%"},
    "vsd_40_60":              {"pair":"3007.07","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 40–60%"},
    "vsd_60_80":              {"pair":"3007.08","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 60–80%"},
    "vsd_80_100":             {"pair":"3007.09","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 80–100%"},
    "fan_starts":             {"pair":"3007.0B","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Fan Starts"},
    "accumulated_volume":     {"pair":"3007.0C","part":"u32","decode":"_times1000","unit":"m³","device_class":None,"state_class":"total_increasing","name":"Accumulated Volume"},
    "module_hours":           {"pair":"3007.0D","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Module Hours"},
    "emergency_stops":        {"pair":"3007.0E","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Emergency Stops"},
    "direct_stops":           {"pair":"3007.0F","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Direct Stops"},
    "recirculation_starts":   {"pair":"3007.14","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Starts"},
    "recirculation_failures": {"pair":"3007.15","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Failures"},
    "low_load_hours":         {"pair":"3007.18","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Low Load Hours"},
    "available_hours":        {"pair":"3007.22","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Available Hours"},
    "unavailable_hours":      {"pair":"3007.23","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Unavailable Hours"},
    "emergency_stop_hours":   {"pair":"3007.24","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Emergency Stop Hours"},
    "rpm_requested":          {"pair":"3021.01","part":"lo","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"RPM Requested"},
    "rpm_actual":             {"pair":"3021.01","part":"hi","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"RPM Actual"},
    "motor_amperage":         {"pair":"3021.05","part":"hi","decode":"_id","unit":"A","device_class":"current","state_class":"measurement","name":"Motor Amperage"},
    "flow":                   {"pair":"3021.0A","part":"u32","decode":"_id","unit":"%","device_class":None,"state_class":"measurement","name":"Flow"},
    "service_a_1":            {"pair":"3113.50","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 1"},
    "service_a_2":            {"pair":"3113.51","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 2"},
    "service_b_1":            {"pair":"3113.52","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 1"},
    "service_b_2":            {"pair":"3113.53","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 2"},
}

# ------------------------------ Decoders -------------------------------------
def _id(v: int) -> int:
    return v
def _div10(v: int) -> float:
    return round(v / 10.0, 1)
def _div1000(v: int) -> float:
    return round(v / 1000.0, 3)
def _hours_from_seconds_u32(v: int) -> float:
    return round(v / 3600.0, 1)
def _percent_from_bucket(v: int) -> float:
    return round((v / 65831881.0) * 100.0, 2)
def _service_remaining_3000(v: int) -> float:
    return max(0.0, round(3000.0 - (v / 3600.0), 1))
def _service_remaining_6000(v: int) -> float:
    return max(0.0, round(6000.0 - (v / 3600.0), 1))
def _times1000(v: int) -> int:
    return v * 1000

DECODERS = {
    "_id": _id,
    "_div10": _div10,
    "_div1000": _div1000,
    "_hours_from_seconds_u32": _hours_from_seconds_u32,
    "_percent_from_bucket": _percent_from_bucket,
    "_times1000": _times1000,
}


#---Post Question to Controller---
def single_pair_read(session: requests.Session, ip: str, pair: str, timeout: int, verbose: bool) -> Optional[str]:
    q = pair.replace(".","")
    try:
        r = session.post(f"http://{ip}/cgi-bin/mkv.cgi", data={"QUESTION": q}, timeout=timeout)
        raw = r.text if r.status_code == 200 else ""
    except Exception as e:
        raw = f"EXC:{e}"
    clean = clean_answer(raw)
    toks = tokenize_answer(clean, 1)
    tok = toks[0] if toks else None
    if verbose:
        print(f"[{device_type}:{ip}] FALLBACK_Q={q}", flush=True)
        print(f"[{device_type}:{ip}] FALLBACK_A_RAW={repr(raw)}", flush=True)
        print(f"[{device_type}:{ip}] FALLBACK_A_CLEAN={repr(clean)} TOKENS={len(toks)}", flush=True)
        print(f"[{device_type}:{ip}]   token[fallback] {pair} = {tok if tok else 'None'}", flush=True)
    return tok

    mqtt_settings = {
	    "host": opts.get("mqtt_host", "localhost"),
        "port": opts.get("mqtt_port", 1883),
        "user": opts.get("mqtt_user", ""),
        "password": opts.get("mqtt_password", ""),
        "discovery_prefix": opts.get("discovery_prefix", "homeassistant"),
    }