# app/api/routes/attendance.py

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId

from app.dependencies.permissions import require_permission
from app.core.database import get_database
from app.core.time import local_date, now_local, now_utc
from app.services.attendance_service import AttendanceService


router = APIRouter(tags=["Attendance"])


# ============================================================
# HELPERS
# ============================================================

def format_working_hours(total_minutes: int) -> str:

    total_minutes = max(
        0,
        int(total_minutes or 0)
    )

    hours = total_minutes // 60
    minutes = total_minutes % 60

    return f"{hours:02d}:{minutes:02d}"


async def get_user_and_department(
    db,
    record: dict,
):

    user_doc = None
    department_doc = None

    user_id = record.get("user_id")

    if user_id:

        if isinstance(user_id, ObjectId):

            user_object_id = user_id

        elif ObjectId.is_valid(str(user_id)):

            user_object_id = ObjectId(
                str(user_id)
            )

        else:

            user_object_id = None

        if user_object_id:

            user_doc = await db.users.find_one({
                "_id": user_object_id
            })

    if user_doc:

        department_id = user_doc.get(
            "department_id"
        )

        if isinstance(
            department_id,
            ObjectId,
        ):

            department_object_id = (
                department_id
            )

        elif ObjectId.is_valid(
            str(department_id)
        ):

            department_object_id = (
                ObjectId(
                    str(department_id)
                )
            )

        else:

            department_object_id = None

        if department_object_id:

            department_doc = (
                await db.departments.find_one({
                    "_id":
                        department_object_id
                })
            )

    return user_doc, department_doc


# ============================================================
# FORMAT RECORD
# ============================================================

def format_record(
    record: dict,
    user: Optional[dict] = None,
    department: Optional[dict] = None,
) -> dict:

    sessions = (
        record.get("sessions", [])
        or []
    )

    current_state = record.get(
        "current_state",
        "OUT",
    )

    employee_name = (
        (user or {}).get("name")
        or record.get("name")
        or "Unknown"
    )

    employee_id = (
        (user or {}).get("employee_id")
        or record.get("employee_id")
        or record.get("user_id")
        or ""
    )

    department_name = (
        (department or {}).get("name")
        or record.get("department")
        or ""
    )

    # --------------------------------------------------------
    # Calculate LIVE values
    # --------------------------------------------------------

    required_work = int(
        record.get(
            "required_work_minutes",
            585,
        )
        or 585
    )

    free_break = int(
        record.get(
            "free_break_minutes",
            45,
        )
        or 45
    )

    live = AttendanceService.calculate_live(
        record,
        required_work,
        free_break,
        now_utc(),
    )

    first_session = (
        sessions[0]
        if sessions
        else {}
    )

    last_session = (
        sessions[-1]
        if sessions
        else {}
    )

    check_out = (
        last_session.get("out")
        if current_state == "OUT"
        else None
    )

    return {

        "id":
            str(record["_id"]),

        "employee":
            employee_name,

        "employeeId":
            str(employee_id),

        "department":
            department_name,

        "date":
            record.get("date"),

        "checkIn":
            first_session.get("in"),

        "checkOut":
            check_out,

        # ====================================================
        # COMPLETED VALUES
        # ====================================================

        "workingHours":
            format_working_hours(
                live["completed_work_minutes"]
            ),

        "totalWorkMinutes":
            live["completed_work_minutes"],

        "completedWorkMinutes":
            live["completed_work_minutes"],

        "completedWorkingHours":
            format_working_hours(
                live["completed_work_minutes"]
            ),

        # ====================================================
        # BREAK
        # ====================================================

        "totalBreakMinutes":
            live["completed_break_minutes"],

        "liveBreakMinutes":
            live["live_break_minutes"],

        "freeBreakMinutes":
            live["free_break_minutes"],

        "excessBreakMinutes":
            live["excess_break_minutes"],

        # ====================================================
        # EFFECTIVE WORK
        # ====================================================

        "effectiveWorkMinutes":
            live["effective_work_minutes"],

        "effectiveWorkingHours":
            format_working_hours(
                live["effective_work_minutes"]
            ),

        # ====================================================
        # REQUIRED
        # ====================================================

        "requiredWorkMinutes":
            live["required_work_minutes"],

        "requiredWorkingHours":
            format_working_hours(
                live["required_work_minutes"]
            ),

        # ====================================================
        # REMAINING
        # ====================================================

        "remainingWorkMinutes":
            live["remaining_work_minutes"],

        "remainingWorkingHours":
            format_working_hours(
                live["remaining_work_minutes"]
            ),

        "isWorkingTimeComplete":
            live["working_time_complete"],

        # ====================================================
        # LIVE
        # ====================================================

        "liveCurrentSessionMinutes":
            live["current_session_minutes"],

        "liveWorkMinutes":
            live["live_work_minutes"],

        "liveWorkingHours":
            format_working_hours(
                live["live_work_minutes"]
            ),

        "liveEffectiveWorkMinutes":
            live["live_effective_work_minutes"],

        "liveEffectiveWorkingHours":
            format_working_hours(
                live["live_effective_work_minutes"]
            ),

        "liveRemainingWorkMinutes":
            live["live_remaining_work_minutes"],

        "liveRemainingWorkingHours":
            format_working_hours(
                live["live_remaining_work_minutes"]
            ),

        "liveWorkingTimeComplete":
            live["live_working_time_complete"],

        # ====================================================
        # STATE
        # ====================================================

        "status":
            record.get(
                "status",
                "present",
            ),

        "currentState":
            current_state,

        "sessions":
            sessions,

        "lastAction":
            record.get("last_action"),

        "lastActionAt":
            record.get("last_action_at"),

        "lastSimilarity":
            record.get("last_similarity"),

        "createdAt":
            record.get("created_at"),

        "updatedAt":
            record.get("updated_at"),
    }


# ============================================================
# ATTENDANCE LIST
# ============================================================

@router.get("/attendance")
@router.get("/api/v1/attendance")
async def attendance_list(
    month: Optional[str] = None,
    date: Optional[str] = None,

    user=Depends(
        require_permission(
            "attendance.read"
        )
    ),

    db=Depends(get_database),
):

    query = {}

    # Employees may only read their own attendance. Admin roles retain global scope.
    if user.get("role") == "user":
        query["user_id"] = {"$in": [user["_id"], str(user["_id"])]}

    current = now_local()

    year = current.year
    current_month = current.month

    # --------------------------------------------------------
    # Validate month
    # --------------------------------------------------------

    month_number = None

    if month is not None:

        try:
            month_number = int(month)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Invalid month",
            )

        if not 1 <= month_number <= 12:

            raise HTTPException(
                status_code=400,
                detail="Month must be between 1 and 12",
            )

    # --------------------------------------------------------
    # Validate date
    # --------------------------------------------------------

    date_number = None

    if date is not None:

        try:
            date_number = int(date)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Invalid date",
            )

        if not 1 <= date_number <= 31:

            raise HTTPException(
                status_code=400,
                detail="Date must be between 1 and 31",
            )

    # --------------------------------------------------------
    # Build query
    # --------------------------------------------------------

    if (
        month_number is not None
        and date_number is not None
    ):

        query["date"] = (
            f"{year}-"
            f"{month_number:02d}-"
            f"{date_number:02d}"
        )

    elif date_number is not None:

        query["date"] = (
            f"{year}-"
            f"{current_month:02d}-"
            f"{date_number:02d}"
        )

    elif month_number is not None:

        query["date"] = {
            "$regex":
                f"^{year}-{month_number:02d}-"
        }

    # --------------------------------------------------------
    # Query
    # --------------------------------------------------------

    rows = (
        await db.attendance
        .find(query)
        .sort([
            ("date", -1),
            ("created_at", -1),
        ])
        .to_list(length=5000)
    )

    result = []

    for record in rows:

        user_doc, department_doc = (
            await get_user_and_department(
                db,
                record,
            )
        )

        result.append(
            format_record(
                record,
                user_doc,
                department_doc,
            )
        )

    return result


