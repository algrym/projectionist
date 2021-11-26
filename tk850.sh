#!/usr/bin/bash

PRJ_PORT=/dev/ttyUSB0
PRJ_PORT=/dev/stdout
PRJ_PORT_BAUD=9600

# Goofy Sh!t I've learned about the TK850:
#
# * It only accepts "sour=hdmi" in lower case.
# * It only accepts "sour=hdmi" despite calling it HDMI1
# * It only accepts '\r', not '\r\n', or '\n'.
# * It only supports these commands:
# ** Power on/off/status
# ** Source change
# ** Model name
# ** Blank on/off/status

#   cs8:     8 data bits
#   -parenb: No parity (because of the '-')
#   -cstopb: 1 stop bit (because of the '-')
#   -echo: Without this option, Linux will sometimes automatically send back
#          any received characters, even if you are just reading from the serial
#          port with a command like 'cat'. Some terminals will print codes
#          like "^B" when receiving back a character like ASCII ETX (hex 03).
#echo -n 'Setting baud to '
#stty -F ${PRJ_PORT} cs8 -parenb -cstopb -echo raw speed ${PRJ_PORT_BAUD}

PRJ_CMD='unknown command'

case "$1" in
  power) 
    case "$2" in
      on)
        PRJ_CMD='\r*pow=on#\r'
        ;;
      off)
        PRJ_CMD='\r*pow=off#\r'
        ;;
      status)
        PRJ_CMD='\r*pow=?#\r'
        ;;
      *)
        echo 'Unknown $2: "'$2'"'
        exit 1
      ;;
    esac
    ;;
  src|source)
    case "$2" in
      status)
        PRJ_CMD='\r*sour=?#\r'
        ;;
      *)
        echo 'Unknown $2: "'$2'"'
        exit 1
      ;;
    esac
    ;;
  *)
    echo 'Unknown $1: "'$1'"'
    exit 1
    ;;
esac
printf ${PRJ_CMD}'\n'
