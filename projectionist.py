#!/usr/bin/python3 -W all

# List of Raspbian pre-req packages
# sudo apt install python3-serial python3-serial-asyncio python3-paho-mqtt python3-pexpect python3-yaml

################################################################
# Import standard Python libraries - we're assuming POSIX
import sys, time, signal, platform, logging, argparse, pprint

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
# TODO: log output needs to change when we start interfacing with systemd
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

    logging.debug("Closing MQTT client ...")
    if client is not None:
        client.loop_stop()
        client.disconnect()

    logging.info("Exiting.  You don't have to go home, but you can't stay here.")
    sys.exit(0)

#----------------------------------------------------------------
# Install SIGINT signal handler ASAP
logging.debug("SIGINT handler ready")
original_sigint_handler = signal.getsignal(signal.SIGINT)
signal.signal(signal.SIGINT, _sigint_handler)

################################################################
# MQTT callbacks and setup

#----------------------------------------------------------------
# The callback for when the broker responds to our connection request.
def on_connect(client, userdata, flags, rc):
    if rc==0:
        logging.info(f"MQTT connect flags: {flags}, result code: {rc}")
        client.isConnected=True
    elif rc==1:
        logging.error(f"MQTT connect refused: incorrect protocol version, flags: {flags}, result code: {rc}")
        client.isConnected=False
    elif rc==2:
        logging.error(f"MQTT connect refused: invalid client identifier, flags: {flags}, result code: {rc}")
        client.isConnected=False
    elif rc==3:
        logging.error(f"MQTT connect refused: server unavailable, flags: {flags}, result code: {rc}")
        client.isConnected=False
    elif rc==4:
        logging.error(f"MQTT connect refused: bad username or password, flags: {flags}, result code: {rc}")
        client.isConnected=False
    elif rc==5:
        logging.error(f"MQTT connect refused: not authorized, flags: {flags}, result code: {rc}")
        client.isConnected=False
    else:
        logging.error(f"MQTT connect failed: unknown reason, flags: {flags}, result code: {rc}")
        client.isConnected=False

    # Subscribing in on_connect() means that if we lose the
    # connection and reconnect then subscriptions will be renewed.
    client.subscribe(config['mqtt']['topicPrefix'] + "/#")
    # TODO: Use https://github.com/eclipse/paho.mqtt.python#message_callback_add
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
    logging.debug(f"mqtt msg mid: {msg.mid} topic: {msg.topic} payload: {msg.payload}")

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
    logging.debug(f"mqtt disconnect userdata: {userdata} rc: {rc}")
    client.isConnected=False
    return

#----------------------------------------------------------------
# Handle the details of an mqtt publish
def mqtt_publish(topic, payload, retain=False):
    result = client.publish(topic, payload=payload, qos=0, retain=retain)
    if result.rc == 0 and result.is_published():
        logging.debug(f"mqtt publish success mid: {result.mid}")
    else:
        logging.debug(f"mqtt publish failed mid: {result.mid} rc: {result.rc} result.is_published()={result.is_published()}")
    return

#----------------------------------------------------------------
# This faux-callback gets called when there's incoming serial input
def parseSerialInput(input):
    if input.startswith('*MODELNAME='):
        logging.debug(f"serial: MODELNAME {input[11:-1]}")
        mqtt_publish(topic=config['mqtt']['topicPrefix'] + "/modelname",
            payload=input[11:-1], retain=True)
    else:
        logging.debug(f"serial: {input}")
    return

################################################################
# Launch the MQTT network client
logging.debug("Setting up MQTT client")
client = mqtt.Client(client_id=platform.node(), clean_session=True)
client.enable_logger(logger=logging)

# Assign callbacks
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect

if config['mqtt']['useTLS']:
    logging.debug("Enabling TLS for MQTT")
    client.tls_set()

client.username_pw_set(config['mqtt']['username'], config['mqtt']['password'])

#----------------------------------------------------------------
# Start a background thread to connect to the MQTT network.
logging.debug("Starting background thread for MQTT connection")
client.isConnected=False
client.connect_async(config['mqtt']['hostname'], port=config['mqtt']['portnumber'],
        keepalive=config['mqtt']['keepalive'])
client.loop_start()

# wait until all the above MQTT stuff was successful
while not client.isConnected:
    logging.debug("Sleeping for MQTT connection ...")
    time.sleep(1)

################################################################
# Connect to the serial device
#  Needs 9600 8N1 with all flow control disabled
serial_port = serial.Serial(config['serialPort']['name'], baudrate=config['serialPort']['baud'], bytesize=8, parity='N', stopbits=1, timeout=1.0, xonxoff=False, rtscts=False, dsrdtr=False)
# TODO: ensure checking the serial port was successful

################################################################
# wait briefly for the system to complete waking up
time.sleep(0.2)

# Get initial information from the device
serial_port.write(b'\r*modelname=?#\r')

# Start into the event loop
logging.info(f"Entering event loop for {config['serialPort']['name']}.  SIGINT to quit.")
while(True):
    input = serial_port.readline().decode(encoding='ascii', errors='ignore').rstrip()
    if len(input) != 0:
        parseSerialInput(input)