# ============================================================
# TODAY
# ============================================================

@router.get("/api/v1/attendance/today")
async def today(
    user=Depends(
        require_permission(
            "attendance.read"
        )
    ),

    db=Depends(get_database),
):

    date = local_date()

    today_query = {"date": date}
    if user.get("role") == "user":
        today_query["user_id"] = {"$in": [user["_id"], str(user["_id"])]}

    rows = (
        await db.attendance
        .find(today_query)
        .sort([
            ("created_at", -1)
        ])
        .to_list(length=None)
    )

    if user.get("role") == "user":
        total_employees = 1
    else:
        total_employees = await db.users.count_documents({"is_active": True, "employee_id": {"$exists": True}})

    present = len(rows)

    inside = sum(
        1
        for record in rows
        if record.get(
            "current_state"
        ) == "IN"
    )

    checked_out = sum(
        1
        for record in rows
        if record.get(
            "current_state"
        ) == "OUT"
    )

    # Employees on approved leave today are not absent (leave tracker integration).
    present_ids = {str(record.get("user_id")) for record in rows}
    leave_query = {
        "status": {"$in": ["approved", "cancellation_pending"]},
        "from_date": {"$lte": date},
        "to_date": {"$gte": date},
    }
    if user.get("role") == "user":
        leave_query["employee_id"] = user["_id"]
    on_leave = len({
        str(row["employee_id"])
        for row in await db.leave_requests.find(leave_query, {"employee_id": 1}).to_list(length=None)
        if str(row["employee_id"]) not in present_ids
    })

    absent = max(
        0,
        total_employees - present - on_leave,
    )

    formatted = []

    for record in rows:

        user_doc, department_doc = (
            await get_user_and_department(
                db,
                record,
            )
        )

        formatted.append(
            format_record(
                record,
                user_doc,
                department_doc,
            )
        )

    return {

        "date":
            date,

        "summary": {

            "total_employees":
                total_employees,

            "present":
                present,

            "inside":
                inside,

            "checked_out":
                checked_out,

            "on_leave":
                on_leave,

            "absent":
                absent,
        },

        "records":
            formatted,
    }


# ============================================================
# MY TODAY
# ============================================================

@router.get("/api/v1/attendance/me/today")
async def my_today(
    user=Depends(
        require_permission(
            "attendance.read"
        )
    ),

    db=Depends(get_database),
):

    date = local_date()

    user_id = str(
        user["_id"]
    )

    record = await db.attendance.find_one({
        "user_id": user_id,
        "date": date,
    })

    if not record:

        return {

            "date":
                date,

            "currentState":
                "OUT",

            "sessions":
                [],

            "workingHours":
                "00:00",

            "totalWorkMinutes":
                0,

            "liveWorkMinutes":
                0,

            "status":
                "absent",
        }

    user_doc, department_doc = (
        await get_user_and_department(
            db,
            record,
        )
    )

    return format_record(
        record,
        user_doc,
        department_doc,
    )





























# from typing import Optional

# from fastapi import APIRouter, Depends
# from bson import ObjectId

# from app.dependencies.permissions import require_permission
# from app.core.database import get_database
# from app.core.time import local_date, now_local
# from app.services.attendance_service import AttendanceService


# router = APIRouter(tags=["Attendance"])


# # ============================================================
# # HELPERS
# # ============================================================

# def format_working_hours(
#     total_minutes: int,
# ) -> str:

#     total_minutes = max(
#         0,
#         int(total_minutes or 0)
#     )

#     hours = total_minutes // 60
#     minutes = total_minutes % 60

#     return f"{hours:02d}:{minutes:02d}"


# # ============================================================
# # FORMAT ATTENDANCE RECORD
# # ============================================================

# # def format_record(
# #     record: dict,
# #     user: Optional[dict] = None,
# #     department: Optional[dict] = None,
# # ) -> dict:

# #     sessions = (
# #         record.get(
# #             "sessions",
# #             []
# #         )
# #         or []
# #     )

# #     first_session = (
# #         sessions[0]
# #         if sessions
# #         else {}
# #     )

# #     last_session = (
# #         sessions[-1]
# #         if sessions
# #         else {}
# #     )

# #     # ========================================================
# #     # STORED VALUES
# #     # ========================================================

# #     total_work_minutes = int(
# #         record.get(
# #             "total_work_minutes",
# #             0,
# #         )
# #         or 0
# #     )

# #     total_break_minutes = int(
# #         record.get(
# #             "total_break_minutes",
# #             0,
# #         )
# #         or 0
# #     )

# #     free_break_minutes = int(
# #         record.get(
# #             "free_break_minutes",
# #             45,
# #         )
# #         or 0
# #     )

# #     excess_break_minutes = int(
# #         record.get(
# #             "excess_break_minutes",
# #             0,
# #         )
# #         or 0
# #     )

# #     effective_work_minutes = int(
# #         record.get(
# #             "effective_work_minutes",
# #             total_work_minutes,
# #         )
# #         or 0
# #     )

# #     required_work_minutes = int(
# #         record.get(
# #             "required_work_minutes",
# #             585,
# #         )
# #         or 0
# #     )

# #     remaining_work_minutes = int(
# #         record.get(
# #             "remaining_work_minutes",
# #             max(
# #                 0,
# #                 required_work_minutes
# #                 - effective_work_minutes,
# #             ),
# #         )
# #         or 0
# #     )

# #     # ========================================================
# #     # LIVE VALUES
# #     # ========================================================

# #     live = AttendanceService.calculate_live(
# #         record
# #     )

# #     live_current_session_minutes = (
# #         live[
# #             "liveCurrentSessionMinutes"
# #         ]
# #     )

# #     live_work_minutes = (
# #         live[
# #             "liveWorkMinutes"
# #         ]
# #     )

# #     live_effective_work_minutes = (
# #         live[
# #             "liveEffectiveWorkMinutes"
# #         ]
# #     )

# #     live_remaining_work_minutes = (
# #         live[
# #             "liveRemainingWorkMinutes"
# #         ]
# #     )

# #     live_work_complete = (
# #         live[
# #             "liveWorkingTimeComplete"
# #         ]
# #     )

# #     # ========================================================
# #     # STATE
# #     # ========================================================

# #     current_state = record.get(
# #         "current_state",
# #         "OUT",
# #     )

# #     # ========================================================
# #     # EMPLOYEE
# #     # ========================================================

# #     employee_name = (
# #         (user or {}).get("name")
# #         or record.get("name")
# #         or "Unknown"
# #     )

# #     employee_id = (
# #         (user or {}).get("employee_id")
# #         or record.get("employee_id")
# #         or record.get("user_id")
# #         or ""
# #     )

# #     # ========================================================
# #     # DEPARTMENT
# #     # ========================================================

# #     department_name = (
# #         (department or {}).get("name")
# #         or record.get("department")
# #         or ""
# #     )

# #     # ========================================================
# #     # CHECK IN
# #     # ========================================================

# #     check_in = (
# #         first_session.get(
# #             "in"
# #         )
# #     )

# #     # ========================================================
# #     # CHECK OUT
# #     # ========================================================

# #     check_out = (
# #         last_session.get("out")
# #         if current_state == "OUT"
# #         else None
# #     )

# #     # ========================================================
# #     # RESPONSE
# #     # ========================================================

# #     return {

# #         "id":
# #             str(record["_id"]),

# #         "employee":
# #             employee_name,

# #         "employeeId":
# #             str(employee_id),

# #         "department":
# #             department_name,

# #         "date":
# #             record.get("date"),

# #         # ----------------------------------------------------
# #         # First IN
# #         # ----------------------------------------------------

# #         "checkIn":
# #             check_in,

# #         # ----------------------------------------------------
# #         # Last OUT
# #         # ----------------------------------------------------

# #         "checkOut":
# #             check_out,

# #         # ====================================================
# #         # STORED / COMPLETED WORK
# #         # ====================================================

# #         "workingHours":
# #             format_working_hours(
# #                 total_work_minutes
# #             ),

# #         "totalWorkMinutes":
# #             total_work_minutes,

