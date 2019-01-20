from synergistic.poller import Poll
from synergistic.broker import server

if __name__ == "__main__":
    poller = Poll(catch_errors=False)

    broker_server = server.Server("127.0.0.1", 8891, handler=server.Handler)

    poller.add_server(broker_server)

    poller.serve_forever()
