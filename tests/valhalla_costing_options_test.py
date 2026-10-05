#!/usr/bin/env python3

import argparse
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit


class RoutingHandler(BaseHTTPRequestHandler):
    backend = "valhalla"
    requests = []

    def log_message(self, *_args):
        pass

    def do_GET(self):  # noqa: N802
        request_path = urlsplit(self.path)
        RoutingHandler.requests.append(request_path.path)

        if self.backend == "valhalla":
            query = request_path.query
            assert query.startswith("json=")
            request = json.loads(unquote(query[5:]))
            RoutingHandler.requests[-1] = request

            if request_path.path.endswith("sources_to_targets"):
                size = len(request["sources"])
                response = {
                    "sources_to_targets": [
                        [
                            {"time": 0 if i == j else 1,
                             "distance": 0.0 if i == j else 0.001}
                            for j in range(size)
                        ]
                        for i in range(size)
                    ]
                }
            else:
                size = len(request["locations"])
                response = {
                    "trip": {
                        "status": 0,
                        "status_message": "",
                        "legs": [
                            {
                                "summary": {"time": 1, "length": 0.001},
                                "shape": "??",
                            }
                            for _ in range(size - 1)
                        ],
                    }
                }
        else:
            if request_path.path.find("/table/v1/") != -1:
                size = len(request_path.path.split("/")[-1].split(";"))
                response = {
                    "code": "Ok",
                    "durations": [[0 if i == j else 1 for j in range(size)]
                                   for i in range(size)],
                    "distances": [[0 if i == j else 1 for j in range(size)]
                                   for i in range(size)],
                }
            else:
                response = {
                    "code": "Ok",
                    "routes": [{"duration": 1, "distance": 1,
                                "geometry": "??", "legs": []}],
                }

        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def run_vroom(binary, router, profile, payload, geometry=False):
    RoutingHandler.backend = router
    RoutingHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), RoutingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    command = [
        binary,
        "--router", router,
        "--host", f"{profile}:127.0.0.1",
        "--port", f"{profile}:{server.server_port}",
        "--threads", "1",
        "--explore", "0",
    ]
    if geometry:
        command.append("--geometry")

    result = subprocess.run(command,
                            input=json.dumps(payload),
                            text=True,
                            capture_output=True,
                            check=False)
    server.shutdown()
    thread.join()
    assert result.returncode == 0, result.stderr
    return RoutingHandler.requests


def base_input(profile):
    return {
        "vehicles": [{
            "id": 1,
            "profile": profile,
            "start": [0.0, 0.0],
            "end": [0.01, 0.01],
        }],
        "jobs": [{"id": 1, "location": [0.005, 0.005]}],
    }


def assert_valhalla_options(binary, profile, costing_options):
    payload = base_input(profile)
    payload["costing_options"] = costing_options
    requests = run_vroom(binary, "valhalla", profile, payload, geometry=True)
    valhalla_requests = [request for request in requests
                         if isinstance(request, dict)]
    assert any("sources" in request for request in valhalla_requests)
    assert any("locations" in request for request in valhalla_requests)
    for request in valhalla_requests:
        assert request["costing_options"] == costing_options


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vroom", required=True)
    args = parser.parse_args()

    no_options_requests = run_vroom(
        args.vroom, "valhalla", "auto", base_input("auto"), geometry=True)
    for request in no_options_requests:
        if isinstance(request, dict):
            assert "costing_options" not in request

    assert_valhalla_options(
        args.vroom,
        "pedestrian",
        {"pedestrian": {"exclude_ferries": True}},
    )
    assert_valhalla_options(
        args.vroom,
        "auto",
        {"auto": {"exclude_tolls": True}},
    )

    osrm_payload = base_input("auto")
    osrm_payload["costing_options"] = {"auto": {"exclude_tolls": True}}
    run_vroom(args.vroom, "osrm", "auto", osrm_payload)


if __name__ == "__main__":
    main()
