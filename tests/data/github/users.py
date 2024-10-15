GITHUB_USER_DATA = [
    {
        'hasTwoFactorEnabled': None,
        'node': {
            'url': 'https://example.com/hjsimpson',
            'login': 'hjsimpson',
            'name': 'Homer Simpson',
            'isSiteAdmin': False,
            'email': 'hjsimpson@example.com',
            'company': 'Springfield Nuclear Power Plant',
        },
        'role': 'MEMBER',
    }, {
        'hasTwoFactorEnabled': None,
        'node': {
            'url': 'https://example.com/mbsimpson',
            'login': 'mbsimpson',
            'name': 'Marge Simpson',
            'isSiteAdmin': False,
            'email': 'mbsimpson@example.com',
            'company': 'Simpson Residence',
        },
        'role': 'ADMIN',
    },
]

# Note the subtle differences between owner data and user data:
# 1. owner data does not include a `hasTwoFactorEnabled` field (it in unavailable in the GraphQL query for these owners)
# 2. an `organizationRole` field instead of a `role` field.  For user data, membership in the queried org
#    is assumed.  The owner data, membership is not assumed, so there is an 'UNAFFILIATED' value for owners who are
#    not also users in an organization.  In this list, the 'OWNER' organizationRole matches the 'ADMIN' role in the
#    user data.  Similarly, the 'DIRECT_MEMBER' organizationRole matches the 'MEMBER' role.
GITHUB_ENTERPRISE_OWNER_DATA = [ # TODO put in real fake values for testing
    {
        'node': {
            'url': 'https://example.com/kbroflovski',
            'login': 'kbroflovski',
            'name': 'Kyle Broflovski',
            'isSiteAdmin': False,
            'email': 'kbroflovski@example.com',
            'company': 'South Park Elementary',
        },
        'organizationRole': 'UNAFFILIATED',
    }, {
        'node': {
            'url': 'https://example.com/bjsimpson',
            'login': 'bjsimpson',
            'name': 'Bartholomew Simpson',
            'isSiteAdmin': False,
            'email': 'bjsimpson@example.com',
            'company': 'Simpson Residence',
        },
        'organizationRole': 'DIRECT_MEMBER',
    }, {
        'node': {
            'url': 'https://example.com/lmsimpson',
            'login': 'lmsimpson',
            'name': 'Lisa Simpson',
            'isSiteAdmin': False,
            'email': 'lmsimpson@example.com',
            'company': 'Simpson Residence',
        },
        'organizationRole': 'OWNER',
    },
]

GITHUB_ORG_DATA = {
    'url': 'https://example.com/my_org',
    'login': 'my_org',
}
