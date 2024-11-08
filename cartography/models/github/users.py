from dataclasses import dataclass
from typing import Optional

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.relationships import CartographyRelProperties
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import TargetNodeMatcher

"""
RE: Tenant relationship between GitHubUser and GitHubOrganization

Note this relationship is implemented via 'other_relationships' and not via the 'sub_resource_relationship' 
as might be expected.

The 'sub_resource_relationship' typically describes the relationship of a node to its tenant (the org, project, or
other resource to which other nodes belong).  An assumption of that relationship is that if the tenant goes
away, all nodes related to it should be cleaned up.

In GitHub, though the GitHubUser's tenant seems to be GitHubOrganization, users actually exist independently.  There
is a concept of 'UNAFFILIATED' users, like Enterprise Owners who are related to an org even if they are not direct
members of it.  You would not want them to be cleaned up, if an org goes away, and you could want them in your graph
even if they are not members of any org in the enterprise.

To allow for this in the schema, this relationship is treated as any other node-to-node relationship, via
'other_relationships', instead of as the typical 'sub_resource_relationship'.

RE: GitHubOrganizationUserSchema vs GitHubUnaffiliatedUserSchema

As noted above, there are implicitly two types of users, those that are part of, or affiliated, to a target
GitHubOrganization, and those thare are not part, or unaffiliated.   Both are represented as GitHubUser nodes,
but there are two schemas below to allow for some differences between them, e.g., unaffiliated lack these properties:
  * the 'role' property, because unaffiliated have no 'role' in the target org
  * the 'has_2fa_enabled' property, because the GitHub api does not return it, for these users
The main importance of having two schemas is to allow the two sets of users to be loaded separately.  If we are loading
an unaffiliated user, but the user already exists in the graph (perhaps they are members of another GitHub orgs for
example), then loading the unaffiliated user will not blank out the 'role' and 'has_2fa_enabled' properties.

See:
* https://docs.github.com/en/graphql/reference/enums#roleinorganization
* https://docs.github.com/en/enterprise-cloud@latest/admin/managing-accounts-and-repositories/managing-users-in-your-enterprise/roles-in-an-enterprise#enterprise-owners
"""


@dataclass(frozen=True)
class GitHubOrganizationUserNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef('url')
    lastupdated: PropertyRef = PropertyRef('lastupdated', set_in_kwargs=True)
    fullname: PropertyRef = PropertyRef('name')
    username: PropertyRef = PropertyRef('login', extra_index=True)
    is_site_admin: PropertyRef = PropertyRef('isSiteAdmin')
    is_enterprise_owner: PropertyRef = PropertyRef('isEnterpriseOwner')
    email: PropertyRef = PropertyRef('email')
    company: PropertyRef = PropertyRef('company')
    has_2fa_enabled: PropertyRef = PropertyRef('hasTwoFactorEnabled')
    role: PropertyRef = PropertyRef('role')

@dataclass(frozen=True)
class GitHubUnaffiliatedUserNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef('url')
    lastupdated: PropertyRef = PropertyRef('lastupdated', set_in_kwargs=True)
    fullname: PropertyRef = PropertyRef('name')
    username: PropertyRef = PropertyRef('login', extra_index=True)
    is_site_admin: PropertyRef = PropertyRef('isSiteAdmin')
    is_enterprise_owner: PropertyRef = PropertyRef('isEnterpriseOwner')
    email: PropertyRef = PropertyRef('email')
    company: PropertyRef = PropertyRef('company')
    # 'has_2fa_enabled' not specified for unaffiliated; GitHub api does not return this property for them
    # 'role' not specified for unaffiliated; they do not have a role in the target organization

@dataclass(frozen=True)
class GitHubUserToOrganizationRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef('lastupdated', set_in_kwargs=True)


@dataclass(frozen=True)
class GitHubUserMemberOfOrganizationRel(CartographyRelSchema):
    target_node_label: str = 'GitHubOrganization'
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {'id': PropertyRef('MEMBER_OF')},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "MEMBER_OF"
    properties: GitHubUserToOrganizationRelProperties = GitHubUserToOrganizationRelProperties()


@dataclass(frozen=True)
class GitHubUserUnaffiliatedOrganizationRel(CartographyRelSchema):
    target_node_label: str = 'GitHubOrganization'
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {'id': PropertyRef('UNAFFILIATED')},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "UNAFFILIATED"
    properties: GitHubUserToOrganizationRelProperties = GitHubUserToOrganizationRelProperties()


@dataclass(frozen=True)
class GitHubOrganizationUserSchema(CartographyNodeSchema):
    label: str = 'GitHubUser'
    properties: GitHubOrganizationUserNodeProperties = GitHubOrganizationUserNodeProperties()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            GitHubUserMemberOfOrganizationRel(),
        ],
    )
    sub_resource_relationship = None


@dataclass(frozen=True)
class GitHubUnaffiliatedUserSchema(CartographyNodeSchema):
    label: str = 'GitHubUser'
    properties: GitHubUnaffiliatedUserNodeProperties = GitHubUnaffiliatedUserNodeProperties()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            GitHubUserUnaffiliatedOrganizationRel(),
        ],
    )
    sub_resource_relationship = None