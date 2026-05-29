import socket
import threading


class CalibratorComm:
    def __init__(self, port=8282):
        """
        Initialize a TCP communication server for calibrator commands.
        
        Args:
            port (int): TCP port to listen on. Defaults to 8282.
        """
        self.port = port
        self.server_socket = None
        self.client_socket = None
        self.running = False
            
    def _run_server(self):
        """Run the TCP server loop, accepting and handling connections."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', self.port))
        self.server_socket.listen(1)
        self.running = True
        
        try:
            while self.running:
                # Accept a connection
                conn, addr = self.server_socket.accept()
                self.client_socket = conn
                
                try:
                    self._handle_client(conn)
                except Exception as e:
                    print(f"Error handling client: {e}")
                finally:
                    conn.close()
                    self.client_socket = None
        finally:
            self.server_socket.close()
    
    def _handle_client(self, conn):
        """
        Handle a single client connection.
        
        Expects initial "HELLO\n" message and responds with "OK\n".
        Then receives and processes commands until client disconnects.
        Allows gaps of up to 30 seconds between commands.
        """
        # Set socket timeout to 30 seconds to allow client gaps
        conn.settimeout(30)
        
        # Expect HELLO
        hello_msg = conn.recv(1024).decode().strip()
        
        if hello_msg != "HELLO":
            conn.send(b"ERROR: Expected HELLO\n")
            return
        
        # Send OK response
        conn.send(b"OK\n")
        
        # Process commands
        while True:
            try:
                # Receive command
                data = conn.recv(1024)
                if not data:
                    # Client disconnected
                    break
                
                # Strip whitespace and newline
                command = data.decode().strip()
                
                # Parse and execute command
                response = self.parse_command(command)
                
                # Send response
                conn.send((response + "\n").encode())
            
            except socket.timeout:
                # Timeout while waiting for command; client is idle but connected
                # Just continue waiting for the next command
                continue
            except Exception as e:
                print(f"Error in command handling: {e}")
                break
    
    def parse_command(self, command: str) -> str:
        """
        Parse and execute a command.
        
        Supported commands:
        - "q": Query command
        - "F <arg1>": F command with a single argument formatted "x,y,d,c" (x,y,d numeric, c string)
        - "V <vpdx>,<vpdy>": V command with two numeric values between 0 and 5
        
        Args:
            command (str): The command to parse (whitespace already stripped)
        
        Returns:
            str: The response to send to the client
        """
        if command == "q":
            # Handle 'q' command
            # TODO: Implement query command
            response = 'OK'
        elif command.startswith("F "):
            # Handle 'F' command with a single argument formatted as "x,y,d,c"
            parts = command.split(maxsplit=1)
            if len(parts) < 2:
                return "ERROR: F command requires an argument in format x,y,d,c"

            payload = parts[1]
            fields = payload.split(",")
            if len(fields) != 4:
                return "ERROR: F argument must be x,y,d,c"

            try:
                x = float(fields[0])
                y = float(fields[1])
                d = float(fields[2])
            except ValueError:
                return "ERROR: x, y, and d must be numbers"

            c = fields[3]

            # TODO: Implement F command handling for x, y, d, c
            print(f"Received F command with x={x}, y={y}, d={d}, c={c}")
            response = 'OK'
        elif command.startswith("V "):
            # Handle 'V' command with two numeric values separated by a comma
            parts = command.split(maxsplit=1)
            if len(parts) < 2:
                return "ERROR: V command requires vpdx,vpdy"

            coords = parts[1].split(",")
            if len(coords) != 2:
                return "ERROR: V command requires vpdx,vpdy"

            try:
                vpdx = float(coords[0])
                vpdy = float(coords[1])
            except ValueError:
                return "ERROR: V command values must be numbers"

            if not (0 <= vpdx <= 5) or not (0 <= vpdy <= 5):
                return "ERROR: V command values must be between 0 and 5"

            # TODO: Implement V command handling for vpdx and vpdy
            print(f"Received V command with vpdx={vpdx}, vpdy={vpdy}")
            response = 'OK'
        else:
            response = "ERROR: Unknown command"
        
        return response if response is not None else ""
    
    def shutdown(self, timeout: float = 1.0):
        """Shutdown the server and disconnect any client.

        Args:
            timeout (float): Seconds to wait for the background thread to stop.
        """
        print("Shutting down calibrator server...")
        self.running = False

        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                self.client_socket.close()
                self.client_socket = None

        if self.server_socket:
            try:
                self.server_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                self.server_socket.close()
                self.server_socket = None


    def stop(self):
        """Stop the server."""
        self.shutdown()
