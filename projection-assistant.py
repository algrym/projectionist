#!/usr/bin/env python3 -W all

import argparse


def parse_cli_arguments():
    """ Parse command-line arguments """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dump",
        action="store_true",
        help="dump projector config"
    )
    parser.add_argument(
        "-s",
        "--serial_port",
        type=str,
        default="/dev/serial0",
        help='path to serial device (default: /dev/serial0)',
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="output additional information"
    )
    return parser.parse_args()


def main():
    args = parse_cli_arguments()
    print(args)


if __name__ == "__main__":
    main()
