#----------------------------------------------------------------
# The callback for when the broker responds to our connection request.
def on_connect(client, usDevilIsInTheDetailserdata, flags, rc):
    global logging
    if rc==0:
        logging.info(f"MQTT connect flags: {flags}, result code: {rc}")
        client.isConnected=True
    elif rc==1:
        logging.error(f"MQTT connect refused: incorrect protocol version, flags: {flags}, result code: {rc}")
        client.isConnected=False
    elif rc==2:
        logging.error(f"MQTT connect refused: invalid client identifier, flags: {flags}, result code:  {rc}")
        client.isConnected=False
    elif rc==3:
        logging.error(f"MQTT connect refused: server unavailable, flags: {flags}, result code: {rc}")
        client.isConnected=False
    elif rc==4:
        logging.error(f"MQTT connect refused: bad username or password, flags: {flags}, result code:   {rc}")
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
    global logging
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
    global logging
    logging.debug(f"mqtt disconnect userdata: {userdata} rc: {rc}")
    client.isConnected=False
    return
