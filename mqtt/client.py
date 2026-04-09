"""
MQTT Client Configuratie
========================
Dit bestand beheert de permanente verbinding tussen de FastAPI backend (Cloud)
en de Mosquitto MQTT Broker. 

Deze client draait op de achtergrond in een eigen thread en luistert (subscribes)
naar binnenkomende signalen van alle kluiswanden (zoals leveringen, afhalingen, en hartslagen).
"""

import os
import json
import ssl
import paho.mqtt.client as mqtt
from typing import Any

# Importeer alle specifieke acties vanuit handlers.py
from mqtt.handlers import (
    handle_delivery, 
    handle_pickup, 
    handle_alarm, 
    handle_telemetry,
    handle_request_sync,
    push_user_to_edge,
    handle_return,
    handle_collect
)

# ==========================================
# CONFIGURATIE (Via environment variabelen met veilige fallbacks)
# ==========================================
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT"))

MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")

# Initialiseer de MQTT client
client = mqtt.Client(client_id="fastapi_cloud_backend")


# ==========================================
# CALLBACK FUNCTIES
# ==========================================

def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
    """
    Wordt afgevuurd zodra de connectie met de broker slaagt of faalt.
    Bij succes (rc == 0) abonneren we direct op alle relevante topics.
    """
    if rc == 0:
        print("[MQTT] Cloud Backend succesvol verbonden met broker!")
        # Luister naar ALLES van ALLE locaties
        # + is een wildcard voor exact 1 niveau (location_id)
        # # is een wildcard voor alles wat erna komt
        client.subscribe("lockers/+/events/#")
        client.subscribe("lockers/+/telemetry")
    else:
        print(f"[MQTT ERROR] Verbinding mislukt met code {rc}")


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    # 1. LOG ALLES WAT BINNENKOMT (Zelfs als het onzin is)
    print(f"\n[MQTT DEBUG] ---> Bericht ontvangen op topic: {msg.topic}")
    print(f"[MQTT DEBUG] ---> Ruwe payload: {msg.payload.decode()}")
    
    topic_parts = msg.topic.split("/")
    
    if len(topic_parts) >= 3:
        location_id = topic_parts[1]
        category = topic_parts[2]  
        
        try:
            payload = json.loads(msg.payload.decode())
            print(f"[MQTT DEBUG] JSON succesvol geparsed. Categorie: {category}")
            
            if category == "events" and len(topic_parts) >= 4:
                event_type = topic_parts[3]
                print(f"[MQTT DEBUG] Event type gedetecteerd: {event_type}")
                
                if event_type == "delivery":
                    handle_delivery(client, location_id, payload)
                elif event_type == "pickup":
                    handle_pickup(client, location_id, payload)
                elif event_type == "return":  # <--- NIEUW: De retour-router
                    print("[MQTT DEBUG] Ik ga nu handle_return aanroepen!")
                    handle_return(client, location_id, payload)
                elif event_type == "collect": # <--- NIEUW
                    print("[MQTT DEBUG] Ik ga nu handle_collect aanroepen!")
                    handle_collect(client, location_id, payload)
                elif event_type == "alarm":
                    print("[MQTT DEBUG] Ik ga nu handle_alarm aanroepen!")
                    handle_alarm(client, location_id, payload)
                elif event_type == "request_sync":
                    handle_request_sync(client, location_id, payload)
                else:
                    print(f"[MQTT WARNING] Onbekend event type: {event_type}")
            
            elif category == "telemetry":
                handle_telemetry(client, location_id, payload)
                
        except json.JSONDecodeError:
            print(f"[MQTT ERROR] Dit is geen geldige JSON!")
        except Exception as e:
            print(f"[MQTT ERROR] Fout bij verwerken (crash in de handler?): {e}")
    else:
        print(f"[MQTT DEBUG] Topic structuur te kort, wordt genegeerd.")

# ==========================================
# CLIENT INSTELLEN & STARTEN
# ==========================================

# Koppel de callback functies aan de client
client.on_connect = on_connect
client.on_message = on_message

# We verbinden intern via MQTTS over poort 8883. 
# Omdat we communiceren via de Docker-netwerknaam ('mqtt-broker') en niet via 
# een formeel domein zoals 'mqtt.jouwwebsite.be', negeren we de hostname check (ssl.CERT_NONE).
client.tls_set(cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)
client.username_pw_set(MQTT_USER, MQTT_PASS)

def start_mqtt() -> None:
    """
    Start de MQTT client en laat deze op de achtergrond (loop_start) meedraaien 
    naast de reguliere FastAPI processen.
    """
    try:
        # Connectie maken met een timeout (keepalive) van 60 seconden
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()  # Start de niet-blokkerende achtergrond-thread
    except Exception as e:
        print(f"[MQTT FATAL] Kon de MQTT service niet opstarten: {e}")

def stop_mqtt() -> None:
    """
    Stopt de MQTT client netjes af als de FastAPI server wordt afgesloten.
    """
    client.loop_stop()
    client.disconnect()
    print("[MQTT] Service veilig afgesloten.")