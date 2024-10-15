import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

import neo4j

from copy import deepcopy
from cartography.intel.github.util import fetch_all
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
def get_users(token: str, api_url: str, organization: str) -> Tuple[List[Dict], Dict]:
    """
    Retrieve a list of users from the given GitHub organization as described in
    https://docs.github.com/en/graphql/reference/objects#organizationmemberedge.
    :param token: The Github API token as string.
    :param api_url: The Github v4 API endpoint as string.
    :param organization: The name of the target Github organization as string.
    :return: A 2-tuple containing 1. a list of dicts representing users - see tests.data.github.users.GITHUB_USER_DATA
    for shape, and 2. data on the owning GitHub organization - see tests.data.github.users.GITHUB_ORG_DATA for shape.
    """
    users, org = fetch_all(
        token,
        api_url,
        organization,
        GITHUB_ORG_USERS_PAGINATED_GRAPHQL,
        'membersWithRole',
    )
    return users.edges, org

@timeit
def get_enterprise_owners(token: str, api_url: str, organization: str) -> Tuple[List[Dict], List[Dict], Dict]:
    """
        Retrieve a list of enterprise owners from the given GitHub organization as described in
        https://docs.github.com/en/graphql/reference/objects#organizationenterpriseowneredge.
        :param token: The Github API token as string.
        :param api_url: The Github v4 API endpoint as string.
        :param organization: The name of the target Github organization as string.
        :return: A 2-tuple containing
            1. a list of dicts representing enterprise owners who are also users in the organization - see tests.data.github.users.GITHUB_ENTERPRISE_OWNER_DATA for shape
            2. a list of dicts representing enterprise owners who are NOT users in the organization - see tests.data.github.users.GITHUB_ENTERPRISE_OWNER_DATA for shape
            3. data on the owning GitHub organization - see tests.data.github.users.GITHUB_ORG_DATA for shape.
        """
    owners, org = fetch_all(
        token,
        api_url,
        organization,
        GITHUB_ENTERPRISE_OWNER_USERS_PAGINATED_GRAPHQL,
        'enterpriseOwners',
    )

    unaffiliated_owners = []
    affiliated_owners = []
    for owner in owners.edges:
        if owner['organizationRole'] == 'UNAFFILIATED':
            unaffiliated_owners.append(owner)
        else:
            affiliated_owners.append(owner)
    return affiliated_owners, unaffiliated_owners, org


def _mark_users_as_enterprise_owners(
        user_data: List[Dict],
        user_org_data: Dict,
        affiliated_owner_data: List[Dict],
        owner_org_data: Dict,
) -> list[Dict]:
    """
    For every organization user, mark if they are also an enterprise owner.
    :param user_data: A list of dicts representing users - see tests.data.github.users.GITHUB_USER_DATA for shape.
    :param user_org_data: A dict representing the organization for the user_data - see tests.data.github.users.GITHUB_ORG_DATA for shape.
    :param affiliated_owner_data: A list of dicts representing affiliated enterprise owners - see tests.data.github.users.GITHUB_ENTERPRISE_OWNER_DATA for shape.
    :param owner_org_data: A dict representing the organization for the enterprise_owner_data - see tests.data.github.users.GITHUB_ORG_DATA for shape.
    :return: A new list of user_data dicts, updated with a new property, isEnterpriseOwner
    """

    # Guarding against accidental mixing of data from different orgs.  Since user data and owner data are queried
    # separately, there is at least a possibility of callers attempting to join data from different orgs.
    if user_org_data['url'] != owner_org_data['url']:
        raise ValueError(f"Organization URLs do not match: {user_org_data['url']} != {owner_org_data['url']}")
    if user_org_data['login'] != owner_org_data['login']:
        raise ValueError(f"Organization logins do not match: {user_org_data['login']} != {owner_org_data['login']}")

    result = []
    owner_urls = {entry['node']['url'] for entry in affiliated_owner_data}
    for user in user_data:
        user_copy = deepcopy(user)
        user_copy['node']['isEnterpriseOwner'] = user['node']['url'] in owner_urls
        result.append(user_copy)
    return result


