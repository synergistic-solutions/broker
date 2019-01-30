import os
import pwd
import json
import uuid
import socket
import typing
import platform

from Crypto import Random
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP

from synergistic.broker import encryption


class Client(socket.socket):

    def __init__(self, hostname: str, port: int, name: str):

        socket.socket.__init__(self)
        self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._closed = False
        self.connect((hostname, port))

        # generates a uuid that contains the mac address and the name of service
        self.uuid = str(uuid.uuid1(clock_seq=sum([ord(i) for i in name])))
        self.name = name
        self.subscriptions = {}
        self.callbacks = {}
        self.state = 0
        # don't encrypt if it's on the loop back interface
        self.encrypt = self.getpeername()[0] != "127.0.0.1"
        self.aes_key = Random.new().read(16)
        self.queue = []
        self.buffer = b''

    def on_receive(self):
        message = self.recv(4096*16)
        if not message:
            self.close()
            return
        message = self.buffer + message

        buffer = message.split(b'\r\n\r\n')

        for message in buffer[:-1]:
            if message:
                self.handle(message)

        self.buffer = buffer[-1]

    def handle(self, message):
        if self.encrypt:
            if self.state == 0:
                cipher = PKCS1_OAEP.new(RSA.import_key(message))
                ciphertext = cipher.encrypt(self.aes_key) + b'\r\n\r\n'
                self.state = 1  # allow the send on the next line to be sent normally
                self.send(ciphertext)
                self.state = 2
                return

            elif self.state == 2:
                self.register()

                for item in self.queue:
                    self.send(item)
                self.queue = []

                self.state = 3
                return

            message = encryption.decrypt(self.aes_key, message)

        if isinstance(message, bytes):
            message = message.decode('utf-8')

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            print("error decoding")
            return

        channel = data.get('matched_channel', data.get('channel', None))
        if not channel:
            return

        subscription = self.subscriptions.get(channel, None)
        if subscription:
            func, limit = subscription
            func(channel, data['msg_id'], data.get('payload', None))
            if limit > 1:
                self.subscriptions[channel][1] -= 1
            elif limit == 1:
                self.unsubscribe(channel)

    def on_connect(self):
        if not self.encrypt:
            self.register()

    def send(self, data, **kwargs):
        if self.encrypt:
            if self.state == 0:
                self.queue.append(data)
                return
            elif self.state >= 2:
                data = encryption.encrypt(self.aes_key, data)

        data += b'\r\n\r\n'
        socket.socket.send(self, data, **kwargs)

    def register(self):
        data = {
            'uuid': self.uuid,
            'name': self.name,
            'os': platform.system(),
            'hostname': socket.gethostname(),
            'user': pwd.getpwuid(os.getuid()).pw_name,
            'mac': uuid.getnode(),
        }
        self.publish("register", data)

    def subscribe(self, channel: str, callback: typing.Callable, limit: int = 0):
        self.subscriptions[channel] = [callback, limit]
        self.publish(channel, 'subscribe')

    def unsubscribe(self, channel):
        del self.subscriptions[channel]
        self.publish(channel, 'unsubscribe')

    def respond(self, msg_id, payload):
        self.publish('__' + msg_id, payload)

    def publish(self, channel: str, payload, callback: typing.Callable = None):
        msg_id = str(uuid.uuid4())

        if callback:
            self.subscribe('__' + msg_id, callback, 1)

        data = {
            'channel': channel,
            'msg_id': msg_id,
            'payload': payload
        }
        self.send(json.dumps(data).encode('utf-8') + b'\r\n\r\n', )
