import json
import os

import httpx
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
from unidecode import unidecode
from dotenv import load_dotenv
from loguru import logger

load_dotenv()
api_key = os.getenv("API_KEY")
client_secret = os.getenv("CLIENT_SECRET")
keycloak_password = os.getenv("KEYCLOAK_PASS")
organisation_id = os.getenv("ORGA_ID")

logger.add("on_offboarding.log", retention="7 days")

keycloak_connection = KeycloakOpenIDConnection(
    server_url="http://192.168.178.72:8080",
    username="admin",
    password=keycloak_password,
    realm_name="master",
    client_id="admin-cli",
    client_secret_key=client_secret,
    verify=True
)

keycloak_admin = KeycloakAdmin(connection=keycloak_connection)

base_url = "https://api.campai.com/"
user_count = f"{base_url}contacts?mode=count&organisation={organisation_id}"

header = {
    "Authorization": api_key,
}

response = httpx.get(user_count, headers=header)

user_url = f"{base_url}contacts?organisation={organisation_id}&mode=query"
user = httpx.get(user_url, headers=header)
data = json.loads(user.text)
for i in range(50):
    email_check = keycloak_admin.get_users({"email" : data[i]["mergeTags"]["email"]})
    if email_check:
        logger.info(f"Nutzer {data[i]["mergeTags"]["email"]} existiert schon")
    else:
        username = data[i]["mergeTags"]["email"]
        username = str(username).split("@", 1)[0]
        username = username.lower()
        translate = str.maketrans({
            "ä" : "ae",
            "ö" : "oe",
            "ü" : "ue"
        })
        username = username.translate(translate)
        username = unidecode(username)
        new_user = keycloak_admin.create_user(
            {"email": data[i]["mergeTags"]["email"],
            "username": username,
            "enabled": True,
            "firstName": data[i]["mergeTags"]["personFirstName"],
            "lastName": data[i]["mergeTags"]["personLastName"],
            "emailVerified": True},
            exist_ok=False
            )
        logger.info(f"Nutzer {username} wurde erstellt")

        new_user_id = keycloak_admin.get_user_id(username)
        groups = keycloak_admin.get_groups()

        group_id = None
        for i in groups:
            if i["name"] == "Mitglied":
                group_id = i["id"]
                break
        
        if group_id:
            keycloak_admin.group_user_add(new_user_id, group_id)
            logger.info(f"Dem Nutzer {username} wurde der Gruppe Mitglied hinzugefügt")
        else:
            logger.info(f"Dem Nutzer {username} konnte keine Gruppe hinzugefügt werden")