@timeit
def load_organization_users(
    neo4j_session: neo4j.Session, user_data: List[Dict], org_data: Dict,
    update_tag: int,
) -> None:
    query = """
    MERGE (org:GitHubOrganization{id: $OrgUrl})
    ON CREATE SET org.firstseen = timestamp()
    SET org.username = $OrgLogin,
    org.lastupdated = $UpdateTag
    WITH org

    UNWIND $UserData as user

    MERGE (u:GitHubUser{id: user.node.url})
    ON CREATE SET u.firstseen = timestamp()
    SET u.fullname = user.node.name,
    u.username = user.node.login,
    u.has_2fa_enabled = user.hasTwoFactorEnabled,
    u.role = user.role,
    u.is_site_admin = user.node.isSiteAdmin,
    u.is_enterprise_owner = user.node.isEnterpriseOwner,
    u.email = user.node.email,
    u.company = user.node.company,
    u.lastupdated = $UpdateTag

    MERGE (u)-[r:MEMBER_OF]->(org)
    ON CREATE SET r.firstseen = timestamp()
    SET r.lastupdated = $UpdateTag
    """
    neo4j_session.run(
        query,
        OrgUrl=org_data['url'],
        OrgLogin=org_data['login'],
        UserData=user_data,
        UpdateTag=update_tag,
    )

@timeit
def load_unaffiliated_owners(
    neo4j_session: neo4j.Session, owner_data: List[Dict], org_data: Dict,
    update_tag: int,
) -> None:
    """
    The owner_data here represents users who are enterprise owners but are not in the target org.
    Note the subtle differences between what is loaded here and what in load_organization_users:
    1. The user-org relationship is set to UNAFFILIATED instead of MEMBER_OF.
    2. 'role' is not set: these users have no role in the organization (i.e. they are neither 'MEMBER' nor 'ADMIN').
    2. 'has_2fa_enabled' is not set: it is unavailable from the GraphQL query for these owners

    If the user does already exist in the graph (perhaps they are members of other orgs) then this merge will
    update the user's node but leave 'role' and 'has_2fa_enabled' untouched.
    """
    query = """
    MERGE (org:GitHubOrganization{id: $OrgUrl})
    ON CREATE SET org.firstseen = timestamp()
    SET org.username = $OrgLogin,
    org.lastupdated = $UpdateTag
    WITH org

    UNWIND $UserData as user

    MERGE (u:GitHubUser{id: user.node.url})
    ON CREATE SET u.firstseen = timestamp()
    SET u.fullname = user.node.name,
    u.username = user.node.login,
    u.is_site_admin = user.node.isSiteAdmin,
    u.is_enterprise_owner = TRUE,
    u.email = user.node.email,
    u.company = user.node.company,
    u.lastupdated = $UpdateTag

    MERGE (u)-[r:UNAFFILIATED]->(org)
    ON CREATE SET r.firstseen = timestamp()
    SET r.lastupdated = $UpdateTag
    """
    neo4j_session.run(
        query,
        OrgUrl=org_data['url'],
        OrgLogin=org_data['login'],
        UserData=owner_data,
        UpdateTag=update_tag,
    )

@timeit
def sync(
        neo4j_session: neo4j.Session,
        common_job_parameters: Dict[str, Any],
        github_api_key: str,
        github_url: str,
        organization: str,
) -> None:
    logger.info("Syncing GitHub users")
    user_data, user_org_data = get_users(github_api_key, github_url, organization)
    affiliated_owner_data, unaffiliated_owner_data, owner_org_data = get_enterprise_owners(github_api_key, github_url, organization)
    processed_user_data = _mark_users_as_enterprise_owners(user_data, user_org_data, affiliated_owner_data, owner_org_data)
    load_organization_users(neo4j_session, processed_user_data, user_org_data, common_job_parameters['UPDATE_TAG'])
    load_unaffiliated_owners(neo4j_session, unaffiliated_owner_data, owner_org_data, common_job_parameters['UPDATE_TAG'])
    run_cleanup_job('github_users_cleanup.json', neo4j_session, common_job_parameters)
    merge_module_sync_metadata(
        neo4j_session,
        group_type='GitHubOrganization',
        group_id=user_org_data['url'],
        synced_type='GitHubOrganization',
        update_tag=common_job_parameters['UPDATE_TAG'],
        stat_handler=stat_handler,
    )
