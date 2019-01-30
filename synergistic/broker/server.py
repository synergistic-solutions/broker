import json
import uuid
import socket
import typing

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP

from synergistic.broker import encryption
from synergistic.broker.vars import Type


class Handler(socket.socket):

    server_uuid = str(uuid.uuid1(clock_seq=sum([ord(i) for i in Type.BROKER])))
    rsa_key = RSA.generate(1024)
    rsa_pub_key = rsa_key.publickey().export_key('DER')
    clients = {}

    def __init__(self, fd: int):

        socket.socket.__init__(self, family=socket.AF_INET, type=socket.SOCK_STREAM, fileno=fd)
        self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._closed = False
        self.subscriptions = []
        self.uuid = None
        self.name = None
        self.info = None
        self.state = 0
        # don't encrypt if it's on the loop back interface
        self.encrypt = self.getpeername()[0] != "127.0.0.1"
        self.aes_key = None
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
                cipher = PKCS1_OAEP.new(self.rsa_key)
                message = cipher.decrypt(message)
                self.aes_key = message
                self.state = 1

                # send a message to trigger the next client state
                self.send(b"{}")
                return

            message = encryption.decrypt(self.aes_key, message)

        if isinstance(message, bytes):
            message = message.decode('utf-8')

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self.close()
            return

        channel = data.get('channel', None)

        if not channel:
            return

        payload = data.get('payload', '')

        if channel == 'register':
            self.register(data)
        elif payload == 'subscribe':
            self.subscribe(channel)
        elif payload == 'unsubscribe':
            self.unsubscribe(channel)
        else:
            self.publish(data)

    def publish(self, data):
        channel = data['channel']
        channel_split = channel.split('.')

        wildcards = []
        for i in range(len(channel_split)):
            wildcards.append('.'.join(channel_split[:i] + ['*']))
        wildcards = [channel] + wildcards[::-1]

        specific_cache = json.dumps(data).encode('utf-8') + b'\r\n\r\n'

        for uuid, client in self.clients.items():
            matching = client.find_subscriptions(wildcards)
            if matching:
                try:
                    if matching == channel:
                        client.send(specific_cache, )
                    else:
                        client.send(json.dumps({**data, 'matched_channel': matching}).encode('utf-8') + b'\r\n\r\n')
                except OSError:
                    print("lost a client")

    def find_subscriptions(self, wildcards: list):
        for wildcard in wildcards:
            if wildcard in self.subscriptions:
                return wildcard
        return None

    def subscribe(self, channel):
        self.subscriptions.append(channel)

    def unsubscribe(self, channel):
        if channel in self.subscriptions:
            self.subscriptions.remove(channel)

    def register(self, data):
        self.info = data['payload']
        self.uuid = self.info['uuid']
        self.name = self.info['name']
        self.clients[self.uuid] = self

    def on_connect(self):
        if self.encrypt:
            self.send(self.rsa_pub_key)

    def send(self, data, **kwargs):
        if self.encrypt and self.state >= 1:
            data = encryption.encrypt(self.aes_key, data)
        data += b'\r\n\r\n'
        socket.socket.send(self, data, **kwargs)


class Server(socket.socket):

    def __init__(self, hostname: str = "0.0.0.0", port: int = 8891, handler: typing.Type[socket.socket] = Handler):
        socket.socket.__init__(self, family=socket.AF_INET, type=socket.SOCK_STREAM)
        self.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.bind((hostname, port))
        self.listen(5)
        self.handler = handler

    def on_connect(self):
        original_client_conn, address = self.accept()
        client_conn = self.handler(fd=original_client_conn.fileno())
        original_client_conn.detach()
        return client_conn
