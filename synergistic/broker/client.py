import os
import pwd
import json
import uuid
import socket
import typing
import platform


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

    def on_receive(self):
        message = self.recv(4096*16)
        if not message:
            self.close()
            return
        buffer = message.decode('utf-8')
        for message in buffer.split('\r\n'):
            if message:
                self.handle(message)

    def handle(self, message):
        try:
            data = json.loads(message)
        except:
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
        self.send(json.dumps(data).encode('utf-8') + b'\r\n')