# #         # ====================================================
# #         # BREAK
# #         # ====================================================

# #         "totalBreakMinutes":
# #             total_break_minutes,

# #         "freeBreakMinutes":
# #             free_break_minutes,

# #         "excessBreakMinutes":
# #             excess_break_minutes,

# #         # ====================================================
# #         # STORED EFFECTIVE WORK
# #         # ====================================================

# #         "effectiveWorkMinutes":
# #             effective_work_minutes,

# #         "effectiveWorkingHours":
# #             format_working_hours(
# #                 effective_work_minutes
# #             ),

# #         # ====================================================
# #         # POLICY
# #         # ====================================================

# #         "requiredWorkMinutes":
# #             required_work_minutes,

# #         "requiredWorkingHours":
# #             format_working_hours(
# #                 required_work_minutes
# #             ),

# #         # ====================================================
# #         # STORED REMAINING
# #         # ====================================================

# #         "remainingWorkMinutes":
# #             remaining_work_minutes,

# #         "remainingWorkingHours":
# #             format_working_hours(
# #                 remaining_work_minutes
# #             ),

# #         # ====================================================
# #         # STORED COMPLETION
# #         # ====================================================

# #         "isWorkingTimeComplete":
# #             (
# #                 effective_work_minutes
# #                 >= required_work_minutes
# #             ),

# #         # ====================================================
# #         # LIVE WORK
# #         # ====================================================

# #         "liveCurrentSessionMinutes":
# #             live_current_session_minutes,

# #         "liveWorkMinutes":
# #             live_work_minutes,

# #         "liveWorkingHours":
# #             format_working_hours(
# #                 live_work_minutes
# #             ),

# #         "liveEffectiveWorkMinutes":
# #             live_effective_work_minutes,

# #         "liveEffectiveWorkingHours":
# #             format_working_hours(
# #                 live_effective_work_minutes
# #             ),

# #         "liveRemainingWorkMinutes":
# #             live_remaining_work_minutes,

# #         "liveRemainingWorkingHours":
# #             format_working_hours(
# #                 live_remaining_work_minutes
# #             ),

# #         "liveWorkingTimeComplete":
# #             live_work_complete,

# #         # ====================================================
# #         # STATUS
# #         # ====================================================

# #         "status":
# #             record.get(
# #                 "status",
# #                 "present",
# #             ),

# #         "currentState":
# #             current_state,

# #         # ====================================================
# #         # SESSIONS
# #         # ====================================================

# #         "sessions":
# #             sessions,

# #         # ====================================================
# #         # TIMESTAMPS
# #         # ====================================================

# #         "createdAt":
# #             record.get(
# #                 "created_at"
# #             ),

# #         "updatedAt":
# #             record.get(
# #                 "updated_at"
# #             ),
# #     }

# def format_record(
#     record: dict,
#     user: Optional[dict] = None,
#     department: Optional[dict] = None,
# ) -> dict:

#     sessions = (
#         record.get("sessions", [])
#         or []
#     )

#     first_session = (
#         sessions[0]
#         if sessions
#         else {}
#     )

#     last_session = (
#         sessions[-1]
#         if sessions
#         else {}
#     )

#     # ========================================================
#     # CURRENT STATE
#     # ========================================================

#     current_state = record.get(
#         "current_state",
#         "OUT",
#     )

#     # ========================================================
#     # STORED / COMPLETED VALUES
#     # ========================================================

#     completed_work_minutes = int(
#         record.get(
#             "total_work_minutes",
#             0,
#         )
#         or 0
#     )

#     total_break_minutes = int(
#         record.get(
#             "total_break_minutes",
#             0,
#         )
#         or 0
#     )

#     free_break_minutes = int(
#         record.get(
#             "free_break_minutes",
#             45,
#         )
#         or 0
#     )

#     excess_break_minutes = int(
#         record.get(
#             "excess_break_minutes",
#             0,
#         )
#         or 0
#     )

#     completed_effective_work_minutes = int(
#         record.get(
#             "effective_work_minutes",
#             completed_work_minutes,
#         )
#         or 0
#     )

#     required_work_minutes = int(
#         record.get(
#             "required_work_minutes",
#             585,
#         )
#         or 0
#     )

#     completed_remaining_work_minutes = max(
#         0,
#         required_work_minutes
#         - completed_effective_work_minutes,
#     )

#     # ========================================================
#     # LIVE CALCULATION
#     # ========================================================

#     live = AttendanceService.calculate_live(
#         record
#     )

#     live_current_session_minutes = int(
#         live.get(
#             "liveCurrentSessionMinutes",
#             0,
#         )
#         or 0
#     )

#     live_work_minutes = int(
#         live.get(
#             "liveWorkMinutes",
#             completed_work_minutes,
#         )
#         or 0
#     )

#     live_effective_work_minutes = int(
#         live.get(
#             "liveEffectiveWorkMinutes",
#             completed_effective_work_minutes,
#         )
#         or 0
#     )

#     live_remaining_work_minutes = int(
#         live.get(
#             "liveRemainingWorkMinutes",
#             completed_remaining_work_minutes,
#         )
#         or 0
#     )

#     live_work_complete = bool(
#         live.get(
#             "liveWorkingTimeComplete",
#             False,
#         )
#     )

#     # ========================================================
#     # IMPORTANT
#     #
#     # If employee is currently IN:
#     #
#     #   Main values = LIVE values
#     #
#     # If employee is OUT:
#     #
#     #   Main values = STORED values
#     # ========================================================

#     if current_state == "IN":

#         display_work_minutes = (
#             live_work_minutes
#         )

#         display_effective_work_minutes = (
#             live_effective_work_minutes
#         )

#         display_remaining_work_minutes = (
#             live_remaining_work_minutes
#         )

#         display_complete = (
#             live_work_complete
#         )

#     else:

#         display_work_minutes = (
#             completed_work_minutes
#         )

#         display_effective_work_minutes = (
#             completed_effective_work_minutes
#         )

#         display_remaining_work_minutes = (
#             completed_remaining_work_minutes
#         )

#         display_complete = (
#             completed_effective_work_minutes
#             >= required_work_minutes
#         )

#     # ========================================================
#     # EMPLOYEE
#     # ========================================================

#     employee_name = (
#         (user or {}).get("name")
#         or record.get("name")
#         or "Unknown"
#     )

#     employee_id = (
#         (user or {}).get("employee_id")
#         or record.get("employee_id")
#         or record.get("user_id")
#         or ""
#     )

#     # ========================================================
#     # DEPARTMENT
#     # ========================================================

#     department_name = (
#         (department or {}).get("name")
#         or record.get("department")
#         or ""
#     )

#     # ========================================================
#     # CHECK IN
#     # ========================================================

#     check_in = first_session.get(
#         "in"
#     )

#     # ========================================================
#     # CHECK OUT
#     # ========================================================

#     check_out = (
#         last_session.get("out")
#         if current_state == "OUT"
#         else None
#     )

#     # ========================================================
#     # RESPONSE
#     # ========================================================

#     return {

#         # ====================================================
#         # IDENTITY
#         # ====================================================

#         "id":
#             str(record["_id"]),

#         "employee":
#             employee_name,

#         "employeeId":
#             str(employee_id),

#         "department":
#             department_name,

#         "date":
#             record.get("date"),

#         # ====================================================
#         # CHECK IN / OUT
#         # ====================================================

#         "checkIn":
#             check_in,

#         "checkOut":
#             check_out,

#         # ====================================================
#         # MAIN WORK VALUES
#         #
#         # These are now the values the frontend should display.
#         #
#         # IN  -> live
#         # OUT -> persisted
#         # ====================================================

#         "workingHours":
#             format_working_hours(
#                 display_work_minutes
#             ),

#         "totalWorkMinutes":
#             display_work_minutes,

#         # ====================================================
#         # COMPLETED/STORED WORK
#         #
#         # Useful for audit/debugging.
#         # ====================================================

#         "completedWorkMinutes":
#             completed_work_minutes,

