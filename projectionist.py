#!/usr/bin/python3 -W all

# List of Raspbian pre-req packages, assuming Raspian (buster)
# sudo apt install python3-serial python3-serial-asyncio \
#        python3-paho-mqtt python3-pexpect python3-yaml \
#        python3-systemd

################################################################
# Import libraries - we're _assuming_ POSIX
import sys, time, signal, platform, logging, argparse, queue
import threading

# Paho MQTT client to interface with Home Asssitant.
#   https://www.eclipse.org/paho/clients/python/docs/
import paho.mqtt.client as mqtt

# pySerial for COM port access
#   https://pyserial.readthedocs.io/en/latest/
import serial

# PyYAML for config files
import yaml

# JSON for config topics
import json

# systemd components
import systemd.daemon
import systemd.journal

################################################################
# Global script variables.
serial_port = None
client = None
config = None
original_sigint_handler = None
original_sigterm_handler = None
original_sig_pipethandler = None
publishQ = None
serialQ = None
log = None
client_is_connected = False

################################################################
# Initial Setup
logger.info("Projectionist v1.0 - Heading into the projection booth ... It's aliiiive!")

#----------------------------------------------------------------
# Parse CLI arguments
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--config-file', default='config.yaml',
            help='load configuration from CONFIG_FILE')
    parser.add_argument('-v', '--verbose', action='store_true',
            help='output additional information')
    args = parser.parse_args()

#----------------------------------------------------------------
# Setup logger to systemd or STDOUT

# get an instance of the logger object this module will use
logger = logging.getLogger('projectionist')
logger.propagate=False

# how much output?
if args.verbose:
    logLevel=logging.DEBUG
else:
    logLevel=logging.WARNING
logger.setLevel(logLevel)

# Send all logging messages to the journal
logging.root.addHandler(systemd.journal.JournalHandler())
logger.addHandler(systemd.journal.JournalHandler())

#----------------------------------------------------------------
# Initial setup of the inbound and outbound queues
publishQ = queue.Queue()
serialQ = queue.Queue()

################################################################
# Load config from file
with open(args.config_file) as f:
    config = yaml.safe_load(f)

logger.info(f"Configuration loaded from \"{args.config_file}\": {config}")

#----------------------------------------------------------------
# Setup composite config elements
if config['mqtt']['topic']['node_id'] == 'HOSTNAME':
    config['mqtt']['topic']['node_id'] = platform.node()

# topic: <prefix>/[<node_id>/]<object_id>
mqtt_topic = f"{config['mqtt']['topic']['prefix']}/{config['mqtt']['topic']['node_id']}/{config['mqtt']['topic']['object_id']}"
logger.debug(f"MQTT using topic base: {mqtt_topic}")

# LWT := Last will and testament
availability_topic = mqtt_topic + "/LWT"
logger.debug(f"MQTT using availability topic: {availability_topic}")

# Compute the queue wait timeout
queue_timeout = int(1.1 * int(config['worker']['delay']))
logger.debug(f"using {queue_timeout}s queue timeout at 110% of worker delay ({config['worker']['delay']})")

################################################################
# Attach a handler to the keyboard interrupt (control-C).
def _signal_handler(signal_number, stack_frame):
    logger.info(f"Signal {signal.Signals(signal_number).name} caught, closing down ...")
    systemd.daemon.notify("STOPPING=1")

    signal.signal(signal.SIGINT, original_sigint_handler)
    signal.signal(signal.SIGTERM, original_sigterm_handler)
    signal.signal(signal.SIGPIPE, original_sigpipe_handler)

    if serial_port is not None:
        logger.debug("Closing serial port ...")
        serial_port.close()

    if client is not None:
        logger.debug("Closing MQTT client ...")
        publish_availability(False)
        client.loop_stop()
        client.disconnect()

    logger.info("Exiting.  You don't have to go home, but you can't stay here.")
    sys.exit(0)

#----------------------------------------------------------------
# Install SIGINT signal handler ASAP
logger.debug("Installing signal handlers ...")

original_sigint_handler = signal.getsignal(signal.SIGINT)
signal.signal(signal.SIGINT, _signal_handler)

original_sigterm_handler = signal.getsignal(signal.SIGTERM)
signal.signal(signal.SIGTERM, _signal_handler)

original_sigpipe_handler = signal.getsignal(signal.SIGPIPE)
signal.signal(signal.SIGPIPE, _signal_handler)

################################################################
# MQTT callbacks and setup

