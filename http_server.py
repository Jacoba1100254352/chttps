import argparse
import asyncio
import logging
import os
import socket
import time
from queue import Queue
from threading import Thread


# Section 1: ThreadPool Implementation
class ThreadPool:
    def __init__(self, num_threads):
        self.tasks = Queue()
        self.workers = [Worker(self.tasks) for _ in range(num_threads)]

    def add_task(self, func, *task_args, **kwargs):
        self.tasks.put((func, task_args, kwargs))

    def wait_completion(self):
        self.tasks.join()

    def stop_all(self):
        for _ in self.workers:
            self.tasks.put(None)
        for worker in self.workers:
            worker.join()


class Worker(Thread):
    def __init__(self, tasks):
        super().__init__(daemon=True)
        self.tasks = tasks
        self.start()

    def run(self):
        while True:
            task = self.tasks.get()
            if task is None:
                break
            func, task_args, kwargs = task
            try:
                func(*task_args, **kwargs)
            except Exception as e:
                logging.exception(f"Exception in worker thread: {e}")
            finally:
                self.tasks.task_done()


# Section 2: Synchronous Server Code
def handle_client_request_sync(conn, addr, root_folder, delay):
    """
    Handles the client request in a synchronous manner.

    :param conn: The connection object.
    :param addr: The address of the client.
    :param root_folder: The root folder for server files.
    :param delay: Whether to introduce a delay before processing requests (for debugging).
    """
    if delay:
        time.sleep(5)  # Sleep for 5 seconds, for example

    try:
        # Read and process the request
        request = conn.recv(1024).decode()

        # Parse the request and generate an appropriate response
        response = generate_response(request, root_folder)
        conn.sendall(response)
    except ConnectionResetError:
        logging.warning(f"Connection reset by client {addr}.")
    except Exception as e:
        logging.exception(f"Error handling request from {addr}: {e}")
    finally:
        conn.close()


def run_sync(port, root_folder, delay, concurrency):
    server_socket = setup_server_socket(port)
    pool = ThreadPool(10) if concurrency == "thread-pool" else None
    threads = []  # Add this line to keep track of threads

    try:
        while True:
            conn, addr = server_socket.accept()
            if concurrency == "thread":
                client_thread = Thread(
                    target=handle_client_request_sync,
                    args=(conn, addr, root_folder, delay),
                )
                client_thread.start()
                threads.append(client_thread)  # Keep track of the thread
            elif concurrency == "thread-pool":
                pool.add_task(
                    handle_client_request_sync, conn, addr, root_folder, delay
                )
    except KeyboardInterrupt:
        logging.info("Shutting down server")
        if concurrency == "thread-pool":
            pool.stop_all()
        elif concurrency == "thread":
            for thread in threads:
                thread.join()
        server_socket.close()


def generate_response(request, root_folder):
    try:
        lines = request.split("\n")
        if len(lines) > 0 and len(lines[0].split()) >= 3:
            method, filename, _ = lines[0].split()
        else:
            return "HTTP/1.0 400 Bad Request\r\n\r\nBad Request".encode()

        # Only handle GET requests, return 405 for other methods
        if method != "GET":
            return "HTTP/1.0 405 Method Not Allowed\r\n\r\nMethod Not Allowed".encode()

        if filename == "/":
            filename = "/index.html"

        filepath = os.path.join(root_folder, filename.lstrip("/"))
        with open(filepath, "rb") as f:
            content = f.read()
            response_headers = (
                "HTTP/1.0 200 OK\r\n" f"Content-Length: {len(content)}\r\n\r\n"
            )
            return response_headers.encode() + content
    except FileNotFoundError:
        return "HTTP/1.0 404 Not Found\r\n\r\nFile Not Found".encode()
    except Exception as e:
        logging.exception(f"Error generating response: {e}")
        return (
            "HTTP/1.0 500 Internal Server Error\r\n\r\nInternal Server Error".encode()
        )


# Section 3: Asynchronous Server Code
async def handle_client_request_async(reader, writer, root_folder, delay):
    """
    Handles the client request in an asynchronous manner.

    :param reader: The asyncio StreamReader object.
    :param writer: The asyncio StreamWriter object.
    :param root_folder: The root folder for server files.
    :param delay: Whether to introduce a delay before processing requests (for debugging).
    """
    if delay:
        await asyncio.sleep(5)  # Sleep for 5 seconds, for example

    try:
        # Read and process the request here
        request = await reader.read(1024)
        request_str = request.decode()

        # Parse the request and generate an appropriate response
        response = generate_response(request_str, root_folder)
        writer.write(response)
        await writer.drain()
    except ConnectionResetError:
        addr = writer.get_extra_info("peername")
        logging.warning(f"Connection reset by client {addr}.")
    except Exception as e:
        logging.exception(f"Error handling request: {e}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionResetError:
            pass  # Client already closed the connection


async def run_async(port, root_folder, delay):
    """
    Asynchronously runs the HTTP server and listens for incoming client requests.

    :param port: The port number to listen on.
    :param root_folder: The root folder from which to serve files.
    :param delay: If True, introduces a delay before processing each request for debugging purposes.
    :return: None
    """
    server = await asyncio.start_server(
        lambda r, w: handle_client_request_async(r, w, root_folder, delay), "", port
    )

    logging.info(f"Serving on {port}")
    async with server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            logging.info("Server was cancelled, shutting down...")
        except KeyboardInterrupt:  # Handle Ctrl+C for async server
            logging.info("Shutting down async server")
            server.close()
            await server.wait_closed()


def setup_server_socket(port):
    """
    Set up the HTTP server socket.

    :param port: The port number to listen on.

    :return: The server socket
    """
    # Set up the server socket and return it
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("", port))
    server_socket.listen()

    logging.info(f"Listening on port {port}")

    return server_socket


def run(port, root_folder, delay, concurrency):
    """
    Runs the HTTP server and listens for incoming client requests.

    :param port: The port number to listen on.
    :param root_folder: The root folder for server files.
    :param delay: Whether to introduce a delay before processing requests (for debugging).
    :param concurrency: The concurrency model to use ('thread', 'thread-pool', or 'async').

    :return: None
    """
    if concurrency == "async":
        asyncio.run(run_async(port, root_folder, delay))
    else:
        run_sync(port, root_folder, delay, concurrency)


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Simple HTTP Server")
    parser.add_argument(
        "-p", "--port", required=False, type=int, default=8085, help="port to bind to"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        required=False,
        action="store_true",
        help="turn on debugging output",
    )
    parser.add_argument(
        "-d",
        "--delay",
        required=False,
        action="store_true",
        help="add a delay for debugging purposes",
    )

    parser.add_argument(
        "-f",
        "--folder",
        required=False,
        default="./www",
        help="folder from where to serve from",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        required=False,
        choices=["thread", "thread-pool", "async"],
        default="async",
        help="concurrency methodology to use",
    )

    args = parser.parse_args()

    # Setup logging based on verbosity
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(format="%(levelname)s:%(message)s", level=level)
    logging.debug(args)

    # Ensure root folder path is consistent
    if args.folder[-1] != "/":
        args.folder += "/"

    # Start the HTTP server
    run(args.port, args.folder, args.delay, args.concurrency)
