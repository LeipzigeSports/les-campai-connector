LES Campai Connector is a Python application that syncs membership information from Campai to Keycloak.
It keeps personal information in Keycloak up-to-date, modifies group membership and account state depending on membership status.

# Installation

The application is shipped as a container image.
It can be pulled with the following command.

```
docker pull ghcr.io/leipzigesports/les-campai-connector:0.1.0
```

# Setup

The application requires a Campai API key and a Keycloak service account.

Currently, the new Campai API is not supported since it doesn't export member information.
[Follow the steps on the documentation for the old API on how to create an API key](https://docs2.campai.com/).

In Keycloak, open the admin panel and select the realm in which accounts are meant to be managed.
Click on "Clients" in the right sidebar, then "Create client".
Enter the following settings on the client wizard.

1. General settings
    - Client type: OpenID Connect
    - Client ID: les-campai-connector
2. Capability config
    - Client authentication: on
    - Authorization: on
3. Login settings
    - Keep everything empty

After clicking "Save", you are forwarded to the newly created client.
Switch to the "Service account roles" tab.
Click "Assign role", then "Client roles".
Search for the *view-users*, *query-users*, *manage-users*, *view-groups* and *query-groups* roles and apply them.
Finally, switch to the "Credentials" tab and copy the client secret for the 

# Configuration

The application is configured with environment variables.

| Variable                   | Description                                                |
|:---------------------------|:-----------------------------------------------------------|
| `KEYCLOAK__URL`            | Keycloak base URL                                          |
| `KEYCLOAK__REALM_NAME`     | Realm where users are managed                              |
| `KEYCLOAK__CLIENT_ID`      | Application client ID                                      |
| `KEYCLOAK__CLIENT_SECRET`  | Application client secret                                  |
| `CAMPAI__API_KEY`          | Campai API Key                                             |
| `CAMPAI__BASE_URL`         | Campai base URL                                            |
| `SYNC__ORGANISATION_NAME`  | Name of Campai organisation to get members from            |
| `SYNC__DEFAULT_GROUP_NAME` | Name of default Keycloak group to assign to active members |
| `SYNC__AUTO_APPLY`         | Flag to apply sync operations without confirmation         |
| `SYNC__UPTIME_ENDPOINT`    | Passive Uptime Kuma endpoint for monitoring                |
| `SYNC__UPTIME_ENABLE`      | Flag to report sync status to Uptime Kuma endpoint         |

A suitable way to configure the application would be with a Compose file.

```yaml
services:
  les-campai-connector:
    image: ghcr.io/leipzigesports/les-campai-connector:0.1.0
    environment:
      - KEYCLOAK__URL=http://localhost:8080
      - KEYCLOAK__REALM_NAME=lesev
      - KEYCLOAK__CLIENT_ID=les-campai-connector
      - KEYCLOAK__CLIENT_SECRET=xxxxx
      - CAMPAI__API_KEY=xxxxx
      - CAMPAI__BASE_URL=https://api.campai.com
      - SYNC__ORGANISATION_NAME=Leipzig eSports e.V.
      - SYNC__DEFAULT_GROUP_NAME=Mitglied
      - SYNC__AUTO_APPLY=1
      - SYNC__UPTIME_ENDPOINT=http://localhost:8888/api/push/xxxxx
      - SYNC__UPTIME_ENABLE=1
    volumes:
      - ./logs:/app/logs
 ```

# License

Apache 2.0