#----------------------------------------------------------------
# The callback for when the broker responds to our connection request.
def on_mqtt_connect(client, userdata, flags, rc):
    global client_is_connected
    if rc==0:
        logger.info(f"MQTT connect flags=\"{flags}\", result code={rc}")
        client_is_connected = True
    elif rc==1:
        logger.error(f"MQTT connect refused: incorrect protocol version, flags={flags}, result code={rc}")
        client_is_connected = False
        return
    elif rc==2:
        logger.error(f"MQTT connect refused: invalid client identifier, flags={flags}, result code={rc}")
        client_is_connected = False
        return
    elif rc==3:
        logger.error(f"MQTT connect refused: server unavailable, flags={flags}, result code={rc}")
        client_is_connected = False
        return
    elif rc==4:
        logger.error(f"MQTT connect refused: bad username or password, flags={flags}, result code={rc}")
        client_is_connected = False
        return
    elif rc==5:
        logger.error(f"MQTT connect refused: not authorized, flags={flags}, result code={rc}")
        client_is_connected = False
        return
    else:
        logger.error(f"MQTT connect failed: unknown reason, flags={flags}, result code={rc}")
        client_is_connected = False
        return

    # Subscribing in on_mqtt_connect() means that if we lose the
    # connection and reconnect then subscriptions will be renewed.

    # Subscribe to the appropriate locations
    #   If you add more here, be sure to update the "topic.startswith"
    #   section in on_message function
    client.subscribe(mqtt_topic + "/power/set")
    client.subscribe(mqtt_topic + "/source/set")
    client.subscribe(mqtt_topic + "/blank/set")

    # Update mqtt availability topic on connect
    publish_availability(True)

#----------------------------------------------------------------
# The callback for when a message has been received on a topic to which this
# client is subscribed.  The message variable is a MQTTMessage that describes
# all of the message parameters.

# Some useful MQTTMessage fields: topic, payload, qos, retain, mid, properties.
#   The payload is a binary string (bytes).
#   qos is an integer quality of service indicator (0,1, or 2)
#   mid is an integer message ID.
def on_mqtt_message(client, userdata, msg):
    if msg.topic.startswith(mqtt_topic):
        msg_to_cmds(msg.topic.split('/')[3], msg.payload)
    else:
        logger.debug(f"mqtt msg unknown mid={msg.mid} topic=\"{msg.topic}\" payload=\"{msg.payload}\"")

#----------------------------------------------------------------
# called when the client disconnects from the broker.
def on_mqtt_disconnect(client, userdata, rc):
    logger.debug(f"mqtt disconnect userdata=\"{userdata}\" rc={rc}")
    client_is_connected = False

#----------------------------------------------------------------
# Handle the details of an mqtt publish
#   If the publish fails, put the item on the publishQ
def mqtt_publish(topic, payload, retain=False):
    publishQ.put((topic, payload, retain), block=True, timeout=queue_timeout)

#----------------------------------------------------------------
# This faux-callback gets called when there's incoming serial input
def parse_serial_input(input):
    # Trim stuff from the beginning and end of the input
    input.strip()

    # Ignore input that's echo'd back from the projector
    if input.startswith('>'):
        logger.debug(f"serial echo back: {repr(input)}")

    # Handle weird power-on state message
    elif input == '0.33PUN':
        logger.debug(f"serial weird power-on state message: \"{repr(input)}\"")
        serialQ.put(b'\r*pow=?#\r')

    # Handle various known responses from the projector
    elif input.startswith('*MODELNAME='):
        logger.debug(f"serial found MODELNAME={input[11:-1]}")
        mqtt_publish(topic=mqtt_topic + "/modelname", payload=input[11:-1])

    elif input.startswith('*LTIM='):
        logger.debug(f"serial found LTIM={input[6:-1]}")
        mqtt_publish(topic=mqtt_topic + "/lamphour", payload=input[6:-1])

    elif input.startswith('*POW='):
        logger.debug(f"serial found POW={input[5:-1]}")
        mqtt_publish(topic=mqtt_topic + "/power", payload=input[5:-1])

    elif input.startswith('*SOUR='):
        logger.debug(f"serial found SOUR={input[6:-1]}")
        mqtt_publish(topic=mqtt_topic + "/source", payload=input[6:-1])

    elif input.startswith('*BLANK='):
        logger.debug(f"serial found BLANK={input[7:-1]}")
        mqtt_publish(topic=mqtt_topic + "/blank", payload=input[7:-1])

    else:
        logger.debug(f"serial unknown \"{repr(input)}\"")

