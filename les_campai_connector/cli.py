import json
import string
from enum import IntFlag, auto, Enum
from pathlib import Path
from typing import NamedTuple

import click
import httpx
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
from loguru import logger
from pydantic import RootModel

from les_campai_connector import kc
from les_campai_connector.campai import CampaiClient, CampaiAuth, Contact
from les_campai_connector.config import Settings
from les_campai_connector.kc import MinimalUserRepresentation, MinimalGroupRepresentation, \
    MinimalUpdateUserRepresentation, must_parse_into_user


class MemberAction(IntFlag):
    CREATE = auto()
    ACTIVATE = auto()
    DEACTIVATE = auto()
    UPDATE_EMAIL = auto()
    UPDATE_FIRST_NAME = auto()
    UPDATE_LAST_NAME = auto()
    ADD_DEFAULT_GROUP = auto()
    ADD_CAMPAI_ID = auto()


NO_ACTION = 0
UPDATE_ACTIONS = ~(MemberAction.CREATE | MemberAction.ACTIVATE | MemberAction.DEACTIVATE)

ALLOWED_USERNAME_LETTERS = string.ascii_letters + string.digits + "."

class SyncOperation(NamedTuple):
    kc_user: dict | None
    contact: Contact
    actions: MemberAction


@click.group()
def app():
    pass


def create_username_from_contact(contact: Contact) -> str:
    # it is assumed that email has been checked but better to be safe than sorry if logic changes eventually
    assert contact.communication.email is not None

    username = ""

    # noinspection PyTypeChecker
    for c in contact.communication.email:
        if c == "@":
            break

        if c not in ALLOWED_USERNAME_LETTERS:
            continue

        username += c

    return username


def is_contact_active(contact: Contact):
    return contact.membership.status in ("willLeave", "isActive")


def get_keycloak_user_update_flags(
    contact: Contact,
    kc_user: MinimalUserRepresentation,
    kc_user_groups: list[MinimalGroupRepresentation],
    default_group: MinimalGroupRepresentation,
) -> MemberAction:
    actions = NO_ACTION

    if kc_user.email != contact.communication.email:
        actions |= MemberAction.UPDATE_EMAIL

    if kc_user.first_name != contact.personal.person_first_name:
        actions |= MemberAction.UPDATE_FIRST_NAME

    if kc_user.last_name != contact.personal.person_last_name:
        actions |= MemberAction.UPDATE_LAST_NAME

    # check if campai user id attribute exists and matches
    if contact.id not in (kc_user.attributes.get(kc.ATTRIBUTE_CAMPAI_ID) or []):
        actions |= MemberAction.ADD_CAMPAI_ID

    # check if default group id exists in user groups
    if default_group.id not in [g.id for g in kc_user_groups]:
        actions |= MemberAction.ADD_DEFAULT_GROUP

    return actions


