#!/usr/bin/env python3
"""Example client for the CalibratorComm TCP server."""

import socket


def send_command(sock: socket.socket, command: str) -> str:
    sock.sendall((command + ";").encode())
    response = sock.recv(1024).decode().strip()
    print(f"Sent: {command!r} -> Received: {response!r}")
    return response


def main() -> None:
    host = "127.0.0.1"
    port = 8282

    print(f"Connecting to {host}:{port}")
    with socket.create_connection((host, port), timeout=5) as sock:
        # sock.sendall(b"HELLO;")
        # hello_resp = sock.recv(1024).decode().strip()
        # print(f"HELLO response: {hello_resp!r}")
        hello_resp = send_command(sock, "HELLO")

        if hello_resp != "OK;":
            print("Server did not accept HELLO, exiting.")
            return

        send_command(sock, "F 1.0,2.0,3.0,example")
        send_command(sock, "V 1.2,3.4")
        send_command(sock, "q")



if __name__ == "__main__":
    main()