#----------------------------------------------------------------
# This worker thread handles the outbound serial queue
def serialq_worker():
    logger.debug(f"serialQ worker starting.")
    while True:
        # Block until there's an object on the queue
        msg = serialQ.get(block=True, timeout=queue_timeout)
        logger.debug(f"serialQ worker: qsize={serialQ.qsize()} msg=\"{msg}\"")
        systemd.daemon.notify("WATCHDOG=1")

        # Push the object from the queue out the serial port
        try:
            serial_port.write(msg)
        except Exception as e:
            logger.error(f'serialQ port write error msg=\"{msg}\" error=\"{e}\"')
            sys.exit(os.EX_IOERR)

        # Let the queue know that we're successful
        serialQ.task_done()
        time.sleep(0.1) # Pause to let the serial port settle

#----------------------------------------------------------------
# This worker thread handles the outbound serial queue
def publishq_worker():
    logger.debug(f"publishQ worker starting.")
    while True:
        # Block until there's an object on the queue
        topic, payload, retain = publishQ.get(block=True, timeout=queue_timeout)
        logger.debug(f"publishQ worker: qsize={publishQ.qsize()} topic=\"{topic}\" payload=\"{payload}\" retain=\"{retain}\"")
        systemd.daemon.notify("WATCHDOG=1")

        # publish the object from the queue
        result = client.publish(topic, payload=payload, qos=0, retain=retain)
        if result.rc == 0 and result.is_published():
            # Let the queue know that we're successful
            logger.debug(f"publishQ worker success mid={result.mid}")
            publishQ.task_done()
        else:
            logger.debug(f"publishQ worker failed mid={result.mid} rc={result.rc} result.is_published()={result.is_published()}")
            time.sleep(0.1) # Don't spin if things go wrong

#----------------------------------------------------------------
# Convert messages into commands for the projector
def msg_to_cmds(msg_command, msg_payload):
    logger.debug(f"msg_to_cmds cmd=\"{msg_command}\" payload=\"{msg_payload}\"")
    if msg_command == 'blank':
        if msg_payload == b'ON':
            serialQ.put(b'\r*blank=on#\r')
        elif msg_payload == b'OFF':
            serialQ.put(b'\r*blank=off#\r')
        else:
            serialQ.put(b'\r*blank=?#\r')

    elif msg_command == 'power':
        if msg_payload == b'ON':
            serialQ.put(b'\r*pow=on#\r')
        elif msg_payload == b'OFF':
            serialQ.put(b'\r*pow=off#\r')
        else:
            serialQ.put(b'\r*pow=?#\r')

    elif msg_command == 'source':
        if msg_payload == b'HDMI' or msg_payload == b'HDMI1':
            serialQ.put(b'\r*sour=hdmi#\r')
        elif msg_payload == b'HDMI2':
            serialQ.put(b'\r*sour=hdmi2#\r')
        elif msg_payload == b'RGB':
            serialQ.put(b'\r*sour=rgb#\r')
        elif msg_payload == b'USB':
            serialQ.put(b'\r*sour=usbreader#\r')
        else:
            serialQ.put(b'\r*sour=?#\r')

#----------------------------------------------------------------
# Update the availability topic of the device
#   https://www.hivemq.com/blog/mqtt-essentials-part-9-last-will-and-testament/
def publish_availability(available=True):
    logger.debug(f"publish availability topic=\"{availability_topic}\" available={available}")
    if available:
        mqtt_publish(topic=availability_topic, payload="Online", retain=False)
    else:
        mqtt_publish(topic=availability_topic, payload="Offline", retain=True)

#----------------------------------------------------------------
# Build and publish the configuration for related devices
# - Switch for /power
def publish_switch_config():
    logger.info(f"Transmitting JSON to config switch topic")

    # <discovery_prefix>/<component>/[<node_id>/]<object_id>/config
    # Best practice for entities with a unique_id is to set <object_id> to unique_id and omit the <node_id>, so ...
    # <discovery_prefix>/<component>/<unique_id>/config
    unique_id = config['mqtt']['topic']['unique_id'] + "_power"
    config_topic = f"{config['mqtt']['discovery']['prefix']}/switch/{unique_id}/config"

    # Setting up power
    power_switch_config = {
        "name": config['mqtt']['topic']['name'] + ' power',
        "state_topic": mqtt_topic + "/power",
        "command_topic": mqtt_topic + "/power/set",
        "payload_off": "OFF",
        "payload_on": "ON",
        "value_template": "{{value_json.power}}",
        "availability_topic": mqtt_topic + "/LWT",
        "payload_available": "Online",
        "payload_not_available": "Offline",
        "unique_id": unique_id,
        "device": {
            "via_device": platform.node(),
            "manufacturer": config['device']['manufacturer'],
            "model": config['device']['model'],
            "identifiers": unique_id,
            }
    }
    mqtt_publish(topic=config_topic,
           payload=json.dumps(power_switch_config), retain=True)

