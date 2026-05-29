import serial
import os
#assert os.name == 'nt', 'DAC only works on Windows'
import AIOUSB as ao

class Calibrator:
    def __init__(self, port):
        self.port = port 

    def command(self, cmd: str):
        pass

    def get_response(self):
        response = self.ser.readline().decode().strip()
        return response.split(' ', 2)

    def parse_response(self, response):
        a, b, t_str = response.split(' ', 2)
        if a != 'response' or b != 'calibrate':
            raise RuntimeError(f"Unexpected response: {response}")
        return float(t_str)

    def calibrate(self) -> float:
        self.command('calibrate')
        t = None
        while t is None:
            pass


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
        
        # Start the server in a background thread
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
    
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
        - "F <arg1> <arg2>": F command with two string arguments
        
        Args:
            command (str): The command to parse (whitespace already stripped)
        
        Returns:
            str: The response to send to the client
        """
        if command == "q":
            # Handle 'q' command
            # TODO: Implement query command
            response = None
        elif command.startswith("F "):
            # Handle 'F' command with two arguments
            parts = command.split(maxsplit=2)
            if len(parts) < 3:
                return "ERROR: F command requires two arguments"
            
            arg1 = parts[1]
            arg2 = parts[2]
            
            # TODO: Implement F command with arg1 and arg2
            response = None
        else:
            response = "ERROR: Unknown command"
        
        return response if response is not None else ""
    
    def stop(self):
        """Stop the server."""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
            response = self.ser.readline().decode().strip()