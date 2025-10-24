import json
import string
from enum import IntFlag, auto
from pathlib import Path
from typing import NamedTuple

import click
import httpx
from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
from loguru import logger
from pydantic import RootModel

from les_campai_connector import kc, uptime
from les_campai_connector.campai import CampaiClient, CampaiAuth, Contact
from les_campai_connector.config import Settings
from les_campai_connector.kc import (
    MinimalUserRepresentation,
    MinimalGroupRepresentation,
    MinimalUpdateUserRepresentation,
)


class MemberAction(IntFlag):
    CREATE = auto()
    ACTIVATE = auto()
    DEACTIVATE = auto()
    UPDATE_EMAIL = auto()
    UPDATE_FIRST_NAME = auto()
    UPDATE_LAST_NAME = auto()
    ADD_DEFAULT_GROUP = auto()
    REMOVE_ALL_GROUPS = auto()
    ADD_CAMPAI_ID = auto()
    REMOVE_NO_MEMBER_SUFFIX = auto()
    ADD_NO_MEMBER_SUFFIX = auto()
    SET_EMAIL_VALIDATED = auto()


NO_ACTION = 0
UPDATE_ACTIONS = ~(MemberAction.CREATE | MemberAction.ACTIVATE | MemberAction.DEACTIVATE)

ALLOWED_USERNAME_LETTERS = string.ascii_letters + string.digits + ".-_"


class SyncOperation(NamedTuple):
    kc_user: dict | None
    contact: Contact
    actions: MemberAction


@click.group()
def app():
    pass


def sanitize_username(username: str) -> str:
    sanitized_username = ""

    for c in username:
        # if it's an allowed letter, simply append
        if c in ALLOWED_USERNAME_LETTERS:
            sanitized_username += c
            continue

        # if it's a whitespace, sub with underscore
        if c == " ":
            sanitized_username += "_"

    return sanitized_username


def is_contact_active(contact: Contact):
    return contact.membership.status in ("willLeave", "isActive")


def get_keycloak_user_update_flags(
    contact: Contact,
    kc_user: MinimalUserRepresentation,
    kc_user_groups: list[MinimalGroupRepresentation],
    default_group: MinimalGroupRepresentation,
) -> MemberAction:
    actions = NO_ACTION

    # need to make email lowercase because keycloak automatically lowercases emails
    if kc_user.email != contact.communication.email.lower():
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


