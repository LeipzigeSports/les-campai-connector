#!/usr/bin/env bash
pg_restore -d keycloakdb -Fc -U admin --no-acl --no-owner /tmp/dump/keycloakdb
