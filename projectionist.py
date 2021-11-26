#!/usr/bin/python3

# List of Raspbian pre-req packages
# sudo apt install python3-serial python3-serial-asyncio python3-paho-mqtt python3-pexpect python3-yaml

################################################################
# Import standard Python libraries.
import sys, time, signal, pprint, platform, logging

# Import the MQTT client library.
#   https://www.eclipse.org/paho/clients/python/docs/
import paho.mqtt.client as mqtt

# Import the pySerial library.
#   https://pyserial.readthedocs.io/en/latest/
import serial

# Import the PyYAML library.
import yaml

################################################################
# Global script variables.

serial_port = None
client = None
config = None

################################################################
# Load config from file
#  TODO: Handle invalid YAML
with open('config.yaml') as f:
    config = yaml.safe_load(f)

print ("- Configuration loaded from 'config.yaml':")
pprint.pprint(config)

################################################################
# Attach a handler to the keyboard interrupt (control-C).
def _sigint_handler(signal, frame):
    print("\n- Keyboard interrupt caught, closing down...")
    if serial_port is not None:
        serial_port.close()

    if client is not None:
        client.loop_stop()

    sys.exit(0)

print("- SIGINT handler installed.")
signal.signal(signal.SIGINT, _sigint_handler)

################################################################
# MQTT callbacks and setup

#----------------------------------------------------------------
# The callback for when the broker responds to our connection request.
def on_connect(client, userdata, flags, rc):
    print(f"- MQTT connected with flags: {flags}, result code: {rc}")
    pprint.pprint(client)

    # Subscribing in on_connect() means that if we lose the
    # connection and reconnect then subscriptions will be renewed.
    client.subscribe(config['mqtt_subscription'])
    return

#----------------------------------------------------------------
# The callback for when a message has been received on a topic to which this
# client is subscribed.  The message variable is a MQTTMessage that describes
# all of the message parameters.

# Some useful MQTTMessage fields: topic, payload, qos, retain, mid, properties.
#   The payload is a binary string (bytes).
#   qos is an integer quality of service indicator (0,1, or 2)
#   mid is an integer message ID.
def on_message(client, userdata, msg):
    print(f"mqtt: topic: {msg.topic} payload: {msg.payload}")

    # If the serial port is ready, re-transmit received messages to the
    # device. The msg.payload is a bytes object which can be directly sent to
    # the serial port with an appended line ending.
    #if serial_port is not None and serial_port.is_open:
        # TODO: convert incoming MQTT request to appropriate projector commands
        # TODO: MQTT requests to commands should come from config.yaml
        #serial_port.write(msg.payload + b'\n')
    return

#----------------------------------------------------------------
# Launch the MQTT network client
print ("- Setting up MQTT client")
client = mqtt.Client(client_id=platform.node(), clean_session=True)
client.enable_logger(logger=logging.DEBUG)

client.on_connect = on_connect
client.on_message = on_message

client.tls_set()
client.username_pw_set(config['mqtt_username'], config['mqtt_password'])

# Start a background thread to connect to the MQTT network.
print ("- Starting background thread for MQTT connection")
client.connect_async(config['mqtt_hostname'], config['mqtt_portnumber'])
client.loop_start()

# TOOD: check that all the above MQTT stuff was successful

################################################################
# Connect to the serial device
#  Needs 9600 8N1 with all flow control disabled
serial_port = serial.Serial(config['serial_port_name'], baudrate=config['serial_port_baud'], bytesize=8, parity='N', stopbits=1, timeout=1.0, xonxoff=False, rtscts=False, dsrdtr=False)

# wait briefly for the system to complete waking up
time.sleep(0.2)

serial_port.write(b'\r*modelname=?#\r')

print(f"- Entering event loop for {config['serial_port_name']}.  Enter Control-C to quit.")

while(True):
    input = serial_port.readline().decode(encoding='ascii', errors='ignore').rstrip()
    if len(input) != 0:
        print(f"serial: {input}")
