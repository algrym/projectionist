#!/usr/bin/python3

# List of Raspbian pre-req packages
# sudo apt install python3-serial python3-serial-asyncio python3-paho-mqtt python3-pexpect python3-yaml

################################################################
# Import standard Python libraries.
import sys, time, signal, platform, logging, argparse

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
original_sigint_handler = None

################################################################
# Initial Setup
print("Projectionist - Heading into the projection booth ...")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--config-file', default='config.yaml',
            help="load configuration from CONFIG_FILE")
    parser.add_argument('-v', '--verbose', action="store_true",
            help="output additional information")
    args = parser.parse_args()

if args.verbose:
    logLevel=logging.DEBUG
else:
    logLevel=logging.WARNING
# TODO: log output may need to change when we start interfacing with systemd
logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logLevel)

################################################################
# Load config from file
#  TODO: Handle invalid YAML
with open(args.config_file) as f:
    config = yaml.safe_load(f)

logging.info(f"Configuration loaded from '{args.config_file}': {config}")

################################################################
# Attach a handler to the keyboard interrupt (control-C).
def _sigint_handler(signalNumber, stackFrame):
    logging.info("SIGINT caught, closing down ...")
    signal.signal(signal.SIGINT, original_sigint_handler)

    logging.debug("Closing serial port ...")
    if serial_port is not None:
        serial_port.close()
    logging.info("Serial port closed") 

    logging.debug("Closing MQTT client ...")
    if client is not None:
        client.loop_stop()
        client.disconnect()
    logging.info("MQTT client closed") 

    logging.info("Exiting.  You don't have to go home, but you can't stay here.")
    sys.exit(0)

logging.debug("SIGINT handler installed")
original_sigint_handler = signal.getsignal(signal.SIGINT)
signal.signal(signal.SIGINT, _sigint_handler)

################################################################
# MQTT callbacks and setup

#----------------------------------------------------------------
# The callback for when the broker responds to our connection request.
def on_connect(client, userdata, flags, rc):
    if rc==0:
        client.isConnected=True
        logging.info(f"MQTT connect flags: {flags}, result code: {rc}")
    elif rc==1:
        logging.error(f"MQTT connect refused: incorrect protocol version, flags: {flags}, result code: {rc}")
    elif rc==2:
        logging.error(f"MQTT connect refused: invalid client identifier, flags: {flags}, result code: {rc}")
    elif rc==3:
        logging.error(f"MQTT connect refused: server unavailable, flags: {flags}, result code: {rc}")
    elif rc==4:
        logging.error(f"MQTT connect refused: bad username or password, flags: {flags}, result code: {rc}")
    elif rc==5:
        logging.error(f"MQTT connect refused: not authorized, flags: {flags}, result code: {rc}")
    else:
        logging.error(f"MQTT connect failed: unknown reason, flags: {flags}, result code: {rc}")

    # Subscribing in on_connect() means that if we lose the
    # connection and reconnect then subscriptions will be renewed.
    client.subscribe(config['mqtt_topic_prefix'] + "/#")
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
    logging.debug(f"mqtt msg topic: {msg.topic} payload: {msg.payload}")

    # If the serial port is ready, re-transmit received messages to the
    # device. The msg.payload is a bytes object which can be directly sent to
    # the serial port with an appended line ending.
    #if serial_port is not None and serial_port.is_open:
        # TODO: convert incoming MQTT request to appropriate projector commands
        # TODO: MQTT requests to commands should come from config.yaml
        #serial_port.write(msg.payload + b'\n')
    return

#----------------------------------------------------------------
# called when the client disconnects from the broker.
def on_disconnect(client, userdata, rc):
    logging.debug(f"mqtt disconnect client: {client} userdata: {userdata} rc: {rc}")
    client.isConnected=False

#----------------------------------------------------------------
# This faux-callback gets called when there's incoming serial input
def parseSerialInput(input):
    logging.debug(f"serial: {input}")

################################################################
# Launch the MQTT network client
logging.debug("Setting up MQTT client")
client = mqtt.Client(client_id=platform.node(), clean_session=True)
client.enable_logger(logger=logging)

# Assign callbacks
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect

if config['mqtt_use_tls']:
    logging.debug("Enabling TLS for MQTT")
    client.tls_set()

client.username_pw_set(config['mqtt_username'], config['mqtt_password'])

#----------------------------------------------------------------
# Start a background thread to connect to the MQTT network.
logging.debug("Starting background thread for MQTT connection")
client.isConnected=False
client.connect_async(config['mqtt_hostname'], port=config['mqtt_portnumber'],
        keepalive=config['mqtt_keepalive'])
client.loop_start()

# wait until all the above MQTT stuff was successful
while not client.isConnected:
    logging.debug("Sleeping for MQTT connection ...")
    time.sleep(1)

################################################################
# Connect to the serial device
#  Needs 9600 8N1 with all flow control disabled
serial_port = serial.Serial(config['serial_port_name'], baudrate=config['serial_port_baud'], bytesize=8, parity='N', stopbits=1, timeout=1.0, xonxoff=False, rtscts=False, dsrdtr=False)
# TODO: ensure checking the serial port was successful

################################################################
# wait briefly for the system to complete waking up
time.sleep(0.2)

# Get initial information from the device
serial_port.write(b'\r*modelname=?#\r')

# Start into the event loop
logging.info(f"Entering event loop for {config['serial_port_name']}.  SIGINT to quit.")
while(True):
    input = serial_port.readline().decode(encoding='ascii', errors='ignore').rstrip()
    if len(input) != 0:
        parseSerialInput(input)
