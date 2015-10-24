import interface
import multiprocessing
import threading
import time
import xmlrpclib
import SimpleXMLRPCServer


def start_server(funcs, host='', port=8000):
    """ XMLRPC server.

        Pass {'name': func, ...} dict.
    """
    server = SimpleXMLRPCServer.SimpleXMLRPCServer((host, port), allow_none=True)
    server.logRequests = False
    for (name, func) in funcs.items():
        server.register_function(func, name)
    server.serve_forever()


def proxy_move(sumo):
    """ Calls the 'move' function in non-blocking mode.
    """
    def non_block_move(speed, turn, duration):
        sumo.move(speed, turn, duration, block=False)
    return non_block_move


def proxy_pic(sumo):
    """ Calls the 'get_pic' function and returns a Binary result.

        Returns None if no pic.
    """
    def get_pic_binary():
        pic = sumo.get_pic(retries=0)
        return pic if pic is None else xmlrpclib.Binary(pic)
    return get_pic_binary


def main(uhoh_event):
    """ XMLRPC server for sumopy.

        Allows multiple clients to manage a single Sumo.
    """
    try:
        # None-blocking, but starts some threads.
        sumo = interface.SumoController()

        # If the sumo looses connection, we try to reconnect.
        def connected_watchdog():
            while True:
                time.sleep(0.5)
                if not sumo.connected:
                    uhoh_event.set()
                    break
        threading.Thread(target=connected_watchdog).start()

        # Blocking - exceptions will stop though.
        start_server({
            'move': proxy_move(sumo),
            'pic': proxy_pic(sumo),
        })

    except Exception:
        uhoh_event.set()

    # If the server is un-blocked, and we're here, err, it broke.
    uhoh_event.set()


def start():
    while True:
        uhoh_event = multiprocessing.Event()
        proc = multiprocessing.Process(target=main, args=(uhoh_event,))
        proc.start()
        uhoh_event.wait()
        proc.terminate()
        print 'Restarting...'
        time.sleep(5)


if __name__ == '__main__':
    start()