def _do_sync(settings: Settings, cache_to: Path | None, cache_from: Path | None):
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

    if cache_from is not None:
        with cache_from.open(mode="r", encoding="utf-8") as f:
            contacts = RootModel[list[Contact]].model_validate_json(f.read()).root
    else:
        email_to_contact: dict[str, Contact] = {}

        page_limit = 50
        page_skip = 0

        while True:
            next_contacts = campai.get_contacts(organisation, page={"limit": page_limit, "skip": page_skip})

            if len(next_contacts) == 0:
                break

            for contact in next_contacts:
                # skip contacts that aren't people
                if not contact.personal.is_person or contact.personal.is_organisation:
                    continue

                # check if a user with same e-mail has already been added to dict
                existing_contact = email_to_contact.get(str(contact.communication.email), None)

                if existing_contact is not None:
                    # if this is the case and the already existing contact has a lower membership number
                    # (meaning they joined earlier), leave the dict entry untouched and skip this contact.
                    # otherwise overwrite.
                    current_num = contact.membership.number_sort
                    existing_num = existing_contact.membership.number_sort

                    # for some reason the membership number is optional ...
                    if current_num is None or existing_num is None:
                        logger.warning(
                            f"Contacts {contact.id} and {existing_contact.id} have the same e-mail address "
                            f"({contact.communication.email}) but cannot be compared since they are missing "
                            "an account number, using existing contact"
                        )
                        continue

                    if contact.membership.number_sort > existing_contact.membership.number_sort:
                        continue

                # add user to dict (given that another user with a lower membership number isn't already present)
                email_to_contact[str(contact.communication.email)] = contact

            page_skip += page_limit

        contacts = list(email_to_contact.values())

        if cache_to is not None:
            with cache_to.open(mode="w", encoding="utf-8") as f:
                json.dump([c.model_dump(mode="json", by_alias=True) for c in contacts], f)

    logger.info(f"Found {len(contacts)} contacts")
    logger.info("Checking necessary sync operations for each contact")

    sync_queue: list[SyncOperation] = []

    for contact in contacts:
        # try to find by campai ID first
        kc_user = kc.find_user_by_campai_id(kc_admin, contact.id)

        # if that doesn't succeed, try to find by e-mail next
        if kc_user is None and contact.communication.email is not None:
            kc_user = kc.find_user_by_email(kc_admin, str(contact.communication.email))

        # check some pre-conditions
        is_active = is_contact_active(contact)
        is_keycloak_user_created = kc_user is not None

        member_actions = NO_ACTION

        # check if user needs to be created
        if is_active and not is_keycloak_user_created:
            member_actions |= (
                MemberAction.CREATE
                | MemberAction.ACTIVATE
                | MemberAction.UPDATE_FIRST_NAME
                | MemberAction.UPDATE_LAST_NAME
                | MemberAction.UPDATE_EMAIL
                | MemberAction.ADD_DEFAULT_GROUP
                | MemberAction.ADD_CAMPAI_ID
                | MemberAction.SET_EMAIL_VALIDATED
            )

        # check if user needs to be updated
        if is_keycloak_user_created:
            user = kc.must_parse_into_user(kc_user)
            user_groups = kc.must_parse_into_groups(kc_admin.get_user_groups(user.id))

            if is_active:
                # check if keycloak user is disabled
                if not user.enabled:
                    member_actions |= MemberAction.ACTIVATE

                # check if default group is missing
                if not default_group.id in [g.id for g in user_groups]:
                    member_actions |= MemberAction.ADD_DEFAULT_GROUP

                # check if username ends with _nomember
                if user.username.endswith(kc.NO_MEMBER_SUFFIX):
                    member_actions |= MemberAction.REMOVE_NO_MEMBER_SUFFIX
            else:
                # check if user is enabled
                if user.enabled:
                    member_actions |= MemberAction.DEACTIVATE

                # check if user has any group assignments
                if len(user_groups) > 0:
                    member_actions |= MemberAction.REMOVE_ALL_GROUPS

                # check if username doesn't end with _nomember
                if not user.username.endswith(kc.NO_MEMBER_SUFFIX):
                    member_actions |= MemberAction.ADD_NO_MEMBER_SUFFIX

            # these operations apply to all users whether they're activated
            # need to make email lowercase because keycloak automatically lowercases emails
            campai_email = None if contact.communication.email is None else str(contact.communication.email).lower()
            if user.email != campai_email:
                member_actions |= MemberAction.UPDATE_EMAIL

            if user.first_name != contact.personal.person_first_name:
                member_actions |= MemberAction.UPDATE_FIRST_NAME

            if user.last_name != contact.personal.person_last_name:
                member_actions |= MemberAction.UPDATE_LAST_NAME

            # check if campai user id attribute exists and matches
            if contact.id not in (user.attributes.get(kc.ATTRIBUTE_CAMPAI_ID) or []):
                member_actions |= MemberAction.ADD_CAMPAI_ID

            # check if verified e-mail is unset
            if not user.email_verified:
                member_actions |= MemberAction.SET_EMAIL_VALIDATED

        # skip users that don't need to be synced
        if member_actions != NO_ACTION:
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

    if len(sync_queue) == 0:
        click.secho("[*] ", bold=True, fg="green", nl=False)
        click.echo("No users need to be updated, we're all good :)")
        return

    if not settings.sync.auto_apply:
        click.confirm("Continue?", abort=True, prompt_suffix=" ")

    logger.info("Starting sync")

    for sync_op in sync_queue:
        contact = sync_op.contact
        actions = sync_op.actions

        # create a new empty user that will contain fields to be updated
        update_user = MinimalUpdateUserRepresentation()

        # first check if the user needs to created, in which case a username will be generated
        if MemberAction.CREATE in actions:
            if contact.communication.email is None:
                logger.warning(
                    f"User for {contact.personal.person_first_name} {contact.personal.person_last_name} "
                    f"cannot be created: email is missing"
                )
                continue

            # email is guaranteed to be valid so splitting and getting 0 index is safe
            contact_email_name = str(contact.communication.email).split("@")[0]

            # try to find a unique username
            base_username = sanitize_username(contact_email_name)
            username_idx = 0

            while True:
                username = base_username

                # if username_idx == 0, then we try the base username first with no modifications
                if username_idx > 0:
                    # otherwise add an increasing number to the username
                    username += str(username_idx)

                # if no user was found by this username, use it to create this user
                if kc.find_user_by_username(kc_admin, username) is None:
                    update_user.username = username
                    break

                username_idx += 1

        # if the user already exists, populate the username (will be necessary later)
        if sync_op.kc_user is not None:
            # TODO remove sanitize_username here as usernames in keycloak should already be safe
            update_user.username = sanitize_username(kc.must_parse_into_user(sync_op.kc_user).username)

        # set enabled if active
        if MemberAction.ACTIVATE in actions:
            update_user.enabled = True

        # set disabled if inactive
        if MemberAction.DEACTIVATE in actions:
            update_user.enabled = False

        # update e-mail
        if MemberAction.UPDATE_EMAIL in actions:
            # email could be None so this must be accounted for
            update_user.email = (
                str(contact.communication.email).lower() if contact.communication.email is not None else None
            )

        # update first name
        if MemberAction.UPDATE_FIRST_NAME in actions:
            update_user.first_name = contact.personal.person_first_name

        # update last name
        if MemberAction.UPDATE_LAST_NAME in actions:
            update_user.last_name = contact.personal.person_last_name

        # add campai id
        if MemberAction.ADD_CAMPAI_ID in actions:
            update_user.attributes = {kc.ATTRIBUTE_CAMPAI_ID: [contact.id]}

        # add _nomember suffix
        if MemberAction.ADD_NO_MEMBER_SUFFIX in actions:
            update_user.username = update_user.username + kc.NO_MEMBER_SUFFIX

        # remove _nomember suffix
        if MemberAction.REMOVE_NO_MEMBER_SUFFIX in actions:
            update_user.username = update_user.username.rstrip(kc.NO_MEMBER_SUFFIX)

        # set e-mail validated
        if MemberAction.SET_EMAIL_VALIDATED in actions:
            update_user.email_verified = True

        # now create or update user data, handle groups after this step
        if MemberAction.CREATE in actions:
            # by_alias => keys that keycloak can work with
            # exclude_none => ignore attributes not present in campai
            update_user_json = update_user.model_dump(mode="json", by_alias=True, exclude_none=True)
            user_id = kc_admin.create_user(update_user_json, exist_ok=False)
        else:
            # otherwise user already exists in keycloak and the model must be updated
            user_id = str(kc.must_parse_into_user(sync_op.kc_user).id)
            # update_user must receive the complete user representation so we're starting with that and
            # calling update() on it with update_user
            update_user_json = sync_op.kc_user
            # by_alias => keys that keycloak can work with
            # exclude_none => keep values that are None to remove values if they're no longer present in campai
            # exclude_unset => do not update fields that aren't affected by sync
            update_user_json_patch = update_user.model_dump(
                mode="json", by_alias=True, exclude_none=False, exclude_unset=True
            )
            update_user_json.update(update_user_json_patch)
            kc_admin.update_user(user_id, update_user_json)

        # now user_id is guaranteed to be set and can be reused for group assignment
        if MemberAction.ADD_DEFAULT_GROUP in actions:
            kc_admin.group_user_add(user_id, str(default_group.id))

        if MemberAction.REMOVE_ALL_GROUPS in actions:
            user_groups = kc.must_parse_into_groups(kc_admin.get_user_groups(user_id))

            for group in user_groups:
                kc_admin.group_user_remove(user_id, str(group.id))


@app.command()
@click.option("--cache-to", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--cache-from", type=click.Path(dir_okay=False, exists=True, path_type=Path))
def sync(cache_to: Path | None, cache_from: Path | None):
    settings = Settings()
    uptime_client = uptime.UptimeKumaClient(str(settings.sync.uptime_endpoint))

    # noinspection PyBroadException
    try:
        _do_sync(settings, cache_to, cache_from)
        uptime_client.up("Sync successful")
    except Exception:
        logger.exception("Sync failed")
        uptime_client.down("Sync failed")


if __name__ == "__main__":
    app()
