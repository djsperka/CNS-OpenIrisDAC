import socket
from threading import Thread
from globalstate import GlobalState
from shared_resources import in_cal_lock

class CalibratorComm(Thread):
    def __init__(self, state: GlobalState, port=8282, verbose=False):
        """
        Initialize a TCP communication server for calibrator commands.
        
        Args:
            state (GlobalState): The global state instance.
            port (int): TCP port to listen on. Defaults to 8282.
        """
        super().__init__()
        self.state = state
        self.port = port
        self.server_socket = None
        self.client_socket = None
        self.running = False
        self.verbose = verbose

    def run(self):
        """Run the TCP server loop, accepting and handling connections."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', self.port))
        self.server_socket.listen(1)
        self.running = True
        
        try:
            while self.running:
                # Accept a connection
                try:
                    conn, addr = self.server_socket.accept()
                except OSError:
                    break
                self.client_socket = conn
                if self.verbose:
                    print(f"Accepted connection from {self.client_socket.getpeername()[0]}")
                
                try:
                    self._handle_client(conn)
                except Exception as e:
                    print(f"Error handling client: {e}")
                finally:
                    conn.close()
                    self.client_socket = None
        finally:
            if self.server_socket:
                self.server_socket.close()
    
    def _handle_client(self, conn):
        """
        Handle a single client connection.
        
        Expects initial "HELLO\n" message and responds with "OK\n".
        Then receives and processes commands until client disconnects.
        """
        # Set socket timeout to 1 second and buffer input until newline
        conn.settimeout(1)

        # Read initial HELLO line (buffer until '\n')
        recv_buffer = ""
        hello_msg = None
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    # Client disconnected before HELLO
                    return
                recv_buffer += data.decode()
                if ";" in recv_buffer:
                    line, recv_buffer = recv_buffer.split(";", 1)
                    hello_msg = line.strip()
                    break
                else:
                    print(f"partial command {recv_buffer}")
            except socket.timeout:
                # keep waiting for HELLO
                continue

        if hello_msg != "HELLO":
            conn.send(b"ERROR: Expected HELLO;")
            return
        else:
            if self.verbose:
                print("Got HELLO from client. Waiting for commands...")

        # Send OK response
        conn.send(b"OK;")

        # Process commands: buffer until ';' then handle full line
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    # Client disconnected
                    if self.verbose:
                        print("Client disconnected")
                    break

                recv_buffer += data.decode()

                # Process all complete lines in the buffer
                while ";" in recv_buffer:
                    line, recv_buffer = recv_buffer.split(";", 1)
                    command = line.strip()

                    # Parse and execute command
                    response = self.parse_command(command)

                    # Send response
                    conn.send((response + ";").encode())

            except socket.timeout:
                # Short timeout; loop back to receive more data
                continue
            except ConnectionResetError:
                print(f"Connection was reset by peer. Shutting down.")
                break

            except Exception as e:
                print(f"Error in command handling: {e}")
                print(f"{e.__class__}")
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
        if command == "Q":
            with in_cal_lock:
                self.state.calibrating = False
            response = 'OK'
        elif command == "CALIBRATE":
            with in_cal_lock:
                self.state.calibrating = True
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
                c = fields[3]
            except ValueError:
                return "ERROR: x, y, and d must be numbers"            
            print(f"Received F command with x={x}, y={y}, d={d}, c={c}")
            response = 'OK'
            with in_cal_lock:
                self.state.calibration_fixation_x = x
                self.state.calibration_fixation_y = y

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
            with in_cal_lock:
                self.state.calibration_vpdx = vpdx
                self.state.calibration_vpdy = vpdy

        else:
            response = "ERROR: Unknown command"
        
        return response if response is not None else ""
    
    def shutdown(self):
        """Shutdown the server and disconnect any client.
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



if __name__ == "__main__":
    state = GlobalState()
    calibrator_thread = CalibratorComm(state, port=8282, verbose=True)
    try:
        calibrator_thread.start()
        calibrator_thread.join()
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        calibrator_thread.stop()
    
