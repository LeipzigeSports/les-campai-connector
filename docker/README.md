## Local development setup

1. Grab a Postgres dump from backup archive
2. Copy Postgres dump into [dump directory](./dump)
3. Rename file to `keycloakdb`
4. Change permissions with `chmod go+r keycloakdb` (otherwise Postgres won't start)
5. Run `docker compose up`
6. Run `docker compose up` again (because Keycloak starts up before Postgres is ready)
