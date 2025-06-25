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

# GPIO / pulse settings
PIN = 2                # BCM pin connected to coin acceptor
PULSE_VAL = 0          # level that indicates a pulse
BOUNCE_MS = 36         # debounce time
READ_INTERVAL = 1      # only used for type‑2 polling (you’re using add_event_detect here)

# WebSocket settings
WS_URL = os.environ['COIN_READER_WS_URL'] 

# ─── Globals ──────────────────────────────────────────────────────────────────

prev_val = None
total_amount = 0
ws_app: WebSocketApp = None
ws_lock = threading.Lock()

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

def coin_interrupt(PIN):
    """Called on every edge; we only care when it goes to PULSE_VAL."""
    global prev_val, total_amount
    gpio_val = GPIO.input(PIN)
    # detect the falling (or rising) edge to PULSE_VAL once
    if gpio_val == PULSE_VAL and prev_val != PULSE_VAL:
        total_amount = 1
        print(f"Pulse! total_amount={total_amount}")
        sys.stdout.flush()
        # fire off WS update
        send_coin_update(total_amount)
    prev_val = gpio_val

# ─── WebSocket Helpers ────────────────────────────────────────────────────────

def on_ws_open(ws):
    print("WebSocket: connection opened")
    # Optionally send an initial handshake message:
    # ws.send(json.dumps({"type": "hello", "source": "raspi_coin_reader"}))

def on_ws_message(ws, message):
    # If your backend ever pushes messages (unlikely here), handle them:
    print("WebSocket: received:", message)

def on_ws_error(ws, error):
    print("WebSocket: error:", error)

def on_ws_close(ws, close_status_code, close_msg):
    print(f"WebSocket: closed ({close_status_code}) {close_msg}")
    # websocket-client will automatically try to reconnect if you set
    # `run_forever(reconnect=True)`

def start_ws():
    """Initialize the WebSocketApp and run it forever in a background thread."""
    global ws_app
    ws_app = WebSocketApp(
        WS_URL,
        on_open=on_ws_open,
        on_message=on_ws_message,
        on_error=on_ws_error,
        on_close=on_ws_close,
    )
    # run_forever will block, so spin it off into its own thread
    ssl_opts = {"cert_reqs": ssl.CERT_NONE}
    wst = threading.Thread(
        target=lambda: ws_app.run_forever(
            sslopt=ssl_opts,
            ping_interval=30,
            ping_timeout=10,
        )
    )
    wst.daemon = True
    wst.start()

def send_coin_update(count: int):
    """Safely send the updated total_amount to the WS server."""
    global ws_app
    payload = {
        "event": "coin_inserted",
        "coin_count": count,
        "timestamp": int(time.time())
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

# ─── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    print("Starting coin reader & WebSocket client…")
    setup_gpio()
    start_ws()

    try:
        # we don't need to do anything in the loop, interrupts + WS thread handle it
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down…")
    finally:
        cleanup_gpio()
        # also close WS cleanly
        if ws_app:
            ws_app.close()

if __name__ == "__main__":
    main()
