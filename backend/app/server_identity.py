from enum import Enum


class ServerRole(str, Enum):
    OWNER = "OWNER"
    SUPER_ADMIN = "SUPER_ADMIN"
    TECH_ADMIN = "TECH_ADMIN"
    TECH_SUPPORT = "TECH_SUPPORT"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    CONTRACT_MANAGER = "CONTRACT_MANAGER"
    TESTER = "TESTER"


INTERNAL_ROLES = {
    ServerRole.OWNER,
    ServerRole.SUPER_ADMIN,
    ServerRole.TECH_ADMIN,
    ServerRole.TECH_SUPPORT,
}


COMPANY_ROLES = {
    ServerRole.COMPANY_ADMIN,
    ServerRole.CONTRACT_MANAGER,
    ServerRole.TESTER,
}


ROLE_LABELS = {
    ServerRole.OWNER: "Propriétaire logiciel",
    ServerRole.SUPER_ADMIN: "Super administrateur",
    ServerRole.TECH_ADMIN: "Administrateur technique",
    ServerRole.TECH_SUPPORT: "Support technique",
    ServerRole.COMPANY_ADMIN: "Administrateur société",
    ServerRole.CONTRACT_MANAGER: "Responsable contrat",
    ServerRole.TESTER: "Testeur",
}


def is_internal_role(role: str) -> bool:
    try:
        return ServerRole(role) in INTERNAL_ROLES
    except ValueError:
        return False


def is_company_role(role: str) -> bool:
    try:
        return ServerRole(role) in COMPANY_ROLES
    except ValueError:
        return False


def get_role_label(role: str) -> str:
    try:
        return ROLE_LABELS[ServerRole(role)]
    except ValueError:
        return role
