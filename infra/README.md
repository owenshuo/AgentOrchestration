# Local Docker Stack

The default local stack starts the API and worker services without mounting the
host Docker socket. This keeps routine orchestration tasks from receiving
implicit control over the host container runtime.

Container build tasks that need Docker access must opt in to the isolated
builder profile:

```bash
docker compose -f infra/docker-compose.yml --profile builder up -d builder
```

The `builder` service is the only service allowed to mount
`/var/run/docker.sock`, and it is kept behind an explicit profile so developers
can decide when the host runtime boundary should be crossed. Prefer a remote or
rootless builder for shared environments.