#         "completedWorkingHours":
#             format_working_hours(
#                 completed_work_minutes
#             ),

#         # ====================================================
#         # BREAK
#         # ====================================================

#         "totalBreakMinutes":
#             total_break_minutes,

#         "freeBreakMinutes":
#             free_break_minutes,

#         "excessBreakMinutes":
#             excess_break_minutes,

#         # ====================================================
#         # MAIN EFFECTIVE WORK
#         # ====================================================

#         "effectiveWorkMinutes":
#             display_effective_work_minutes,

#         "effectiveWorkingHours":
#             format_working_hours(
#                 display_effective_work_minutes
#             ),

#         # ====================================================
#         # REQUIRED WORK
#         # ====================================================

#         "requiredWorkMinutes":
#             required_work_minutes,

#         "requiredWorkingHours":
#             format_working_hours(
#                 required_work_minutes
#             ),

#         # ====================================================
#         # MAIN REMAINING WORK
#         # ====================================================

#         "remainingWorkMinutes":
#             display_remaining_work_minutes,

#         "remainingWorkingHours":
#             format_working_hours(
#                 display_remaining_work_minutes
#             ),

#         "isWorkingTimeComplete":
#             display_complete,

#         # ====================================================
#         # LIVE INFORMATION
#         # ====================================================

#         "liveCurrentSessionMinutes":
#             live_current_session_minutes,

#         "liveWorkMinutes":
#             live_work_minutes,

#         "liveWorkingHours":
#             format_working_hours(
#                 live_work_minutes
#             ),

#         "liveEffectiveWorkMinutes":
#             live_effective_work_minutes,

#         "liveEffectiveWorkingHours":
#             format_working_hours(
#                 live_effective_work_minutes
#             ),

#         "liveRemainingWorkMinutes":
#             live_remaining_work_minutes,

#         "liveRemainingWorkingHours":
#             format_working_hours(
#                 live_remaining_work_minutes
#             ),

#         "liveWorkingTimeComplete":
#             live_work_complete,

#         # ====================================================
#         # STATUS
#         # ====================================================

#         "status":
#             record.get(
#                 "status",
#                 "present",
#             ),

#         "currentState":
#             current_state,

#         # ====================================================
#         # SESSIONS
#         # ====================================================

#         "sessions":
#             sessions,

#         # ====================================================
#         # TIMESTAMPS
#         # ====================================================

#         "createdAt":
#             record.get(
#                 "created_at"
#             ),

#         "updatedAt":
#             record.get(
#                 "updated_at"
#             ),
#     }

# # ============================================================
# # GET USER + DEPARTMENT
# # ============================================================

# async def get_user_and_department(
#     db,
#     record: dict,
# ):

#     user_doc = None
#     department_doc = None

#     user_id = record.get(
#         "user_id"
#     )

#     # ========================================================
#     # USER
#     # ========================================================

#     if user_id:

#         user_object_id = None

#         if isinstance(
#             user_id,
#             ObjectId,
#         ):

#             user_object_id = user_id

#         elif ObjectId.is_valid(
#             str(user_id)
#         ):

#             user_object_id = ObjectId(
#                 str(user_id)
#             )

#         if user_object_id:

#             user_doc = (
#                 await db.users.find_one(
#                     {
#                         "_id":
#                             user_object_id
#                     }
#                 )
#             )

#     # ========================================================
#     # DEPARTMENT
#     # ========================================================

#     if user_doc:

#         department_id = user_doc.get(
#             "department_id"
#         )

#         if department_id:

#             department_object_id = None

#             if isinstance(
#                 department_id,
#                 ObjectId,
#             ):

#                 department_object_id = (
#                     department_id
#                 )

#             elif ObjectId.is_valid(
#                 str(department_id)
#             ):

#                 department_object_id = (
#                     ObjectId(
#                         str(department_id)
#                     )
#                 )

#             if department_object_id:

#                 department_doc = (
#                     await db.departments.find_one(
#                         {
#                             "_id":
#                                 department_object_id
#                         }
#                     )
#                 )

#     return (
#         user_doc,
#         department_doc,
#     )


# # ============================================================
# # GET ATTENDANCE LIST
# # ============================================================

# @router.get("/attendance")
# @router.get("/api/v1/attendance")
# async def attendance_list(
#     month: Optional[str] = None,
#     date: Optional[str] = None,
#     user=Depends(
#         require_permission(
#             "attendance.read"
#         )
#     ),
#     db=Depends(get_database),
# ):

#     query = {}

#     current_local = now_local()

#     current_year = (
#         current_local.year
#     )

#     current_month = (
#         current_local.month
#     )

#     # ========================================================
#     # MONTH
#     # ========================================================

#     month_number = None

#     if month is not None:

#         try:

#             month_number = int(
#                 month
#             )

#         except (
#             ValueError,
#             TypeError,
#         ):

#             return []

#         if (
#             month_number < 1
#             or month_number > 12
#         ):

#             return []

#     # ========================================================
#     # DATE
#     # ========================================================

#     date_number = None

#     if date is not None:

#         try:

#             date_number = int(
#                 date
#             )

#         except (
#             ValueError,
#             TypeError,
#         ):

#             return []

#         if (
#             date_number < 1
#             or date_number > 31
#         ):

#             return []

#     # ========================================================
#     # MONTH + DATE
#     # ========================================================

#     if (
#         month_number is not None
#         and date_number is not None
#     ):

#         query["date"] = (
#             f"{current_year}-"
#             f"{month_number:02d}-"
#             f"{date_number:02d}"
#         )

#     # ========================================================
#     # DATE ONLY
#     # ========================================================

#     elif date_number is not None:

#         query["date"] = (
#             f"{current_year}-"
#             f"{current_month:02d}-"
#             f"{date_number:02d}"
#         )

#     # ========================================================
#     # MONTH ONLY
#     # ========================================================

#     elif month_number is not None:

#         query["date"] = {
#             "$regex":
#                 (
#                     f"^{current_year}-"
#                     f"{month_number:02d}-"
#                 )
#         }

#     # ========================================================
#     # DATABASE
#     # ========================================================

#     rows = (
#         await db.attendance
#         .find(query)
#         .sort(
#             [
#                 ("date", -1),
#                 ("created_at", -1),
#             ]
#         )
#         .to_list(
#             length=5000
#         )
#     )

#     result = []

#     # ========================================================
#     # FORMAT
#     # ========================================================

#     for record in rows:

#         (
#             user_doc,
#             department_doc,
#         ) = await get_user_and_department(
#             db,
#             record,
#         )

#         result.append(
#             format_record(
#                 record,
#                 user_doc,
#                 department_doc,
#             )
#         )

#     return result


# # ============================================================
# # TODAY
# # ============================================================

# @router.get(
#     "/api/v1/attendance/today"
# )
# async def today(
#     user=Depends(
#         require_permission(
#             "attendance.read"
#         )
#     ),
#     db=Depends(get_database),
# ):

#     date = local_date()

#     # ========================================================
#     # TODAY'S RECORDS
#     # ========================================================

#     rows = (
#         await db.attendance
#         .find(
#             {
#                 "date":
#                     date
#             }
#         )
#         .sort(
#             [
#                 ("created_at", -1)
#             ]
#         )
#         .to_list(
#             length=None
#         )
#     )

#     # ========================================================
#     # EMPLOYEES
#     # ========================================================

#     total_employees = (
#         await db.users.count_documents(
#             {
#                 "is_active":
#                     True
#             }
#         )
#     )

#     # ========================================================
#     # SUMMARY
#     # ========================================================

#     present = len(
#         rows
#     )

#     inside = sum(
#         1
#         for record in rows
#         if record.get(
#             "current_state"
#         ) == "IN"
#     )

#     checked_out = sum(
#         1
#         for record in rows
#         if record.get(
#             "current_state"
#         ) == "OUT"
#     )

#     absent = max(
#         0,
#         total_employees
#         - present,
#     )

#     # ========================================================
#     # FORMAT
#     # ========================================================

#     formatted_records = []

#     for record in rows:

#         (
#             user_doc,
#             department_doc,
#         ) = await get_user_and_department(
#             db,
#             record,
#         )

#         formatted_records.append(
#             format_record(
#                 record,
#                 user_doc,
#                 department_doc,
#             )
#         )

#     return {

#         "date":
#             date,

#         "summary": {

#             "total_employees":
#                 total_employees,

#             "present":
#                 present,

#             "inside":
#                 inside,

#             "checked_out":
#                 checked_out,

#             "absent":
#                 absent,
#         },

#         "records":
#             formatted_records,
#     }


# # ============================================================
# # MY TODAY
# # ============================================================

# @router.get(
#     "/api/v1/attendance/me/today"
# )
# async def my_today(
#     user=Depends(
#         require_permission(
#             "attendance.read"
#         )
#     ),
#     db=Depends(get_database),
# ):

#     date = local_date()

#     user_id = str(
#         user["_id"]
#     )

#     # ========================================================
#     # FIND
#     # ========================================================

#     record = await db.attendance.find_one(
#         {
#             "user_id":
#                 user_id,

#             "date":
#                 date,
#         }
#     )

#     # ========================================================
#     # NO RECORD
#     # ========================================================

#     if not record:

#         return {

#             "date":
#                 date,

#             "current_state":
#                 "OUT",

#             "sessions":
#                 [],

#             "total_work_minutes":
#                 0,

#             "total_break_minutes":
#                 0,

#             "free_break_minutes":
#                 45,

#             "excess_break_minutes":
#                 0,

#             "effective_work_minutes":
#                 0,

#             "required_work_minutes":
#                 585,

#             "remaining_work_minutes":
#                 585,

#             "workingHours":
#                 "00:00",

#             "effectiveWorkingHours":
#                 "00:00",

#             "requiredWorkingHours":
#                 "09:45",

#             "remainingWorkingHours":
#                 "09:45",

#             "isWorkingTimeComplete":
#                 False,

#             # Live values
#             "liveCurrentSessionMinutes":
#                 0,

#             "liveWorkMinutes":
#                 0,

#             "liveWorkingHours":
#                 "00:00",

#             "liveEffectiveWorkMinutes":
#                 0,

#             "liveEffectiveWorkingHours":
#                 "00:00",

#             "liveRemainingWorkMinutes":
#                 585,

#             "liveRemainingWorkingHours":
#                 "09:45",

#             "liveWorkingTimeComplete":
#                 False,

#             "status":
#                 "absent",
#         }

#     # ========================================================
#     # USER + DEPARTMENT
#     # ========================================================

#     (
#         user_doc,
#         department_doc,
#     ) = await get_user_and_department(
#         db,
#         record,
#     )

#     return format_record(
#         record,
#         user_doc,
#         department_doc,
#     )






















# from typing import Optional

# from fastapi import APIRouter, Depends
# from bson import ObjectId

# from app.dependencies.permissions import require_permission
# from app.core.database import get_database
# from app.core.time import local_date, now_local


# router = APIRouter(tags=["Attendance"])


# # ============================================================
# # HELPERS
# # ============================================================

# def format_working_hours(total_minutes: int) -> str:
#     """
#     Convert minutes into HH:MM format.

#     Example:
#         485 -> "08:05"
#         585 -> "09:45"
#         555 -> "09:15"
#     """

#     total_minutes = max(
#         0,
#         int(total_minutes or 0)
#     )

#     hours = total_minutes // 60
#     minutes = total_minutes % 60

#     return f"{hours:02d}:{minutes:02d}"


# def format_record(
#     record: dict,
#     user: Optional[dict] = None,
#     department: Optional[dict] = None,
# ) -> dict:
#     """
#     Convert MongoDB attendance document into
#     frontend-friendly response.
#     """

#     sessions = (
#         record.get("sessions", [])
#         or []
#     )

#     first_session = (
#         sessions[0]
#         if sessions
#         else {}
#     )

#     last_session = (
#         sessions[-1]
#         if sessions
#         else {}
#     )

#     # ========================================================
#     # WORK CALCULATIONS
#     # ========================================================

#     total_work_minutes = int(
#         record.get(
#             "total_work_minutes",
#             0,
#         )
#         or 0
#     )

#     total_break_minutes = int(
#         record.get(
#             "total_break_minutes",
#             0,
#         )
#         or 0
#     )

#     free_break_minutes = int(
#         record.get(
#             "free_break_minutes",
#             45,
#         )
#         or 0
#     )

#     excess_break_minutes = int(
#         record.get(
#             "excess_break_minutes",
#             0,
#         )
#         or 0
#     )

#     effective_work_minutes = int(
#         record.get(
#             "effective_work_minutes",
#             total_work_minutes,
#         )
#         or 0
#     )

#     required_work_minutes = int(
#         record.get(
#             "required_work_minutes",
#             585,
#         )
#         or 0
#     )

#     remaining_work_minutes = int(
#         record.get(
#             "remaining_work_minutes",
#             max(
#                 0,
#                 required_work_minutes
#                 - effective_work_minutes,
#             ),
#         )
#         or 0
#     )

#     is_working_time_complete = (
#         effective_work_minutes
#         >= required_work_minutes
#     )

#     current_state = record.get(
#         "current_state",
#         "OUT",
#     )

#     # ========================================================
#     # EMPLOYEE INFORMATION
#     # ========================================================

#     employee_name = (
#         (user or {}).get("name")
#         or record.get("name")
#         or "Unknown"
#     )

#     employee_id = (
#         (user or {}).get("employee_id")
#         or record.get("employee_id")
#         or record.get("user_id")
#         or ""
#     )

#     # ========================================================
#     # DEPARTMENT
#     # ========================================================

#     department_name = (
#         (department or {}).get("name")
#         or record.get("department")
#         or ""
#     )

#     # ========================================================
#     # CHECK IN
#     # ========================================================

#     check_in = first_session.get(
#         "in"
#     )

#     # ========================================================
#     # CHECK OUT
#     # ========================================================
#     #
#     # OUT:
#     #   Show last checkout
#     #
#     # IN:
#     #   Employee is currently inside,
#     #   therefore checkout is None.
#     #
#     # ========================================================

#     check_out = (
#         last_session.get("out")
#         if current_state == "OUT"
#         else None
#     )

#     # ========================================================
#     # RESPONSE
#     # ========================================================

#     return {

#         # ----------------------------------------------------
#         # Identity
#         # ----------------------------------------------------

#         "id": str(
#             record["_id"]
#         ),

#         "employee": employee_name,

#         "employeeId": str(
#             employee_id
#         ),

#         "department": department_name,

#         "date": record.get(
#             "date"
#         ),

#         # ----------------------------------------------------
#         # Check in/out
#         # ----------------------------------------------------

#         "checkIn": check_in,

#         "checkOut": check_out,

#         # ----------------------------------------------------
#         # Existing work fields
#         # ----------------------------------------------------

#         "workingHours":
#             format_working_hours(
#                 total_work_minutes
#             ),

#         "totalWorkMinutes":
#             total_work_minutes,

#         # ----------------------------------------------------
#         # Break fields
#         # ----------------------------------------------------

#         "totalBreakMinutes":
#             total_break_minutes,

#         "freeBreakMinutes":
#             free_break_minutes,

#         "excessBreakMinutes":
#             excess_break_minutes,

#         # ----------------------------------------------------
#         # Effective work
#         # ----------------------------------------------------

#         "effectiveWorkMinutes":
#             effective_work_minutes,

#         "effectiveWorkingHours":
#             format_working_hours(
#                 effective_work_minutes
#             ),

#         # ----------------------------------------------------
#         # Required work
#         # ----------------------------------------------------

#         "requiredWorkMinutes":
#             required_work_minutes,

#         "requiredWorkingHours":
#             format_working_hours(
#                 required_work_minutes
#             ),

#         # ----------------------------------------------------
#         # Remaining work
#         # ----------------------------------------------------

#         "remainingWorkMinutes":
#             remaining_work_minutes,