#----------------------------------------------------------------
# Build and publish the configuration for related devices
# - Source for /source
def publish_select_config():
    logger.info(f"Transmitting JSON to config select topic")

    # <discovery_prefix>/<component>/<unique_id>/config
    unique_id = config['mqtt']['topic']['unique_id'] + "_source"
    config_topic = f"{config['mqtt']['discovery']['prefix']}/select/{unique_id}/config"

    # Setting up source select
    source_select_config= {
        "name": config['mqtt']['topic']['name'] + ' input source',
        "state_topic": mqtt_topic + "/source",
        "command_topic": mqtt_topic + "/source/set",
        "options": ["HDMI", "HDMI2", "RGB", "USB"],
        "value_template": "{{value_json.source}}",
        "availability_topic": mqtt_topic + "/LWT",
        "payload_available": "Online",
        "payload_not_available": "Offline",
        "unique_id": unique_id,
        "device": {
            "via_device": platform.node(),
            "manufacturer": config['device']['manufacturer'],
            "model": config['device']['model'],
            "identifiers": unique_id,
        }
    }
    mqtt_publish(topic=config_topic,
           payload=json.dumps(source_select_config), retain=True)

#----------------------------------------------------------------
# Worker thread to periodically push initial commands onto the serial queue
def timed_worker():
    while True:
        logger.info(f"timed_worker awakens!")
        systemd.daemon.notify("WATCHDOG=1")

        # Poke the projector into updating its current state
        serialQ.put(b'\r*modelname=?#\r')
        serialQ.put(b'\r*ltim=?#\r')
        serialQ.put(b'\r*pow=?#\r')
        serialQ.put(b'\r*sour=?#\r')
        serialQ.put(b'\r*blank=?#\r')

        # Publish the config for the projector
        publish_switch_config()
        publish_select_config()

        # Publish availability
        publish_availability(True)

        logger.info(f"worker updates queued. Sleeping for {config['worker']['delay']} secs")
        time.sleep(config['worker']['delay'])

################################################################
# Launch the MQTT network client
logger.debug("Starting MQTT client setup")
client = mqtt.Client(client_id=platform.node(), clean_session=True)
client.enable_logger(logger=logger)

# Assign callbacks
client.on_connect = on_mqtt_connect
client.on_message = on_mqtt_message
client.on_disconnect = on_mqtt_disconnect

if config['mqtt']['useTLS']:
    logger.debug("Enabling TLS for MQTT")
    client.tls_set()

client.username_pw_set(config['mqtt']['username'], config['mqtt']['password'])

#----------------------------------------------------------------
# Start a background thread to connect to the MQTT network.
logger.debug("Starting background thread for MQTT connection")
client.connect_async(config['mqtt']['hostname'], port=config['mqtt']['portnumber'],
        keepalive=config['mqtt']['keepalive'])
client.loop_start()

################################################################
# Connect to the serial device
#  Needs 9600 8N1 with all flow control disabled
serial_port = serial.Serial(config['serial_port']['name'],
        baudrate=config['serial_port']['baud'],
        bytesize=8,
        parity='N',
        stopbits=1,
        timeout=1.0,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False)

################################################################
# wait briefly for the system to complete waking up
time.sleep(1)

# Start thread to periodically push initial commands onto the serial queue
threading.Thread(target=timed_worker, daemon=True).start()
threading.Thread(target=serialq_worker, daemon=True).start()
threading.Thread(target=publishq_worker, daemon=True).start()

# Start the event loop
logger.info(f"Entering event loop for {config['serial_port']['name']}")

# Tell systemd that our service is ready
systemd.daemon.notify('READY=1')

while(True):
    input = serial_port.readline().decode(encoding='ascii', errors='ignore').rstrip()
    if len(input) != 0:
        systemd.daemon.notify('WATCHDOG=1')
        parse_serial_input(input)
