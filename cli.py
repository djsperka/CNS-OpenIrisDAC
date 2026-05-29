import socket

def run_client():
    # Define the server's IP address and port number
    server_ip = "128.120.140.96"  # Localhost
    server_port = 8282      # Must match the server's port

    # 1. Create a socket object
    # AF_INET specifies IPv4, SOCK_STREAM specifies TCP
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        try:
            # 2. Establish a connection to the server
            client_socket.connect((server_ip, server_port))
            print(f"[CONNECTED] Bound to server {server_ip}:{server_port}")

            # 3. Prepare and send data (must be encoded to bytes)
            message = "Hello, Server!"
            client_socket.sendall(message.encode('utf-8'))
            print(f"[SENT] {message}")

            while True:
                # 4. Receive the server's response (buffer size of 1024 bytes)
                response = client_socket.recv(1024)
                r = response.decode('utf-8')
                print(f"[RECEIVED] {r}")
                if r=='q':
                    break

        except ConnectionRefusedError:
            print("[ERROR] Could not connect. Is the server running?")

if __name__ == "__main__":
    run_client()