@app.command()
@click.option("--cache-to", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--cache-from", type=click.Path(dir_okay=False, exists=True, path_type=Path))
def sync(cache_to: Path | None, cache_from: Path | None):
    settings = Settings()

    logger.info(f"Using Campai API at {settings.campai.base_url}")

    campai = CampaiClient(
        client=httpx.Client(
            base_url=settings.campai.base_url, auth=CampaiAuth(settings.campai.api_key.get_secret_value())
        )
    )

    organisations = campai.get_organisations(filter={"name": settings.sync.organisation_name})

    if len(organisations) != 1:
        logger.error(
            f'Expected to find one organisation named "{settings.sync.organisation_name}", found {len(organisations)}'
        )
        exit(1)

    organisation = organisations.pop()
    logger.info(f'Found organisation named "{organisation.name}" with ID {organisation.id}')

    logger.info(f"Using Keycloak Admin API at {settings.keycloak.url} as {settings.keycloak.client_id}")

    kc_admin = KeycloakAdmin(
        connection=KeycloakOpenIDConnection(
            server_url=settings.keycloak.url,
            realm_name=settings.keycloak.realm_name,
            client_id=settings.keycloak.client_id,
            client_secret_key=settings.keycloak.client_secret.get_secret_value(),
        )
    )

    default_group_raw = kc.find_group_by_name(kc_admin, settings.sync.default_group_name)

    if default_group_raw is None:
        logger.error(f'Couldn\'t find Keycloak group named "{settings.sync.default_group_name}"')
        exit(1)

    default_group = kc.must_parse_into_group(default_group_raw)
    logger.info(f'Found group named "{default_group.name}" with ID {default_group.id}')
    logger.info("Fetching users from Campai")

    contacts: list[Contact] = []

    if cache_from is not None:
        with cache_from.open(mode="r", encoding="utf-8") as f:
            contacts = RootModel[list[Contact]].model_validate_json(f.read()).root
    else:
        page_limit = 50
        page_skip = 0

        while True:
            next_contacts = campai.get_contacts(organisation, page={"limit": page_limit, "skip": page_skip})

            if len(next_contacts) == 0:
                break

            contacts.extend(next_contacts)
            page_skip += page_limit

        if cache_to is not None:
            with cache_to.open(mode="w", encoding="utf-8") as f:
                json.dump([c.model_dump(mode="json", by_alias=True) for c in contacts], f)

    sync_queue: list[SyncOperation] = []

    for contact in contacts:
        # try to find by campai ID first
        kc_user = kc.find_user_by_campai_id(kc_admin, contact.id)

        # if that doesn't succeed, try to find by e-mail next
        if kc_user is None and contact.communication.email is not None:
            kc_user = kc.find_user_by_email(kc_admin, contact.communication.email)

        # check some pre-conditions
        is_active = is_contact_active(contact)
        is_keycloak_user_created = kc_user is not None

        member_actions = NO_ACTION

        # check if user needs to be created
        if is_active and not is_keycloak_user_created:
            member_actions |= MemberAction.CREATE

        # check if user needs to be updated
        if is_keycloak_user_created:
            user = kc.must_parse_into_user(kc_user)

            if user.enabled and not is_active:
                member_actions |= MemberAction.DEACTIVATE
            elif not user.enabled and is_active:
                member_actions |= MemberAction.ACTIVATE

            user_groups = kc.must_parse_into_groups(kc_admin.get_user_groups(user.id))
            member_actions |= get_keycloak_user_update_flags(contact, user, user_groups, default_group)

        sync_queue.append(SyncOperation(kc_user=kc_user, contact=contact, actions=member_actions))

    for sync_op in sync_queue:
        contact = sync_op.contact

        if sync_op.actions == NO_ACTION:
            continue

        if MemberAction.CREATE in sync_op.actions:
            click.secho("[*] ", bold=True, fg="blue", nl=False)
            click.echo(
                f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                f"(ID: {contact.id}, email: {contact.communication.email}) will be created"
            )

        if MemberAction.ACTIVATE in sync_op.actions:
            click.secho("[*] ", bold=True, fg="green", nl=False)
            click.echo(
                f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                f"(ID: {contact.id}, email: {contact.communication.email}) will be activated"
            )

        if MemberAction.DEACTIVATE in sync_op.actions:
            click.secho("[-] ", bold=True, fg="red", nl=False)
            click.echo(
                f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                f"(ID: {contact.id}, email: {contact.communication.email}) will be deactivated"
            )

        # check if any additional actions need to be taken
        selected_update_actions = sync_op.actions & UPDATE_ACTIONS

        if selected_update_actions != NO_ACTION:
            click.secho("[~] ", bold=True, fg="yellow", nl=False)
            click.echo(
                f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                f"(ID: {contact.id}, email: {contact.communication.email}) will be updated "
                f"({repr(selected_update_actions)})"
            )

    if not settings.sync.auto_apply:
        click.confirm("Continue?", abort=True, prompt_suffix=" ")

    logger.info("Starting sync")

    for sync_op in sync_queue:
        contact = sync_op.contact

        # same logic as above during confirmation
        if sync_op.actions == NO_ACTION:
            continue

        if MemberAction.CREATE in sync_op.actions:
            if contact.communication.email is None:
                logger.warning(
                    f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                    f"cannot be created: email is missing"
                )
                continue

            kc_username = create_username_from_contact(contact)
            kc_user = MinimalUpdateUserRepresentation(
                first_name=contact.personal.person_first_name,
                last_name=contact.personal.person_last_name,
                email=contact.communication.email,
                email_verified=True,
                username=kc_username,
                enabled=True,
                attributes={
                    kc.ATTRIBUTE_CAMPAI_ID: [contact.id]
                },
            ).model_dump(mode="json", by_alias=True, exclude_none=True)

            kc_user_id = kc_admin.create_user(kc_user, exist_ok=False)
            kc_admin.group_user_add(kc_user_id, str(default_group.id))

            logger.info(
                f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                f"created (ID: {kc_user_id}, username: {kc_username})"
            )
            continue

        if MemberAction.ACTIVATE in sync_op.actions:
            user = kc.must_parse_into_user(sync_op.kc_user)

            # re-enable user and remove _nomember suffix, if exists
            user.enabled = True
            user.username = user.username.rstrip(kc.NO_MEMBER_SUFFIX)

            kc_admin.update_user(user.id, user.model_dump(mode="json", by_alias=True))
            logger.info(
                f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                f"activated"
            )
            continue


if __name__ == "__main__":
    app()
