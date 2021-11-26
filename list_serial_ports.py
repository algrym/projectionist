#!/usr/bin/python3

import sys, serial.tools.list_ports

print("All available serial ports:")
for p in serial.tools.list_ports.comports():
  print(" ", p.device)
sys.exit(0)