#         "remainingWorkingHours":
#             format_working_hours(
#                 remaining_work_minutes
#             ),

#         # ----------------------------------------------------
#         # Completion
#         # ----------------------------------------------------

#         "isWorkingTimeComplete":
#             is_working_time_complete,

#         # ----------------------------------------------------
#         # Attendance state
#         # ----------------------------------------------------

#         "status": record.get(
#             "status",
#             "present",
#         ),

#         "currentState": current_state,

#         # ----------------------------------------------------
#         # Sessions
#         # ----------------------------------------------------

#         "sessions": sessions,

#         # ----------------------------------------------------
#         # Timestamps
#         # ----------------------------------------------------

#         "createdAt": record.get(
#             "created_at"
#         ),

#         "updatedAt": record.get(
#             "updated_at"
#         ),
#     }


# # ============================================================
# # GET USER + DEPARTMENT
# # ============================================================

# async def get_user_and_department(
#     db,
#     record: dict,
# ):
#     """
#     Fetch user and department for an
#     attendance record.
#     """

#     user_doc = None
#     department_doc = None

#     user_id = record.get(
#         "user_id"
#     )

#     # ========================================================
#     # FIND USER
#     # ========================================================

#     if user_id:

#         user_object_id = None

#         if isinstance(
#             user_id,
#             ObjectId,
#         ):
#             user_object_id = user_id

#         elif ObjectId.is_valid(
#             str(user_id)
#         ):
#             user_object_id = ObjectId(
#                 str(user_id)
#             )

#         if user_object_id:

#             user_doc = (
#                 await db.users.find_one(
#                     {
#                         "_id": user_object_id
#                     }
#                 )
#             )

#     # ========================================================
#     # FIND DEPARTMENT
#     # ========================================================

#     if user_doc:

#         department_id = user_doc.get(
#             "department_id"
#         )

#         if department_id:

#             department_object_id = None

#             if isinstance(
#                 department_id,
#                 ObjectId,
#             ):
#                 department_object_id = (
#                     department_id
#                 )

#             elif ObjectId.is_valid(
#                 str(department_id)
#             ):
#                 department_object_id = (
#                     ObjectId(
#                         str(department_id)
#                     )
#                 )

#             if department_object_id:

#                 department_doc = (
#                     await db.departments.find_one(
#                         {
#                             "_id":
#                                 department_object_id
#                         }
#                     )
#                 )

#     return (
#         user_doc,
#         department_doc,
#     )


# # ============================================================
# # GET ATTENDANCE LIST
# # ============================================================

# @router.get("/attendance")
# @router.get("/api/v1/attendance")
# async def attendance_list(
#     month: Optional[str] = None,
#     date: Optional[str] = None,
#     user=Depends(
#         require_permission(
#             "attendance.read"
#         )
#     ),
#     db=Depends(get_database),
# ):
#     """
#     Get attendance records.

#     Supported:

#         GET /api/v1/attendance

#         GET /api/v1/attendance?month=09

#         GET /api/v1/attendance?month=09&date=21

#         GET /api/v1/attendance?date=21
#     """

#     query = {}

#     # ========================================================
#     # CURRENT LOCAL DATE
#     # ========================================================

#     current_local = now_local()

#     current_year = (
#         current_local.year
#     )

#     current_month = (
#         current_local.month
#     )

#     # ========================================================
#     # VALIDATE MONTH
#     # ========================================================

#     month_number = None

#     if month is not None:

#         try:

#             month_number = int(
#                 month
#             )

#         except (
#             ValueError,
#             TypeError,
#         ):

#             return []

#         if (
#             month_number < 1
#             or month_number > 12
#         ):

#             return []

#     # ========================================================
#     # VALIDATE DATE
#     # ========================================================

#     date_number = None

#     if date is not None:

#         try:

#             date_number = int(
#                 date
#             )

#         except (
#             ValueError,
#             TypeError,
#         ):

#             return []

#         if (
#             date_number < 1
#             or date_number > 31
#         ):

#             return []

#     # ========================================================
#     # MONTH + DATE
#     # ========================================================

#     if (
#         month_number is not None
#         and date_number is not None
#     ):

#         full_date = (
#             f"{current_year}-"
#             f"{month_number:02d}-"
#             f"{date_number:02d}"
#         )

#         query["date"] = full_date

#     # ========================================================
#     # DATE ONLY
#     # ========================================================

#     elif date_number is not None:

#         full_date = (
#             f"{current_year}-"
#             f"{current_month:02d}-"
#             f"{date_number:02d}"
#         )

#         query["date"] = full_date

#     # ========================================================
#     # MONTH ONLY
#     # ========================================================

#     elif month_number is not None:

#         query["date"] = {
#             "$regex":
#                 (
#                     f"^{current_year}-"
#                     f"{month_number:02d}-"
#                 )
#         }

#     # ========================================================
#     # QUERY DATABASE
#     # ========================================================

#     rows = (
#         await db.attendance
#         .find(query)
#         .sort(
#             [
#                 ("date", -1),
#                 ("created_at", -1),
#             ]
#         )
#         .to_list(
#             length=5000
#         )
#     )

#     result = []

#     # ========================================================
#     # FORMAT RECORDS
#     # ========================================================

#     for record in rows:

#         (
#             user_doc,
#             department_doc,
#         ) = await get_user_and_department(
#             db,
#             record,
#         )

#         result.append(
#             format_record(
#                 record,
#                 user_doc,
#                 department_doc,
#             )
#         )

#     return result


# # ============================================================
# # TODAY ATTENDANCE
# # ============================================================

# @router.get(
#     "/api/v1/attendance/today"
# )
# async def today(
#     user=Depends(
#         require_permission(
#             "attendance.read"
#         )
#     ),
#     db=Depends(get_database),
# ):
#     """
#     Get today's attendance summary.

#     Returns:

#         total employees
#         present employees
#         employees currently inside
#         employees checked out
#         absent employees
#         attendance records
#     """

#     date = local_date()

#     # ========================================================
#     # TODAY'S ATTENDANCE
#     # ========================================================

#     rows = (
#         await db.attendance
#         .find(
#             {
#                 "date": date
#             }
#         )
#         .sort(
#             [
#                 ("created_at", -1)
#             ]
#         )
#         .to_list(
#             length=None
#         )
#     )

#     # ========================================================
#     # ACTIVE EMPLOYEES
#     # ========================================================

#     total_employees = (
#         await db.users.count_documents(
#             {
#                 "is_active": True
#             }
#         )
#     )

#     # ========================================================
#     # STATISTICS
#     # ========================================================

#     present = len(
#         rows
#     )

#     inside = sum(
#         1
#         for record in rows
#         if record.get(
#             "current_state"
#         ) == "IN"
#     )

#     checked_out = sum(
#         1
#         for record in rows
#         if record.get(
#             "current_state"
#         ) == "OUT"
#     )

#     absent = max(
#         0,
#         total_employees
#         - present,
#     )

#     # ========================================================
#     # FORMAT RECORDS
#     # ========================================================

#     formatted_records = []

#     for record in rows:

#         (
#             user_doc,
#             department_doc,
#         ) = await get_user_and_department(
#             db,
#             record,
#         )

#         formatted_records.append(
#             format_record(
#                 record,
#                 user_doc,
#                 department_doc,
#             )
#         )

#     # ========================================================
#     # RESPONSE
#     # ========================================================

#     return {

#         "date": date,

#         "summary": {

#             "total_employees":
#                 total_employees,

#             "present":
#                 present,

#             "inside":
#                 inside,

#             "checked_out":
#                 checked_out,

#             "absent":
#                 absent,
#         },

#         "records":
#             formatted_records,
#     }


# # ============================================================
# # MY TODAY ATTENDANCE
# # ============================================================

# @router.get(
#     "/api/v1/attendance/me/today"
# )
# async def my_today(
#     user=Depends(
#         require_permission(
#             "attendance.read"
#         )
#     ),
#     db=Depends(get_database),
# ):
#     """
#     Get currently authenticated user's
#     attendance for today.
#     """

