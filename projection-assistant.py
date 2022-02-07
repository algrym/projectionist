#!/usr/bin/env python3 -W all

import argparse

VERSION = '0.1.0'


def parse_cli_arguments():
    """ Parse command-line arguments """

    parser = argparse.ArgumentParser()
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
    parser.add_argument(  # Ideally, this should be a sub_parser
        "command",
        nargs="?",
        choices=['dump', 'version', 'help'],
        help="command to execute"
    )

    args = parser.parse_args()

    # Handle some quick-exit situations
    if (not args.command or args.command == 'help'):
        parser.print_help()
        exit(0)
    elif (args.command == 'version'):
        print(VERSION)
        exit(0)

    return args


def main():
    args = parse_cli_arguments()
    print(args)


if __name__ == "__main__":
    main()
