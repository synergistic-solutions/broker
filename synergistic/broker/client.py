import os
import pwd
import json
import uuid
import socket
import typing
import platform

from Crypto import Random
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP


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
        self.aes_key = Random.new().read(16)
        self.queue = []

    def on_receive(self):
        message = self.recv(4096*16)
        if not message:
            self.close()
            return
        buffer = message
        for message in buffer.split(b'\r\n\r\n'):
            if message:
                self.handle(message)

    def handle(self, message):
        if self.state == 0:
            cipher = PKCS1_OAEP.new(RSA.import_key(message))
            ciphertext = cipher.encrypt(self.aes_key) + b'\r\n\r\n'
            super().send(ciphertext)
            self.state = 1
            return

        # should be encrypted

        iv = message[:AES.block_size]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        message = cipher.decrypt(message[AES.block_size:])
        message = self._unpad(message)

        if self.state == 1:

            self.register()

            for item in self.queue:
                self.send(item)
            self.queue = []
            self.state = 2
            return

        # decoded by the unpad
        # message = message.decode('utf-8')

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
        pass

    def send(self, data, **kwargs):
        if self.state == 0:
            self.queue.append(data)
            return

        data = self._pad(data)
        iv = Random.new().read(AES.block_size)
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        data = iv + cipher.encrypt(data) + b'\r\n\r\n'
        super().send(data, **kwargs)

    @staticmethod
    def _pad(s):
        return s + (AES.block_size - len(s) % AES.block_size) * chr(AES.block_size - len(s) % AES.block_size).encode('utf-8')

    @staticmethod
    def _unpad(s):
        return s[:-ord(s[len(s) - 1:])]

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