#     date = local_date()

#     user_id = str(
#         user["_id"]
#     )

#     # ========================================================
#     # FIND TODAY'S RECORD
#     # ========================================================

#     record = await db.attendance.find_one(
#         {
#             "user_id": user_id,
#             "date": date,
#         }
#     )

#     # ========================================================
#     # NO ATTENDANCE
#     # ========================================================

#     if not record:

#         return {

#             "date": date,

#             "current_state":
#                 "OUT",

#             "sessions": [],

#             "total_work_minutes":
#                 0,

#             "total_break_minutes":
#                 0,

#             "free_break_minutes":
#                 45,

#             "excess_break_minutes":
#                 0,

#             "effective_work_minutes":
#                 0,

#             "required_work_minutes":
#                 585,

#             "remaining_work_minutes":
#                 585,

#             "workingHours":
#                 "00:00",

#             "effectiveWorkingHours":
#                 "00:00",

#             "requiredWorkingHours":
#                 "09:45",

#             "remainingWorkingHours":
#                 "09:45",

#             "isWorkingTimeComplete":
#                 False,

#             "status":
#                 "absent",
#         }

#     # ========================================================
#     # FORMAT EXISTING RECORD
#     # ========================================================

#     (
#         user_doc,
#         department_doc,
#     ) = await get_user_and_department(
#         db,
#         record,
#     )

#     return format_record(
#         record,
#         user_doc,
#         department_doc,
#     )


















# from typing import Optional

# from fastapi import APIRouter, Depends
# from bson import ObjectId

# from app.dependencies.permissions import require_permission
# from app.core.database import get_database
# from app.core.time import local_date, now_local


# router = APIRouter(tags=["Attendance"])


# # ============================================================
# # Helpers
# # ============================================================

# def format_working_hours(total_minutes: int) -> str:
#     """
#     Convert minutes into HH:MM format.

#     Example:
#         485 -> "08:05"
#     """
#     total_minutes = max(0, int(total_minutes or 0))

#     hours = total_minutes // 60
#     minutes = total_minutes % 60

#     return f"{hours:02d}:{minutes:02d}"


# def format_record(
#     record: dict,
#     user: Optional[dict] = None,
#     department: Optional[dict] = None,
# ) -> dict:
#     """
#     Convert MongoDB attendance document into
#     frontend-friendly response.
#     """

#     sessions = record.get("sessions", []) or []

#     first_session = sessions[0] if sessions else {}
#     last_session = sessions[-1] if sessions else {}

#     total_minutes = int(
#         record.get("total_work_minutes", 0) or 0
#     )

#     current_state = record.get(
#         "current_state",
#         "OUT",
#     )

#     # --------------------------------------------------------
#     # Employee information
#     # --------------------------------------------------------

#     employee_name = (
#         (user or {}).get("name")
#         or record.get("name")
#         or "Unknown"
#     )

#     employee_id = (
#         (user or {}).get("employee_id")
#         or record.get("employee_id")
#         or record.get("user_id")
#         or ""
#     )

#     # --------------------------------------------------------
#     # Department
#     # --------------------------------------------------------

#     department_name = (
#         (department or {}).get("name")
#         or record.get("department")
#         or ""
#     )

#     # --------------------------------------------------------
#     # Check in / check out
#     # --------------------------------------------------------

#     check_in = first_session.get("in")

#     # Only show checkout when employee is currently OUT.
#     #
#     # Example:
#     #
#     # IN -> OUT
#     # checkOut = last OUT timestamp
#     #
#     # IN -> OUT -> IN
#     # checkOut = None because employee is currently inside.
#     #
#     check_out = (
#         last_session.get("out")
#         if current_state == "OUT"
#         else None
#     )

#     return {
#         "id": str(record["_id"]),

#         "employee": employee_name,

#         "employeeId": str(employee_id),

#         "department": department_name,

#         "date": record.get("date"),

#         "checkIn": check_in,

#         "checkOut": check_out,

#         "workingHours": format_working_hours(
#             total_minutes
#         ),

#         "totalWorkMinutes": total_minutes,

#         "status": record.get(
#             "status",
#             "present",
#         ),

#         "currentState": current_state,

#         "sessions": sessions,

#         "createdAt": record.get("created_at"),

#         "updatedAt": record.get("updated_at"),
#     }


# async def get_user_and_department(
#     db,
#     record: dict,
# ):
#     """
#     Fetch user and department for an attendance record.
#     """

#     user_doc = None
#     department_doc = None

#     user_id = record.get("user_id")

#     # --------------------------------------------------------
#     # Find user
#     # --------------------------------------------------------

#     if user_id:

#         user_object_id = None

#         if isinstance(user_id, ObjectId):
#             user_object_id = user_id

#         elif ObjectId.is_valid(str(user_id)):
#             user_object_id = ObjectId(str(user_id))

#         if user_object_id:

#             user_doc = await db.users.find_one(
#                 {
#                     "_id": user_object_id
#                 }
#             )

#     # --------------------------------------------------------
#     # Find department
#     # --------------------------------------------------------

#     if user_doc:

#         department_id = user_doc.get(
#             "department_id"
#         )

#         if department_id:

#             department_object_id = None

#             if isinstance(
#                 department_id,
#                 ObjectId,
#             ):
#                 department_object_id = department_id

#             elif ObjectId.is_valid(
#                 str(department_id)
#             ):
#                 department_object_id = ObjectId(
#                     str(department_id)
#                 )

#             if department_object_id:

#                 department_doc = (
#                     await db.departments.find_one(
#                         {
#                             "_id": department_object_id
#                         }
#                     )
#                 )

#     return user_doc, department_doc


# # ============================================================
# # GET ATTENDANCE LIST
# # ============================================================

# @router.get("/attendance")
# @router.get("/api/v1/attendance")
# async def attendance_list(
#     month: Optional[str] = None,
#     date: Optional[str] = None,
#     user=Depends(
#         require_permission("attendance.read")
#     ),
#     db=Depends(get_database),
# ):
#     """
#     Get attendance records.

#     Supported:

#         GET /api/v1/attendance

#         GET /api/v1/attendance?month=09

#         GET /api/v1/attendance?month=09&date=21

#         GET /api/v1/attendance?date=21

#     Database date format:

#         YYYY-MM-DD

#     Example:

#         2026-09-21
#     """

#     query = {}

#     # --------------------------------------------------------
#     # Current local date
#     # --------------------------------------------------------

#     current_local = now_local()

#     current_year = current_local.year
#     current_month = current_local.month

#     # --------------------------------------------------------
#     # Validate month
#     # --------------------------------------------------------

#     month_number = None

#     if month is not None:

#         try:
#             month_number = int(month)

#         except (ValueError, TypeError):
#             return []

#         if month_number < 1 or month_number > 12:
#             return []

#     # --------------------------------------------------------
#     # Validate date
#     # --------------------------------------------------------

#     date_number = None

#     if date is not None:

#         try:
#             date_number = int(date)

#         except (ValueError, TypeError):
#             return []

#         if date_number < 1 or date_number > 31:
#             return []

#     # --------------------------------------------------------
#     # month + date
#     #
#     # Example:
#     #
#     # month=09
#     # date=21
#     #
#     # 2026-09-21
#     # --------------------------------------------------------

#     if (
#         month_number is not None
#         and date_number is not None
#     ):

#         full_date = (
#             f"{current_year}-"
#             f"{month_number:02d}-"
#             f"{date_number:02d}"
#         )

#         query["date"] = full_date

#     # --------------------------------------------------------
#     # date only
#     #
#     # Example:
#     #
#     # date=21
#     #
#     # 2026-09-21
#     # --------------------------------------------------------

#     elif date_number is not None:

#         full_date = (
#             f"{current_year}-"
#             f"{current_month:02d}-"
#             f"{date_number:02d}"
#         )

#         query["date"] = full_date

#     # --------------------------------------------------------
#     # month only
#     #
#     # Example:
#     #
#     # month=09
#     #
#     # ^2026-09-
#     # --------------------------------------------------------

