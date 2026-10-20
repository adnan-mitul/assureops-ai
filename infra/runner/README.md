# Disposable runner image

`RUNNER_MODE=container` makes the worker start one container per test step:

```
docker run --rm -i --network assureops-runner --memory 256m --cpus 0.5 --pids-limit 64 --read-only \
  --tmpfs /tmp:rw,size=16m --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 assureops-runner:local
```

The capsule (one frozen test, the frozen release manifest, the connection settings and that connection's
actor credentials) arrives on stdin; nothing is written to disk and the container is removed afterwards.
The image contains only the connectors package and the pure matcher module: no database driver, broker
client, object-store SDK or platform key.

Build: `docker build -f infra/runner/Dockerfile -t assureops-runner:local .`
Network: `docker network create assureops-runner`. On hosted infrastructure, attach this network to an
egress firewall or proxy that only allows the registered target origins; inside the runner every request
is additionally pinned to the connection origin, redirects are refused and private/metadata addresses are
denied unless `ALLOW_PRIVATE_TARGETS` is set for an authorized private network.

Local development uses `RUNNER_MODE=subprocess` (`python -I` with a scrubbed environment), because the
supplied labs listen on the host loopback, which a container cannot reach without a private-network address.
