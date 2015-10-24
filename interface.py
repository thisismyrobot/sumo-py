""" Bare-bones Parrot Jumping Sumo control.
"""
import collections
import datetime
import json
import socket
import struct
import threading
import time
import SocketServer


# Motor commands must be at 40 Hz for video to work.
MOTOR_HZ = 40.0


def hex_repr(data):
    """ Pretty-print binary data.
    """
    return ''.join('\\x{:02x}'.format(ord(c)) for c in str(data))


class SumoPyException(Exception):
    pass


class InitTimeoutException(SumoPyException):
    pass


class SumoController(object):
    """ Parrot Jumping Sumo controller.
    """
    def __init__(self, sumo_ip='192.168.2.1', init_port=44444, d2c_port=54321,
                 start_video_stream=True, sock_timeout=2):
        """ Set up the instance.
        """
        self._sumo_ip = sumo_ip
        self._d2c_port = d2c_port
        self._latest_pic = collections.deque(maxlen=1)
        self._latest_rx = datetime.datetime.now()

        # Do the init handshake, gathering a c2d_port and the size of the
        # video packets.
        self._c2d_port, vid_data_size = self._do_init(init_port, sock_timeout)

        # Create the socket that we'll send data to the sumo via
        self._c2d_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Create and start the threaded listen server. Video packets are
        # larger than the default UDPServer size so we set max_packet_size
        # appropriately.
        instance = self

        class UDPHandler(SocketServer.BaseRequestHandler):
            """ Handler for incoming UDP data.
            """
            def handle(self):
                instance._latest_rx = datetime.datetime.now()
                data = self.request[0]
                # Intercept pictures
                if data.startswith('\x03\x7d'):
                    instance._latest_pic.append(data[12:])

        class UDPServer(SocketServer.UDPServer):
            allow_reuse_address = True

        self._d2c_server = UDPServer(('', d2c_port), UDPHandler)
        self._d2c_server.max_packet_size = vid_data_size
        threading.Thread(target=self._d2c_server.serve_forever).start()

        # Create and start the 40Hz movement sender. This keeps the connection
        # "alive".
        self._commands = collections.deque()
        threading.Thread(
            target=self._cmd_thread,
            args=(self._commands,)
        ).start()

        # Do setup commands
        if start_video_stream:
            self.start_video_stream()

    def _do_init(self, init_port=44444, sock_timeout=2):
        """ Do the init handshake, return the c2d_port.
        """
        init_msg = {
            'controller_name': 'SumoPy',
            'controller_type': 'Python',
            'd2c_port': self._d2c_port,
        }
        init_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        init_sock.settimeout(sock_timeout)
        try:
            init_sock.connect((self._sumo_ip, init_port))
        except socket.timeout:
            raise InitTimeoutException(
                'Failed to perform init with Sumo - could not connect'
            )
        init_sock.sendall(json.dumps(init_msg))

        # Grab the JSON response, strip trailing \x00 to keep it valid.
        init_resp = init_sock.recv(1024)[:-1]
        json_init_resp = json.loads(init_resp)

        c2d_port = json_init_resp['c2d_port']
        if c2d_port == 0:
            raise Exception('Client already connected!')

        return c2d_port, json_init_resp['arstream_fragment_size']

    def _cmd_thread(self, command_list):
        """ Send commands at 40Hz, if no command send stop.
        """
        sequences = collections.defaultdict(int)
        while True:
            try:
                cmd = command_list.popleft()
            except IndexError:
                cmd = self._move_cmd(0, 0)

            # Update the sequence value - there is a sequence per channel.
            cmd[2] = sequences[cmd[1]]
            sequences[cmd[1]] = (sequences[cmd[1]] + 1) % 256

            # Send it!
            self._c2d_sock.sendto(cmd, (self._sumo_ip, self._c2d_port))

            time.sleep(1.0 / MOTOR_HZ)

    def _move_cmd(self, speed, turn):
        """ Create movement commands.
        """
        cmd = SumoController.fab_cmd(
            2,  # No ACK
            10,  # Piloting channel?
            3,  # Jumping Sumo project id = 3
            0,  # Piloting = Class ID 0
            0,  # Command index 0 = PCMD
            struct.pack(
                '<Bbb',  # u8, i8, i8
                1,  # Touch screen = yes
                speed,   # -100 -> 100 %
                turn,    # -100 -> 100 = -360 -> 360 degrees
            )
        )
        return cmd

    @property
    def connected(self):
        return datetime.datetime.now() - self._latest_rx < datetime.timedelta(seconds=0.5)

    @staticmethod
    def fab_cmd(ack, channel, project, _class, cmd, args):
        """ Assemble the bytes for a command.

            Most values from:
                https://github.com/Parrot-Developers/libARCommands/blob/master/Xml/common_commands.xml

            class_id:
                From "<class name="Common" id="[id]">" in Xml.

            idx:
                Index (zero-based) of the command in the Xml.

            https://github.com/Zepheus/ardrone3-pcap/blob/master/README.md
        """
        arr = bytearray()

        # Type: 2 = No ACK, 4 = ACK I think. See <..."buffer="NON_ACK"> in
        # XML.
        arr.append(ack)

        # Channel - 10 is for sending commands. 11 for photo trigger?
        arr.append(channel)

        # Sequence number - we update this at send time
        arr.append(0)

        # Message length - we update this at end.
        arr.append(0)

        # boilerplate?
        arr.append(0)
        arr.append(0)

        # Project ID - Jumping Sumo = 3
        arr.append(0)
        arr.append(project)

        # Class ID
        arr.append(_class)

        # Command index?
        arr.append(cmd)

        # Padded 0x00
        arr.append(0)

        # arguments, pre-packed using struct
        arr += args

        # update message length value
        arr[3] = len(arr)

        return arr

    def move(self, speed, turn=0, duration=1.0, block=True):
        """ Move in a manner, for a duration(seconds).
        """
        # Minimum duration is one 40th of a second.
        duration = max(1.0 / MOTOR_HZ, duration)

        # Enqueue the movement commands
        self._commands.extend(
            [self._move_cmd(speed, turn)
             for _
             in xrange(int(duration * MOTOR_HZ))]
        )

        if block:
            time.sleep(duration)

    def store_pic(self):
        """ Take a pic to internal storage - use FTP to retrieve if you want.
        """
        cmd = SumoController.fab_cmd(
            4,  # ACK
            11,  # Media channel ?
            3,  # Jumping Sumo project id = 3
            6,  # class = MediaRecord
            0,  # Command = Picture (offset 0)
            struct.pack(
                '<B',  # u8
                0,  # Internal storage = 0
            )
        )
        self._commands.append(cmd)

    def start_video_stream(self):
        """ Start the video streaming.
        """
        cmd = SumoController.fab_cmd(
            4,  # ACK
            11,  # Media channel ?
            3,  # Jumping Sumo project id = 3
            18,  # class = MediaStreaming
            0,  # Command = VideoEnable (Offset = 0)
            struct.pack(
                '<B',  # u8
                1,  # Enable = 1
            )
        )
        self._commands.append(cmd)

    def get_pic(self, retries=20):
        """ Return the last pic from the video stream.
        """
        try:
            return self._latest_pic.pop()
        except IndexError:
            # First one can take a minute
            if retries > 0:
                time.sleep(0.1)
                return self.get_pic(retries - 1)


if __name__ == '__main__':

    controller = SumoController()
    controller.move(50)
    controller.store_pic()
    controller.move(-50, duration=0.5)
    with open('output.jpg', 'wb') as f:
        f.write(controller.get_pic())
