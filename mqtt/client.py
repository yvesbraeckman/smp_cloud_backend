"""
MQTT Client Configuration
=========================

Maintains a persistent MQTT connection between the FastAPI cloud backend and
the Mosquitto broker. The client runs in a dedicated background thread and
subscribes to incoming events from all locker walls (deliveries, pickups,
returns, alarms, telemetry, and sync requests).
"""

import os
import json
import ssl
import paho.mqtt.client as mqtt
from typing import Any

from mqtt.handlers import (
    handle_delivery,
    handle_pickup,
    handle_alarm,
    handle_telemetry,
    handle_request_sync,
    push_user_to_edge,
    handle_return,
    handle_collect,
    handle_flush_complete,
)

# ==========================================
# Configuration (environment variables with no defaults — must be set)
# ==========================================

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT"))

MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")

# Fixed client ID identifies this backend uniquely on the broker
client = mqtt.Client(client_id="fastapi_cloud_backend")


# ==========================================
# Callbacks
# ==========================================

def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
    """Called when the broker connection succeeds or fails.

    On success (rc == 0), subscribes to all locker-wall topics:
      - ``lockers/+/events/#``   — all event sub-types for any location
      - ``lockers/+/telemetry``  — periodic heartbeat for any location

    The ``+`` wildcard matches exactly one topic level (the location_id),
    and ``#`` matches all remaining levels.

    Args:
        client: The MQTT client instance.
        userdata: User-defined data (unused).
        flags: Response flags from the broker.
        rc: Result code — 0 means success.
    """
    if rc == 0:
        print("[MQTT] Cloud backend connected to broker successfully.")
        client.subscribe("lockers/+/events/#")
        client.subscribe("lockers/+/telemetry")
    else:
        print(f"[MQTT ERROR] Connection failed with code {rc}")


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    """Main message router. Parses the topic and dispatches to the correct handler.

    Expected topic format: ``lockers/{location_id}/{category}[/{event_type}]``

    Dispatched event types (under ``events/``):
      - delivery, pickup, return, collect, alarm, request_sync, flush_complete

    The ``telemetry`` category is handled separately without a sub-type.

    Args:
        client: The MQTT client instance.
        userdata: User-defined data (unused).
        msg: The received MQTT message.
    """
    print(f"\n[MQTT DEBUG] ---> Message received on topic: {msg.topic}")
    print(f"[MQTT DEBUG] ---> Raw payload: {msg.payload.decode()}")

    topic_parts = msg.topic.split("/")

    if len(topic_parts) < 3:
        print("[MQTT DEBUG] Topic structure too short, ignoring.")
        return

    location_id = topic_parts[1]
    category = topic_parts[2]

    try:
        payload = json.loads(msg.payload.decode())
        print(f"[MQTT DEBUG] JSON parsed successfully. Category: {category}")

        if category == "events" and len(topic_parts) >= 4:
            event_type = topic_parts[3]
            print(f"[MQTT DEBUG] Event type detected: {event_type}")

            if event_type == "delivery":
                handle_delivery(client, location_id, payload)
            elif event_type == "pickup":
                handle_pickup(client, location_id, payload)
            elif event_type == "return":
                handle_return(client, location_id, payload)
            elif event_type == "collect":
                handle_collect(client, location_id, payload)
            elif event_type == "alarm":
                handle_alarm(client, location_id, payload)
            elif event_type == "request_sync":
                handle_request_sync(client, location_id, payload)
            elif event_type == "flush_complete":
                handle_flush_complete(client, location_id, payload)
            else:
                print(f"[MQTT WARNING] Unknown event type: {event_type}")

        elif category == "telemetry":
            handle_telemetry(client, location_id, payload)

    except json.JSONDecodeError:
        print("[MQTT ERROR] Payload is not valid JSON.")
    except Exception as e:
        print(f"[MQTT ERROR] Error processing message: {e}")


# ==========================================
# Client setup and lifecycle
# ==========================================

client.on_connect = on_connect
client.on_message = on_message

# MQTTS on port 8883. Because communication happens over the Docker network
# using the service name (not a real domain), hostname verification is disabled.
client.tls_set(cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)
client.username_pw_set(MQTT_USER, MQTT_PASS)


def start_mqtt() -> None:
    """Connect to the broker and start the non-blocking background event loop.

    Called once at FastAPI startup. The keepalive interval is 60 seconds.
    """
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"[MQTT FATAL] Could not start MQTT service: {e}")


def stop_mqtt() -> None:
    """Stop the background loop and disconnect from the broker.

    Called on FastAPI shutdown to ensure a clean disconnect.
    """
    client.loop_stop()
    client.disconnect()
    print("[MQTT] Service shut down safely.")