import RPi.GPIO as GPIO
import os
from dotenv import load_dotenv
import sys
import time
import json
import threading
from websocket import WebSocketApp
import ssl

load_dotenv()

# ─── Configuration ─────────────────────────────────────────────────────────────
PIN        = 2      # BCM pin connected to coin acceptor
PULSE_VAL  = 0      # level that indicates a pulse
BOUNCE_MS  = 36     # debounce time

WS_URL     = os.environ['COIN_READER_WS_URL']

# ─── Globals ──────────────────────────────────────────────────────────────────
prev_val   = None
ws_app: WebSocketApp = None
ws_lock    = threading.Lock()

# ─── GPIO Setup / Teardown ────────────────────────────────────────────────────
def setup_gpio():
    global prev_val
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    prev_val = GPIO.input(PIN)
    GPIO.add_event_detect(PIN, GPIO.BOTH, callback=coin_interrupt, bouncetime=BOUNCE_MS)

def cleanup_gpio():
    GPIO.cleanup()

# ─── Pulse Callback ────────────────────────────────────────────────────────────
def coin_interrupt(pin):
    """Called on every edge; we only care when it goes to PULSE_VAL."""
    global prev_val
    val = GPIO.input(pin)
    if val == PULSE_VAL and prev_val != PULSE_VAL:
        print("Pulse! sending delta=1")
        sys.stdout.flush()
        send_coin_update(1)
    prev_val = val

# ─── WebSocket Helpers ────────────────────────────────────────────────────────
def on_ws_open(ws):
    print("WebSocket: connection opened")

def on_ws_message(ws, message):
    print("WebSocket: received:", message)

def on_ws_error(ws, error):
    print("WebSocket: error:", error)

def on_ws_close(ws, code, msg):
    print(f"WebSocket: closed ({code}) {msg}")

def start_ws():
    """Initialize WS and run it in its own thread."""
    global ws_app
    ws_app = WebSocketApp(
        WS_URL,
        on_open=on_ws_open,
        on_message=on_ws_message,
        on_error=on_ws_error,
        on_close=on_ws_close,
    )
    ssl_opts = {"cert_reqs": ssl.CERT_NONE}
    t = threading.Thread(
        target=lambda: ws_app.run_forever(
            sslopt=ssl_opts,
            ping_interval=30,
            ping_timeout=10,
        )
    )
    t.daemon = True
    t.start()

def send_coin_update(delta: int):
    """Send only the number of coins just inserted (delta)."""
    global ws_app
    payload = {
        "event":      "coin_inserted",
        "delta":      delta,
        "timestamp":  int(time.time())
    }
    with ws_lock:
        if ws_app and ws_app.sock and ws_app.sock.connected:
            try:
                ws_app.send(json.dumps(payload))
                print("Sent WS update:", payload)
            except Exception as e:
                print("Failed to send WS message:", e)
        else:
            print("WS not connected, could not send:", payload)

# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Starting coin reader & WebSocket client…")
    setup_gpio()
    start_ws()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down…")
    finally:
        cleanup_gpio()
        if ws_app:
            ws_app.close()

if __name__ == "__main__":
    main()