#     elif month_number is not None:

#         query["date"] = {
#             "$regex": (
#                 f"^{current_year}-"
#                 f"{month_number:02d}-"
#             )
#         }

#     # --------------------------------------------------------
#     # MongoDB query
#     # --------------------------------------------------------

#     rows = (
#         await db.attendance
#         .find(query)
#         .sort(
#             [
#                 ("date", -1),
#                 ("created_at", -1),
#             ]
#         )
#         .to_list(length=5000)
#     )

#     result = []

#     # --------------------------------------------------------
#     # Format every attendance record
#     # --------------------------------------------------------

#     for record in rows:

#         user_doc, department_doc = (
#             await get_user_and_department(
#                 db,
#                 record,
#             )
#         )

#         result.append(
#             format_record(
#                 record,
#                 user_doc,
#                 department_doc,
#             )
#         )

#     return result


# # ============================================================
# # TODAY ATTENDANCE
# # ============================================================

# @router.get("/api/v1/attendance/today")
# async def today(
#     user=Depends(
#         require_permission("attendance.read")
#     ),
#     db=Depends(get_database),
# ):
#     """
#     Get today's attendance summary.

#     Returns:

#         total employees
#         present employees
#         employees currently inside
#         employees checked out
#         absent employees
#         attendance records
#     """

#     date = local_date()

#     # --------------------------------------------------------
#     # Today's attendance
#     # --------------------------------------------------------

#     rows = (
#         await db.attendance
#         .find(
#             {
#                 "date": date
#             }
#         )
#         .sort(
#             [
#                 ("created_at", -1)
#             ]
#         )
#         .to_list(length=None)
#     )

#     # --------------------------------------------------------
#     # Active employees
#     # --------------------------------------------------------

#     total_employees = (
#         await db.users.count_documents(
#             {
#                 "is_active": True
#             }
#         )
#     )

#     # --------------------------------------------------------
#     # Statistics
#     # --------------------------------------------------------

#     present = len(rows)

#     inside = sum(
#         1
#         for record in rows
#         if record.get("current_state") == "IN"
#     )

#     checked_out = sum(
#         1
#         for record in rows
#         if record.get("current_state") == "OUT"
#     )

#     absent = max(
#         0,
#         total_employees - present,
#     )

#     # --------------------------------------------------------
#     # Format records
#     # --------------------------------------------------------

#     formatted_records = []

#     for record in rows:

#         user_doc, department_doc = (
#             await get_user_and_department(
#                 db,
#                 record,
#             )
#         )

#         formatted_records.append(
#             format_record(
#                 record,
#                 user_doc,
#                 department_doc,
#             )
#         )

#     return {
#         "date": date,

#         "summary": {
#             "total_employees": total_employees,
#             "present": present,
#             "inside": inside,
#             "checked_out": checked_out,
#             "absent": absent,
#         },

#         "records": formatted_records,
#     }


# # ============================================================
# # MY TODAY ATTENDANCE
# # ============================================================

# @router.get("/api/v1/attendance/me/today")
# async def my_today(
#     user=Depends(
#         require_permission("attendance.read")
#     ),
#     db=Depends(get_database),
# ):
#     """
#     Get currently authenticated user's
#     attendance for today.
#     """

#     date = local_date()

#     user_id = str(
#         user["_id"]
#     )

#     # --------------------------------------------------------
#     # Find today's record
#     # --------------------------------------------------------

#     record = await db.attendance.find_one(
#         {
#             "user_id": user_id,
#             "date": date,
#         }
#     )

#     # --------------------------------------------------------
#     # No attendance yet
#     # --------------------------------------------------------

#     if not record:

#         return {
#             "date": date,

#             "current_state": "OUT",

#             "sessions": [],

#             "total_work_minutes": 0,

#             "workingHours": "00:00",

#             "status": "absent",
#         }

#     # --------------------------------------------------------
#     # Return normalized record
#     # --------------------------------------------------------

#     user_doc, department_doc = (
#         await get_user_and_department(
#             db,
#             record,
#         )
#     )

#     return format_record(
#         record,
#         user_doc,
#         department_doc,
#     )





























# from fastapi import APIRouter, Depends, HTTPException
# from app.dependencies.permissions import require_permission
# from app.core.database import get_database
# from app.core.time import local_date
# from app.core.time import local_datetime

# router=APIRouter(tags=["Attendance"])

# def format_record(r, user=None, dept=None):
#     sessions=r.get("sessions",[]); first=sessions[0] if sessions else {}; last=sessions[-1] if sessions else {}
#     return {"id":str(r["_id"]),"employee":(user or {}).get("name",r.get("name","Unknown")),"employeeId":(user or {}).get("employee_id",r.get("user_id","")),"department":(dept or {}).get("name",""),"date":r.get("date"),"checkIn":first.get("in"),"checkOut":last.get("out") if r.get("current_state")=="OUT" else None,"workingHours":f"{int(r.get('total_work_minutes',0))//60:02d}:{int(r.get('total_work_minutes',0))%60:02d}","status":r.get("status","present")}

# # @router.get("/attendance")
# # @router.get("/api/v1/attendance")
# # async def attendance_list(month:str|None=None,date:str|None=None,user=Depends(require_permission("attendance.read")),db=Depends(get_database)):
# #     q={}
# #     if date:q["date"]=date
# #     elif month:q["date"]={"$regex":f"^{month}"}
# #     rows=await db.attendance.find(q).sort([("date",-1)]).to_list(length=5000); out=[]
# #     for r in rows:
# #         u=await db.users.find_one({"_id":__import__('bson').ObjectId(r["user_id"])}) if __import__('bson').ObjectId.is_valid(r["user_id"]) else None
# #         d=await db.departments.find_one({"_id":u.get("department_id")}) if u and u.get("department_id") else None
# #         out.append(format_record(r,u,d))
# #     return out

# @router.get("/attendance")
# @router.get("/api/v1/attendance")
# async def attendance_list(
#     month: str | None = None,
#     date: str | None = None,
#     user=Depends(require_permission("attendance.read")),
#     db=Depends(get_database),
# ):
#     q = {}

#     current_year = local_datetime().year

#     if month and date:
#         # Frontend sends month=09&date=21
#         full_date = f"{current_year}-{int(month):02d}-{int(date):02d}"
#         q["date"] = full_date

#     elif date:
#         # If only date is supplied
#         full_date = f"{current_year}-{local_datetime().month:02d}-{int(date):02d}"
#         q["date"] = full_date

#     elif month:
#         # Match YYYY-MM-*
#         q["date"] = {
#             "$regex": f"^{current_year}-{int(month):02d}-"
#         }

#     rows = await db.attendance.find(q).sort(
#         [("date", -1)]
#     ).to_list(length=5000)

#     out = []

#     for r in rows:
#         from bson import ObjectId

#         object_id = ObjectId(r["user_id"]) if ObjectId.is_valid(r["user_id"]) else None

#         u = (
#             await db.users.find_one({"_id": object_id})
#             if object_id
#             else None
#         )

#         d = (
#             await db.departments.find_one({"_id": u.get("department_id")})
#             if u and u.get("department_id")
#             else None
#         )

#         out.append(format_record(r, u, d))

#     return out

# @router.get("/api/v1/attendance/today")
# async def today(user=Depends(require_permission("attendance.read")),db=Depends(get_database)):
#     date=local_date(); rows=await db.attendance.find({"date":date}).to_list(length=None); total=await db.users.count_documents({"is_active":True}); present=len(rows); inside=sum(1 for r in rows if r.get("current_state")=="IN")
#     return {"date":date,"summary":{"total_employees":total,"present":present,"inside":inside,"checked_out":present-inside,"absent":max(0,total-present)},"records":rows}

# @router.get("/api/v1/attendance/me/today")
# async def my_today(user=Depends(require_permission("attendance.read")),db=Depends(get_database)):
#     r=await db.attendance.find_one({"user_id":str(user["_id"]),"date":local_date()}); return r or {"date":local_date(),"current_state":"OUT","sessions":[]}
