from synergistic.poller import Poll
from synergistic.broker import server

if __name__ == "__main__":
    poller = Poll(catch_errors=False)

    broker_server = server.Server()

    poller.add_server(broker_server)

    poller.serve_forever()
