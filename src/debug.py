import time

from toomanythreads import ThreadedServer

from fastcloudflare import Gateway

if __name__ == "__main__":
    app = ThreadedServer()
    g = Gateway(app)
    g.launch()
    time.sleep(500)
