PERMISSIONS = {
    "dashboard.read",
    "departments.read", "designations.read", "users.create",
    "employees.read", "employees.create", "employees.update", "employees.delete",
    "attendance.read", "attendance.manage",
    "face.register", "face.manage",
    "recognition.read", "live.read",
    "employeeworkcalendar.read",
    "users.manage", "policies.manage",
    "cameras.read", "cameras.manage",
    "analytics.read", "audit.read",
    "organization.manage", "settings.read", "settings.manage",
    # Leave tracker. leave.self/leave.team are for every signed-in employee (team data is
    # further limited to the caller's own reportees). Approval and configuration are admin-only.
    "leave.self", "leave.team",
    "leave.approve", "leave.manage", "leave.reports",
    "leave.override",
}

# Permissions only a super admin holds (overriding a final leave decision).
SUPER_ADMIN_ONLY = {"leave.override"}

# Administrators can access every application page and management API.
ROLE_PERMISSIONS = {
    "super_admin": PERMISSIONS,
    "admin": PERMISSIONS - SUPER_ADMIN_ONLY,
    # Employees are intentionally limited to their own dashboard, live recognition,
    # attendance, employee work calendar and their own leave data. Managers are ordinary
    # employees with reportees: they can view team leave but never approve it.
    "user": {
        "dashboard.read",
        "live.read", "recognition.read",
        "attendance.read",
        "employeeworkcalendar.read",
        "leave.self", "leave.team",
    },
}


def permissions_for_role(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))
