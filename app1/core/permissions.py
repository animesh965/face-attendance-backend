PERMISSIONS = {
    "dashboard.read", "employees.read", "employees.create", "employees.update", "employees.delete",
    "attendance.read", "attendance.manage", "face.register", "face.manage", "recognition.read",
    "users.manage", "policies.manage", "cameras.manage", "organization.manage", "audit.read", "settings.manage",
}
ROLE_PERMISSIONS = {
    "super_admin": PERMISSIONS,
    "admin": PERMISSIONS - {"settings.manage"},
    "user": {"dashboard.read", "attendance.read"},
}

def permissions_for_role(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))
