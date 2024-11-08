import logging
from copy import deepcopy
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import neo4j

from cartography.client.core.tx import load
from cartography.intel.github.util import fetch_all
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.github.users import GitHubOrganizationUserSchema, GitHubUnaffiliatedUserSchema
from cartography.stats import get_stats_client
from cartography.util import merge_module_sync_metadata
from cartography.util import run_cleanup_job
from cartography.util import timeit

logger = logging.getLogger(__name__)
stat_handler = get_stats_client(__name__)


GITHUB_ORG_USERS_PAGINATED_GRAPHQL = """
    query($login: String!, $cursor: String) {
    organization(login: $login)
        {
            url
            login
            membersWithRole(first:100, after: $cursor){
                edges {
                    hasTwoFactorEnabled
                    node {
                        url
                        login
                        name
                        isSiteAdmin
                        email
                        company
                    }
                    role
                }
                pageInfo{
                    endCursor
                    hasNextPage
                }
            }
        }
    }
    """

GITHUB_ENTERPRISE_OWNER_USERS_PAGINATED_GRAPHQL = """
    query($login: String!, $cursor: String) {
    organization(login: $login)
        {
            url
            login
            enterpriseOwners(first:100, after: $cursor){
                edges {
                    node {
                        url
                        login
                        name
                        isSiteAdmin
                        email
                        company
                    }
                    organizationRole
                }
                pageInfo{
                    endCursor
                    hasNextPage
                }
            }
        }
    }
    """


@timeit
def _get_users_raw(token: str, api_url: str, organization: str) -> Tuple[List[Dict], Dict]:
    """
    Retrieve a list of users from the given GitHub organization as described in
    https://docs.github.com/en/graphql/reference/objects#organizationmemberedge.
    :param token: The Github API token as string.
    :param api_url: The Github v4 API endpoint as string.
    :param organization: The name of the target Github organization as string.
    :return: A 2-tuple containing
        1. a list of dicts representing users and
        2. data on the owning GitHub organization
        see tests.data.github.users.GITHUB_USER_DATA for shape of both
    """
    users, org = fetch_all(
        token,
        api_url,
        organization,
        GITHUB_ORG_USERS_PAGINATED_GRAPHQL,
        'membersWithRole',
    )
    return users.edges, org


def _get_enterprise_owners_raw(token: str, api_url: str, organization: str) -> Tuple[List[Dict], Dict]:
    """
    Retrieve a list of enterprise owners from the given GitHub organization as described in
    https://docs.github.com/en/graphql/reference/objects#organizationenterpriseowneredge.
    :param token: The Github API token as string.
    :param api_url: The Github v4 API endpoint as string.
    :param organization: The name of the target Github organization as string.
    :return: A 2-tuple containing
        1. a list of dicts representing users who are enterprise owners
        3. data on the owning GitHub organization
        see tests.data.github.users.GITHUB_ENTERPRISE_OWNER_DATA for shape
    """
    owners, org = fetch_all(
        token,
        api_url,
        organization,
        GITHUB_ENTERPRISE_OWNER_USERS_PAGINATED_GRAPHQL,
        'enterpriseOwners',
    )
    return owners.edges, org

@timeit
def get_users(token: str, api_url: str, organization: str) -> Tuple[List[Dict], List[Dict], Dict]:
    """
    Retrieve all users:
    * organization users (users directly affiliated with an organization)
    * unaffiliated users (user who, for example, are enterprise owners but not members of the target organization).

    :param token: The Github API token as string.
    :param api_url: The Github v4 API endpoint as string.
    :param organization: The name of the target Github organization as string.
    :return: A 2-tuple containing
        1. a list of dicts representing users who are affiliated with the target org
           see tests.data.github.users.GITHUB_USER_DATA for shape
        2. a list of dicts representing users who are not affiliated (e.g. enterprise owners who are not also in
           the target org) — see tests.data.github.users.GITHUB_ENTERPRISE_OWNER_DATA for shape
        3. data on the owning GitHub organization
    """

    users, org = _get_users_raw(token, api_url, organization)
    users_dict = {}
    for user in users:
        processed_user = deepcopy(user['node'])
        processed_user['role'] = user['role']
        processed_user['hasTwoFactorEnabled'] = user['hasTwoFactorEnabled']
        processed_user['MEMBER_OF'] = org['url']
        users_dict[processed_user['url']] = processed_user

    owners, org = _get_enterprise_owners_raw(token, api_url, organization)
    owners_dict = {}
    for owner in owners:
        processed_owner = deepcopy(owner['node'])
        processed_owner['isEnterpriseOwner'] = True
        if owner['organizationRole'] == 'UNAFFILIATED':
            processed_owner['UNAFFILIATED'] = org['url']
        else:
            processed_owner['MEMBER_OF'] = org['url']
        owners_dict[processed_owner['url']] = processed_owner

    affiliated_users = [] # users affiliated with the target org
    for url, user in users_dict.items():
        user['isEnterpriseOwner'] = url in owners_dict
        affiliated_users.append(user)

    unaffiliated_users = [] # users not affiliated with the target org
    for url, owner in owners_dict.items():
        if url not in users_dict:
            unaffiliated_users.append(owner)

    return affiliated_users, unaffiliated_users, org


@timeit
def load_users(
    neo4j_session: neo4j.Session,
    node_schema: CartographyNodeSchema,
    user_data: List[Dict],
    org_data: Dict,
    update_tag: int,
) -> None:
    logger.info(f"Loading {len(user_data)} GitHub users to the graph")
    load(
        neo4j_session,
        node_schema,
        user_data,
        lastupdated=update_tag,
        org_url=org_data['url'],
    )


@timeit
def sync(
        neo4j_session: neo4j.Session,
        common_job_parameters: Dict,
        github_api_key: str,
        github_url: str,
        organization: str,
) -> None:
    logger.info("Syncing GitHub users")
    affiliated_user_data, unaffiliated_user_data, org_data = get_users(github_api_key, github_url, organization)
    load_users(neo4j_session, GitHubOrganizationUserSchema(), affiliated_user_data, org_data, common_job_parameters['UPDATE_TAG'])
    load_users(neo4j_session, GitHubUnaffiliatedUserSchema(), unaffiliated_user_data, org_data, common_job_parameters['UPDATE_TAG'])
    # no automated cleanup job because user has no sub_resource_relationship
    run_cleanup_job('github_users_cleanup.json', neo4j_session, common_job_parameters)
    merge_module_sync_metadata(
        neo4j_session,
        group_type='GitHubOrganization',
        group_id=org_data['url'],
        synced_type='GitHubOrganization',
        update_tag=common_job_parameters['UPDATE_TAG'],
        stat_handler=stat_handler,
    )
