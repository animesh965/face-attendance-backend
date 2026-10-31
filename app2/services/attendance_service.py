# app/services/attendance_service.py

from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.core.database import get_database
from app.core.time import now_utc, local_date
from app.core.config import settings
from app.services.policy_service import PolicyService


class AttendanceService:

    # ============================================================
    # CONSTANTS
    # ============================================================

    DEFAULT_REQUIRED_WORK_MINUTES = 585
    DEFAULT_FREE_BREAK_MINUTES = 45

    # Never allow an extremely high similarity value to bypass
    # application-level validation accidentally.
    MIN_SIMILARITY = 0.0
    MAX_SIMILARITY = 1.0

    # ============================================================
    # TIME HELPERS
    # ============================================================

    @staticmethod
    def _minutes_between(start, end) -> int:
        if not start or not end:
            return 0

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if end <= start:
            return 0

        # IMPORTANT:
        # Whole minutes only.
        #
        # 20m31s -> 20
        return max(
            0,
            int((end - start).total_seconds() // 60)
        )

    # ============================================================
    # POLICY
    # ============================================================

    @staticmethod
    async def _get_policy(user_id: str) -> dict:

        try:
            policy = await PolicyService.get_for_user(user_id)
        except Exception:
            policy = None

        policy = policy or {}

        required_work = int(
            policy.get(
                "required_work_minutes",
                AttendanceService.DEFAULT_REQUIRED_WORK_MINUTES,
            )
            or AttendanceService.DEFAULT_REQUIRED_WORK_MINUTES
        )

        free_break = int(
            policy.get(
                "daily_break_minutes",
                AttendanceService.DEFAULT_FREE_BREAK_MINUTES,
            )
            or AttendanceService.DEFAULT_FREE_BREAK_MINUTES
        )

        return {
            "required_work_minutes": max(0, required_work),
            "daily_break_minutes": max(0, free_break),
            "policy_id": str(policy.get("_id"))
            if policy.get("_id")
            else None,
            "policy_name": policy.get("name", "Standard"),
        }

    # ============================================================
    # CALCULATE COMPLETED WORK / BREAK
    # ============================================================

    @staticmethod
    def calculate_completed(record: dict) -> dict:

        sessions = record.get("sessions", []) or []

        total_work_minutes = 0
        total_break_minutes = 0

        previous_out = None

        for session in sessions:

            in_time = session.get("in")
            out_time = session.get("out")

            # ----------------------------------------------------
            # Completed work session
            # ----------------------------------------------------

            if in_time and out_time:

                total_work_minutes += (
                    AttendanceService._minutes_between(
                        in_time,
                        out_time,
                    )
                )

                # ------------------------------------------------
                # Break between previous OUT and current IN
                # ------------------------------------------------

                if previous_out and in_time:

                    total_break_minutes += (
                        AttendanceService._minutes_between(
                            previous_out,
                            in_time,
                        )
                    )

                previous_out = out_time

        return {
            "total_work_minutes": total_work_minutes,
            "total_break_minutes": total_break_minutes,
        }

    # ============================================================
    # CALCULATE LIVE VALUES
    # ============================================================

    @staticmethod
    def calculate_live(
        record: dict,
        required_work_minutes: int,
        free_break_minutes: int,
        now: Optional[datetime] = None,
    ) -> dict:

        now = now or now_utc()

        completed = (
            AttendanceService.calculate_completed(record)
        )

        completed_work = completed[
            "total_work_minutes"
        ]

        completed_break = completed[
            "total_break_minutes"
        ]

        sessions = record.get("sessions", []) or []

        current_session_minutes = 0
        current_break_minutes = 0

        current_state = record.get(
            "current_state",
            "OUT",
        )

        # --------------------------------------------------------
        # Currently IN
        # --------------------------------------------------------

        if (
            current_state == "IN"
            and sessions
            and sessions[-1].get("in")
            and sessions[-1].get("out") is None
        ):

            current_session_minutes = (
                AttendanceService._minutes_between(
                    sessions[-1]["in"],
                    now,
                )
            )

        # --------------------------------------------------------
        # Currently OUT
        #
        # The employee's current OUT period is a live break.
        # --------------------------------------------------------

        elif (
            current_state == "OUT"
            and sessions
            and sessions[-1].get("out")
        ):

            current_break_minutes = (
                AttendanceService._minutes_between(
                    sessions[-1]["out"],
                    now,
                )
            )

        live_work = (
            completed_work
            + current_session_minutes
        )

        live_break = (
            completed_break
            + current_break_minutes
        )

        excess_break = max(
            0,
            live_break - free_break_minutes,
        )

        effective_work = max(
            0,
            live_work - excess_break,
        )

        remaining = max(
            0,
            required_work_minutes - effective_work,
        )

        return {
            "completed_work_minutes": completed_work,

            "current_session_minutes":
                current_session_minutes,

            "live_work_minutes":
                live_work,

            "completed_break_minutes":
                completed_break,

            "current_break_minutes":
                current_break_minutes,

            "live_break_minutes":
                live_break,

            "free_break_minutes":
                free_break_minutes,

            "excess_break_minutes":
                excess_break,

            "effective_work_minutes":
                max(
                    0,
                    completed_work
                    - max(
                        0,
                        completed_break
                        - free_break_minutes,
                    ),
                ),

            "live_effective_work_minutes":
                effective_work,

            "required_work_minutes":
                required_work_minutes,

            "remaining_work_minutes":
                max(
                    0,
                    required_work_minutes
                    - max(
                        0,
                        completed_work
                        - max(
                            0,
                            completed_break
                            - free_break_minutes,
                        ),
                    ),
                ),

            "live_remaining_work_minutes":
                remaining,

            "working_time_complete":
                (
                    max(
                        0,
                        completed_work
                        - max(
                            0,
                            completed_break
                            - free_break_minutes,
                        ),
                    )
                    >= required_work_minutes
                ),

            "live_working_time_complete":
                effective_work
                >= required_work_minutes,
        }

    # ============================================================
    # PROCESS ATTENDANCE
    # ============================================================

    @staticmethod
    async def process_attendance(
        user_id: str,
        user: dict,
        similarity: float,
        force: bool = False,
        source: str = "FACE",
        camera_id: Optional[str] = None,
        recognition_id: Optional[str] = None,
    ):

        db = get_database()

        now = now_utc()
        date = local_date()

        attendance = db.attendance
        events = db.attendance_events

        # ========================================================
        # 1. VALIDATE USER
        # ========================================================

        if not user_id:
            return {
                "success": False,
                "action": "rejected",
                "reason": "invalid_user",
            }

        if not user:
            return {
                "success": False,
                "action": "rejected",
                "reason": "user_not_found",
            }

        # ========================================================
        # 2. VALIDATE SOURCE
        # ========================================================

        source = str(source or "FACE").upper()

        allowed_sources = {
            "FACE",
            "LOCATION",
            "ADMIN",
        }

        if source not in allowed_sources:
            return {
                "success": False,
                "action": "rejected",
                "reason": "invalid_attendance_source",
            }

        # ========================================================
        # 3. VALIDATE SIMILARITY
        # ========================================================

        try:
            similarity = float(similarity)
        except (TypeError, ValueError):
            similarity = 0.0

        if not (
            AttendanceService.MIN_SIMILARITY
            <= similarity
            <= AttendanceService.MAX_SIMILARITY
        ):
            return {
                "success": False,
                "action": "rejected",
                "reason": "invalid_similarity",
            }

        # ========================================================
        # 4. FACE CONFIDENCE PROTECTION
        # ========================================================

        # For FACE attendance, require a configured threshold.
        #
        # Example:
        # ATTENDANCE_FACE_MIN_SIMILARITY=0.55
        #

        if source == "FACE":

            threshold = float(
                getattr(
                    settings,
                    "ATTENDANCE_FACE_MIN_SIMILARITY",
                    0.55,
                )
            )

            if similarity < threshold:

                # Store rejected recognition event.
                try:
                    await events.insert_one({
                        "user_id": str(user_id),
                        "date": date,
                        "event_type": "REJECTED",
                        "reason": "low_similarity",
                        "similarity": similarity,
                        "threshold": threshold,
                        "source": source,
                        "camera_id": camera_id,
                        "recognition_id": recognition_id,
                        "created_at": now,
                    })
                except Exception:
                    pass

                return {
                    "success": False,
                    "action": "rejected",
                    "reason": "low_similarity",
                    "similarity": similarity,
                    "required_similarity": threshold,
                }

        # ========================================================
        # 5. IDEMPOTENCY PROTECTION
        # ========================================================

        if recognition_id:

            existing_event = await events.find_one({
                "recognition_id": str(recognition_id),
                "event_type": "ATTENDANCE_ACCEPTED",
            })

            if existing_event:

                existing_attendance = (
                    await attendance.find_one({
                        "_id": existing_event.get(
                            "attendance_id"
                        )
                    })
                )

                if existing_attendance:

                    return AttendanceService._response(
                        existing_attendance,
                        action="duplicate_request",
                    )

        # ========================================================
        # 6. LOAD TODAY'S RECORD
        # ========================================================

        record = await attendance.find_one({
            "user_id": str(user_id),
            "date": date,
        })

        # ========================================================
        # 7. CREATE DAILY RECORD
        # ========================================================

        if not record:

            try:

                initial_policy = (
                    await AttendanceService._get_policy(
                        str(user_id)
                    )
                )

                new_record = {
                    "user_id": str(user_id),
                    "employee_id": user.get(
                        "employee_id"
                    ),
                    "date": date,

                    "sessions": [],

                    "current_state": "OUT",

                    "total_work_minutes": 0,
                    "total_break_minutes": 0,
                    "free_break_minutes": initial_policy[
                        "daily_break_minutes"
                    ],
                    "excess_break_minutes": 0,
                    "effective_work_minutes": 0,

                    "required_work_minutes":
                        initial_policy[
                            "required_work_minutes"
                        ],

                    "remaining_work_minutes":
                        initial_policy[
                            "required_work_minutes"
                        ],

                    "policy_id":
                        initial_policy["policy_id"],

                    "status": "present",

                    "last_action": None,
                    "last_action_at": None,
                    "last_similarity": None,

                    "created_at": now,
                    "updated_at": now,
                }

                await attendance.insert_one(
                    new_record
                )

            except DuplicateKeyError:
                # Another request created the record
                # at the same time.
                pass

            record = await attendance.find_one({
                "user_id": str(user_id),
                "date": date,
            })

        if not record:
            raise RuntimeError(
                "Unable to create or load attendance record"
            )

        # ========================================================
        # 8. SERVER-SIDE COOLDOWN
        # ========================================================

        if not force:

            last_action_at = record.get(
                "last_action_at"
            )

            if last_action_at:

                if last_action_at.tzinfo is None:
                    last_action_at = (
                        last_action_at.replace(
                            tzinfo=timezone.utc
                        )
                    )

                cooldown_seconds = int(
                    getattr(
                        settings,
                        "ATTENDANCE_TOGGLE_COOLDOWN_SECONDS",
                        30,
                    )
                )

                elapsed = (
                    now - last_action_at
                ).total_seconds()

                if elapsed < cooldown_seconds:

                    return AttendanceService._response(
                        record,
                        action="cooldown",
                    )

        # ========================================================
        # 9. LOAD POLICY
        # ========================================================

        policy = await AttendanceService._get_policy(
            str(user_id)
        )

        required_work_minutes = policy[
            "required_work_minutes"
        ]

        free_break_minutes = policy[
            "daily_break_minutes"
        ]

        # ========================================================
        # 10. ATOMIC TOGGLE
        #
        # This is VERY important.
        #
        # Two simultaneous requests cannot both perform
        # the same state transition.
        # ========================================================

        state = record.get(
            "current_state",
            "OUT",
        )

        # ========================================================
        # OUT → IN
        # ========================================================

        if state == "OUT":

            new_session = {
                "in": now,
                "out": None,
                "source": source,
                "camera_id": camera_id,
                "similarity": similarity,
            }

            result = await attendance.update_one(
                {
                    "_id": record["_id"],

                    # IMPORTANT:
                    # State must still be OUT when MongoDB
                    # executes this update.
                    "current_state": "OUT",

                    # Prevent stale simultaneous requests.
                    "last_action_at":
                        record.get(
                            "last_action_at"
                        ),
                },
                {
                    "$push": {
                        "sessions": new_session
                    },
                    "$set": {
                        "current_state": "IN",
                        "last_action": "check_in",
                        "last_action_at": now,
                        "last_similarity": similarity,
                        "updated_at": now,
                        "status": "present",
                    },
                },
            )

            if result.modified_count != 1:

                latest = await attendance.find_one({
                    "_id": record["_id"]
                })

                return AttendanceService._response(
                    latest or record,
                    action="duplicate_request",
                )

            # ====================================================
            # AUDIT EVENT
            # ====================================================

            updated = await attendance.find_one({
                "_id": record["_id"]
            })

            try:
                await events.insert_one({
                    "attendance_id": record["_id"],
                    "user_id": str(user_id),
                    "date": date,
                    "event_type": "ATTENDANCE_ACCEPTED",
                    "action": "check_in",
                    "source": source,
                    "camera_id": camera_id,
                    "similarity": similarity,
                    "recognition_id": recognition_id,
                    "timestamp": now,
                    "created_at": now,
                })
            except Exception:
                pass

            return AttendanceService._response(
                updated,
                action="check_in",
            )

        # ========================================================
        # IN → OUT
        # ========================================================

        if state == "IN":

            sessions = (
                record.get("sessions", [])
                or []
            )

            if (
                not sessions
                or sessions[-1].get("out") is not None
            ):

                return AttendanceService._response(
                    record,
                    action="invalid_state",
                )

            current_session_in = (
                sessions[-1].get("in")
            )

            if not current_session_in:
                return AttendanceService._response(
                    record,
                    action="invalid_state",
                )

            session_minutes = (
                AttendanceService._minutes_between(
                    current_session_in,
                    now,
                )
            )

            # ----------------------------------------------------
            # Atomic update
            # ----------------------------------------------------

            result = await attendance.update_one(
                {
                    "_id": record["_id"],

                    "current_state": "IN",

                    "last_action_at":
                        record.get(
                            "last_action_at"
                        ),
                },
                {
                    "$set": {
                        "sessions.$[session].out": now,

                        "current_state": "OUT",

                        "last_action":
                            "check_out",

                        "last_action_at":
                            now,

                        "last_similarity":
                            similarity,

                        "updated_at":
                            now,

                        "status":
                            "present",
                    },

                    "$inc": {
                        "total_work_minutes":
                            session_minutes
                    },
                },
                array_filters=[
                    {
                        "session.out": None
                    }
                ],
            )

            if result.modified_count != 1:

                latest = await attendance.find_one({
                    "_id": record["_id"]
                })

                return AttendanceService._response(
                    latest or record,
                    action="duplicate_request",
                )

            # ----------------------------------------------------
            # Recalculate persisted values
            # ----------------------------------------------------

            updated = await attendance.find_one({
                "_id": record["_id"]
            })

            calculated = (
                AttendanceService.calculate_completed(
                    updated
                )
            )

            completed_work = calculated[
                "total_work_minutes"
            ]

            completed_break = calculated[
                "total_break_minutes"
            ]

            excess_break = max(
                0,
                completed_break
                - free_break_minutes,
            )

            effective_work = max(
                0,
                completed_work
                - excess_break,
            )

            remaining_work = max(
                0,
                required_work_minutes
                - effective_work,
            )

            await attendance.update_one(
                {
                    "_id": record["_id"]
                },
                {
                    "$set": {
                        "total_work_minutes":
                            completed_work,

                        "total_break_minutes":
                            completed_break,

                        "free_break_minutes":
                            free_break_minutes,

                        "excess_break_minutes":
                            excess_break,

                        "effective_work_minutes":
                            effective_work,

                        "required_work_minutes":
                            required_work_minutes,

                        "remaining_work_minutes":
                            remaining_work,

                        "updated_at":
                            now,
                    }
                },
            )

            updated = await attendance.find_one({
                "_id": record["_id"]
            })

            # ----------------------------------------------------
            # AUDIT EVENT
            # ----------------------------------------------------

            try:
                await events.insert_one({
                    "attendance_id":
                        record["_id"],

                    "user_id":
                        str(user_id),

                    "date":
                        date,

                    "event_type":
                        "ATTENDANCE_ACCEPTED",

                    "action":
                        "check_out",

                    "source":
                        source,

                    "camera_id":
                        camera_id,

                    "similarity":
                        similarity,

                    "session_minutes":
                        session_minutes,

                    "recognition_id":
                        recognition_id,

                    "timestamp":
                        now,

                    "created_at":
                        now,
                })

            except Exception:
                pass

            return AttendanceService._response(
                updated,
                action="check_out",
            )

        # ========================================================
        # UNKNOWN STATE
        # ========================================================

        return AttendanceService._response(
            record,
            action="invalid_state",
        )

    # ============================================================
    # RESPONSE
    # ============================================================

    @staticmethod
    def _response(
        record: dict,
        action: str,
    ) -> dict:

        if not record:
            return {
                "success": False,
                "action": action,
            }

        policy_required = int(
            record.get(
                "required_work_minutes",
                AttendanceService.DEFAULT_REQUIRED_WORK_MINUTES,
            )
            or 0
        )

        free_break = int(
            record.get(
                "free_break_minutes",
                AttendanceService.DEFAULT_FREE_BREAK_MINUTES,
            )
            or 0
        )

        live = AttendanceService.calculate_live(
            record,
            policy_required,
            free_break,
        )

        sessions = (
            record.get("sessions", [])
            or []
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

        current_state = record.get(
            "current_state",
            "OUT",
        )

        return {
            "success": action not in {
                "invalid_state",
                "rejected",
            },

            "action": action,

            "attendance_id":
                str(record["_id"]),

            "current_state":
                current_state,

            "status":
                record.get(
                    "status",
                    "present",
                ),

            "check_in":
                first_session.get("in"),

            "check_out":
                (
                    last_session.get("out")
                    if current_state == "OUT"
                    else None
                ),

            "total_work_minutes":
                live["completed_work_minutes"],

            "live_work_minutes":
                live["live_work_minutes"],

            "total_break_minutes":
                live["completed_break_minutes"],

            "live_break_minutes":
                live["live_break_minutes"],

            "free_break_minutes":
                live["free_break_minutes"],

            "excess_break_minutes":
                live["excess_break_minutes"],

            "effective_work_minutes":
                live["effective_work_minutes"],

            "live_effective_work_minutes":
                live["live_effective_work_minutes"],

            "required_work_minutes":
                live["required_work_minutes"],

            "remaining_work_minutes":
                live["remaining_work_minutes"],

            "live_remaining_work_minutes":
                live["live_remaining_work_minutes"],

            "sessions":
                sessions,

            "last_action":
                record.get("last_action"),

            "last_action_at":
                record.get("last_action_at"),

            "last_similarity":
                record.get("last_similarity"),

            "created_at":
                record.get("created_at"),

            "updated_at":
                record.get("updated_at"),
        }




























# from datetime import datetime
# from typing import Optional

# from app.core.database import get_database
# from app.core.time import now_utc, local_date
# from app.core.config import settings
# from app.services.policy_service import PolicyService


# class AttendanceService:

#     # ============================================================
#     # MAIN ATTENDANCE TOGGLE
#     # ============================================================

#     @staticmethod
#     async def process_attendance(
#         user_id: str,
#         user: dict,
#         similarity: float,
#         force: bool = False,
#     ):
#         """
#         Attendance toggle:

#             OUT -> IN
#             IN  -> OUT

#         Supports multiple sessions per day:

#             IN -> OUT -> IN -> OUT -> IN -> OUT
#         """

#         db = get_database()

#         now = now_utc()
#         date = local_date()

#         attendance_collection = db.attendance

#         # ========================================================
#         # GET USER POLICY
#         # ========================================================

#         policy = await PolicyService.get_for_user(
#             user_id
#         )

#         required_work_minutes = int(
#             policy.get(
#                 "required_work_minutes",
#                 585,
#             )
#         )

#         free_break_minutes = int(
#             policy.get(
#                 "daily_break_minutes",
#                 45,
#             )
#         )

#         # ========================================================
#         # FIND TODAY'S RECORD
#         # ========================================================

#         record = await attendance_collection.find_one(
#             {
#                 "user_id": user_id,
#                 "date": date,
#             }
#         )

#         # ========================================================
#         # COOLDOWN
#         # ========================================================

#         if record and not force:

#             last_action_at = record.get(
#                 "last_action_at"
#             )

#             if last_action_at:

#                 if last_action_at.tzinfo is None:

#                     last_action_at = (
#                         last_action_at.replace(
#                             tzinfo=now.tzinfo
#                         )
#                     )

#                 elapsed_seconds = (
#                     now - last_action_at
#                 ).total_seconds()

#                 if (
#                     elapsed_seconds
#                     < settings.ATTENDANCE_TOGGLE_COOLDOWN_SECONDS
#                 ):

#                     return AttendanceService._response(
#                         record,
#                         "cooldown",
#                     )

#         # ========================================================
#         # CREATE TODAY'S RECORD
#         # ========================================================

#         if not record:

#             new_record = {

#                 "user_id":
#                     user_id,

#                 "date":
#                     date,

#                 "sessions":
#                     [],

#                 "current_state":
#                     "OUT",

#                 # ------------------------------------------------
#                 # Work
#                 # ------------------------------------------------

#                 "total_work_minutes":
#                     0,

#                 # ------------------------------------------------
#                 # Break
#                 # ------------------------------------------------

#                 "total_break_minutes":
#                     0,

#                 "free_break_minutes":
#                     free_break_minutes,

#                 "excess_break_minutes":
#                     0,

#                 # ------------------------------------------------
#                 # Effective work
#                 # ------------------------------------------------

#                 "effective_work_minutes":
#                     0,

#                 # ------------------------------------------------
#                 # Policy
#                 # ------------------------------------------------

#                 "required_work_minutes":
#                     required_work_minutes,

#                 "remaining_work_minutes":
#                     required_work_minutes,

#                 # ------------------------------------------------
#                 # Status
#                 # ------------------------------------------------

#                 "status":
#                     "present",

#                 # ------------------------------------------------
#                 # Last action
#                 # ------------------------------------------------

#                 "last_action":
#                     None,

#                 "last_action_at":
#                     None,

#                 "last_similarity":
#                     None,

#                 # ------------------------------------------------
#                 # Timestamps
#                 # ------------------------------------------------

#                 "created_at":
#                     now,

#                 "updated_at":
#                     now,
#             }

#             result = await attendance_collection.insert_one(
#                 new_record
#             )

#             record = await attendance_collection.find_one(
#                 {
#                     "_id":
#                         result.inserted_id
#                 }
#             )

#         # ========================================================
#         # CURRENT STATE
#         # ========================================================

#         current_state = record.get(
#             "current_state",
#             "OUT",
#         )

#         # ========================================================
#         # OUT -> IN
#         # ========================================================

#         if current_state == "OUT":

#             new_session = {

#                 "in":
#                     now,

#                 "out":
#                     None,
#             }

#             await attendance_collection.update_one(

#                 {
#                     "_id":
#                         record["_id"]
#                 },

#                 {
#                     "$push": {
#                         "sessions":
#                             new_session
#                     },

#                     "$set": {

#                         "current_state":
#                             "IN",

#                         "last_action":
#                             "check_in",

#                         "last_action_at":
#                             now,

#                         "last_similarity":
#                             similarity,

#                         "status":
#                             "present",

#                         "updated_at":
#                             now,
#                     },
#                 },
#             )

#             updated_record = (
#                 await attendance_collection.find_one(
#                     {
#                         "_id":
#                             record["_id"]
#                     }
#                 )
#             )

#             return AttendanceService._response(
#                 updated_record,
#                 "check_in",
#             )

#         # ========================================================
#         # IN -> OUT
#         # ========================================================

#         sessions = record.get(
#             "sessions",
#             []
#         )

#         if not sessions:

#             return AttendanceService._response(
#                 record,
#                 "invalid_state",
#             )

#         last_session = sessions[-1]

#         # --------------------------------------------------------
#         # Last session must be open
#         # --------------------------------------------------------

#         if last_session.get("out") is not None:

#             return AttendanceService._response(
#                 record,
#                 "invalid_state",
#             )

#         in_time = last_session.get(
#             "in"
#         )

#         if not in_time:

#             return AttendanceService._response(
#                 record,
#                 "invalid_state",
#             )

#         if in_time.tzinfo is None:

#             in_time = (
#                 in_time.replace(
#                     tzinfo=now.tzinfo
#                 )
#             )

#         # ========================================================
#         # CLOSE SESSION
#         # ========================================================

#         await attendance_collection.update_one(

#             {
#                 "_id":
#                     record["_id"]
#             },

#             {
#                 "$set": {

#                     "sessions.$[session].out":
#                         now,

#                     "current_state":
#                         "OUT",

#                     "last_action":
#                         "check_out",

#                     "last_action_at":
#                         now,

#                     "last_similarity":
#                         similarity,

#                     "status":
#                         "present",

#                     "updated_at":
#                         now,
#                 },
#             },

#             array_filters=[
#                 {
#                     "session.out":
#                         None
#                 }
#             ],
#         )

#         # ========================================================
#         # GET UPDATED RECORD
#         # ========================================================

#         updated_record = (
#             await attendance_collection.find_one(
#                 {
#                     "_id":
#                         record["_id"]
#                 }
#             )
#         )

#         # ========================================================
#         # RECALCULATE ENTIRE DAY
#         # ========================================================

#         calculations = (
#             AttendanceService.calculate_day(
#                 sessions=updated_record.get(
#                     "sessions",
#                     []
#                 ),
#                 free_break_minutes=
#                     free_break_minutes,
#                 required_work_minutes=
#                     required_work_minutes,
#             )
#         )

#         # ========================================================
#         # SAVE CALCULATIONS
#         # ========================================================

#         await attendance_collection.update_one(

#             {
#                 "_id":
#                     record["_id"]
#             },

#             {
#                 "$set": {

#                     "total_work_minutes":
#                         calculations[
#                             "total_work_minutes"
#                         ],

#                     "total_break_minutes":
#                         calculations[
#                             "total_break_minutes"
#                         ],

#                     "free_break_minutes":
#                         calculations[
#                             "free_break_minutes"
#                         ],

#                     "excess_break_minutes":
#                         calculations[
#                             "excess_break_minutes"
#                         ],

#                     "effective_work_minutes":
#                         calculations[
#                             "effective_work_minutes"
#                         ],

#                     "required_work_minutes":
#                         calculations[
#                             "required_work_minutes"
#                         ],

#                     "remaining_work_minutes":
#                         calculations[
#                             "remaining_work_minutes"
#                         ],

#                     "updated_at":
#                         now,
#                 },
#             },
#         )

#         # ========================================================
#         # GET FINAL RECORD
#         # ========================================================

#         final_record = (
#             await attendance_collection.find_one(
#                 {
#                     "_id":
#                         record["_id"]
#                 }
#             )
#         )

#         return AttendanceService._response(
#             final_record,
#             "check_out",
#         )

#     # ============================================================
#     # CALCULATE DAY
#     # ============================================================

#     @staticmethod
#     def calculate_day(
#         sessions: list,
#         free_break_minutes: int,
#         required_work_minutes: int,
#     ) -> dict:
#         """
#         Calculate completed work and completed breaks.

#         Important:

#         An open IN session is NOT counted in
#         persisted total_work_minutes.

#         Example:

#             09:00 -> 12:00
#             12:30 -> 15:00
#             15:15 -> IN

#         Stored work:

#             180 + 150 = 330

#         Break:

#             30 + 15 = 45

#         The current 15:15 -> now session is
#         handled separately as LIVE work.
#         """

#         total_work_minutes = 0

#         total_break_minutes = 0

#         normalized_sessions = []

#         # ========================================================
#         # NORMALIZE
#         # ========================================================

#         for session in sessions:

#             in_time = session.get(
#                 "in"
#             )

#             out_time = session.get(
#                 "out"
#             )

#             if not in_time:
#                 continue

#             if in_time.tzinfo is None:

#                 in_time = (
#                     in_time.replace(
#                         tzinfo=datetime.now().astimezone().tzinfo
#                     )
#                 )

#             if out_time:

#                 if out_time.tzinfo is None:

#                     out_time = (
#                         out_time.replace(
#                             tzinfo=in_time.tzinfo
#                         )
#                     )

#             normalized_sessions.append(
#                 {
#                     "in":
#                         in_time,

#                     "out":
#                         out_time,
#                 }
#             )

#         # ========================================================
#         # WORK
#         # ========================================================

#         for session in normalized_sessions:

#             in_time = session["in"]

#             out_time = session["out"]

#             # Current open session:
#             # don't persist it yet.
#             if not out_time:
#                 continue

#             seconds = (
#                 out_time - in_time
#             ).total_seconds()

#             minutes = max(
#                 0,
#                 int(
#                     seconds // 60
#                 )
#             )

#             total_work_minutes += (
#                 minutes
#             )

#         # ========================================================
#         # BREAK
#         # ========================================================
#         #
#         # Only:
#         #
#         # previous OUT -> next IN
#         #
#         # is break.
#         #
#         # Current open IN session is NOT a break.
#         # ========================================================

#         for index in range(
#             len(normalized_sessions) - 1
#         ):

#             current_session = (
#                 normalized_sessions[index]
#             )

#             next_session = (
#                 normalized_sessions[
#                     index + 1
#                 ]
#             )

#             current_out = (
#                 current_session.get(
#                     "out"
#                 )
#             )

#             next_in = (
#                 next_session.get(
#                     "in"
#                 )
#             )

#             if not current_out:
#                 continue

#             if not next_in:
#                 continue

#             seconds = (
#                 next_in - current_out
#             ).total_seconds()

#             break_minutes = max(
#                 0,
#                 int(
#                     seconds // 60
#                 )
#             )

#             total_break_minutes += (
#                 break_minutes
#             )

#         # ========================================================
#         # FREE BREAK
#         # ========================================================

#         free_break_minutes = max(
#             0,
#             int(
#                 free_break_minutes or 0
#             )
#         )

#         # ========================================================
#         # EXCESS BREAK
#         # ========================================================

#         excess_break_minutes = max(
#             0,
#             total_break_minutes
#             - free_break_minutes
#         )

#         # ========================================================
#         # EFFECTIVE WORK
#         # ========================================================

#         effective_work_minutes = max(
#             0,
#             total_work_minutes
#             - excess_break_minutes
#         )

#         # ========================================================
#         # REQUIRED
#         # ========================================================

#         required_work_minutes = max(
#             0,
#             int(
#                 required_work_minutes or 0
#             )
#         )

#         # ========================================================
#         # REMAINING
#         # ========================================================

#         remaining_work_minutes = max(
#             0,
#             required_work_minutes
#             - effective_work_minutes
#         )

#         # ========================================================
#         # COMPLETE
#         # ========================================================

#         is_work_complete = (
#             effective_work_minutes
#             >= required_work_minutes
#         )

#         return {

#             "total_work_minutes":
#                 total_work_minutes,

#             "total_break_minutes":
#                 total_break_minutes,

#             "free_break_minutes":
#                 free_break_minutes,

#             "excess_break_minutes":
#                 excess_break_minutes,

#             "effective_work_minutes":
#                 effective_work_minutes,

#             "required_work_minutes":
#                 required_work_minutes,

#             "remaining_work_minutes":
#                 remaining_work_minutes,

#             "is_work_complete":
#                 is_work_complete,
#         }

#     # ============================================================
#     # LIVE CALCULATION
#     # ============================================================

#     @staticmethod
#     def calculate_live(
#         record: dict,
#         now: Optional[datetime] = None,
#     ) -> dict:
#         """
#         Calculate live attendance values.

#         Persisted values:
#             total_work_minutes
#             total_break_minutes

#         Live values:
#             live_work_minutes
#             live_effective_work_minutes
#             live_remaining_work_minutes

#         The current open IN session is included
#         only in live values.
#         """

#         if now is None:
#             now = now_utc()

#         sessions = (
#             record.get(
#                 "sessions",
#                 []
#             )
#             or []
#         )

#         stored_work_minutes = int(
#             record.get(
#                 "total_work_minutes",
#                 0,
#             )
#             or 0
#         )

#         total_break_minutes = int(
#             record.get(
#                 "total_break_minutes",
#                 0,
#             )
#             or 0
#         )

#         free_break_minutes = int(
#             record.get(
#                 "free_break_minutes",
#                 45,
#             )
#             or 0
#         )

#         required_work_minutes = int(
#             record.get(
#                 "required_work_minutes",
#                 585,
#             )
#             or 0
#         )

#         # ========================================================
#         # LIVE CURRENT SESSION
#         # ========================================================

#         live_current_session_minutes = 0

#         current_state = record.get(
#             "current_state",
#             "OUT",
#         )

#         if (
#             current_state == "IN"
#             and sessions
#         ):

#             current_session = (
#                 sessions[-1]
#             )

#             in_time = current_session.get(
#                 "in"
#             )

#             out_time = current_session.get(
#                 "out"
#             )

#             if (
#                 in_time
#                 and not out_time
#             ):

#                 if in_time.tzinfo is None:

#                     in_time = (
#                         in_time.replace(
#                             tzinfo=now.tzinfo
#                         )
#                     )

#                 if now < in_time:

#                     live_current_session_minutes = 0

#                 else:

#                     live_current_session_minutes = max(
#                         0,
#                         int(
#                             (
#                                 now
#                                 - in_time
#                             ).total_seconds()
#                             // 60
#                         )
#                     )

#         # ========================================================
#         # LIVE TOTAL WORK
#         # ========================================================

#         live_work_minutes = (
#             stored_work_minutes
#             + live_current_session_minutes
#         )

#         # ========================================================
#         # EXCESS BREAK
#         # ========================================================

#         excess_break_minutes = max(
#             0,
#             total_break_minutes
#             - free_break_minutes
#         )

#         # ========================================================
#         # LIVE EFFECTIVE WORK
#         # ========================================================

#         live_effective_work_minutes = max(
#             0,
#             live_work_minutes
#             - excess_break_minutes
#         )

#         # ========================================================
#         # LIVE REMAINING
#         # ========================================================

#         live_remaining_work_minutes = max(
#             0,
#             required_work_minutes
#             - live_effective_work_minutes
#         )

#         # ========================================================
#         # COMPLETE
#         # ========================================================

#         is_working_time_complete = (
#             live_effective_work_minutes
#             >= required_work_minutes
#         )

#         return {

#             "liveCurrentSessionMinutes":
#                 live_current_session_minutes,

#             "liveWorkMinutes":
#                 live_work_minutes,

#             "liveEffectiveWorkMinutes":
#                 live_effective_work_minutes,

#             "liveRemainingWorkMinutes":
#                 live_remaining_work_minutes,

#             "liveWorkingTimeComplete":
#                 is_working_time_complete,
#         }

#     # ============================================================
#     # RESPONSE
#     # ============================================================

#     @staticmethod
#     def _response(
#         record: dict,
#         action: str,
#     ):

#         sessions = (
#             record.get(
#                 "sessions",
#                 []
#             )
#             or []
#         )

#         last_session = (
#             sessions[-1]
#             if sessions
#             else {}
#         )

#         return {

#             "action":
#                 action,

#             "current_state":
#                 record.get(
#                     "current_state",
#                     "OUT",
#                 ),

#             "status":
#                 record.get(
#                     "status",
#                     "present",
#                 ),

#             "check_in":
#                 last_session.get(
#                     "in"
#                 ),

#             "check_out":
#                 last_session.get(
#                     "out"
#                 ),

#             "attendance_id":
#                 str(
#                     record["_id"]
#                 ),

#             "total_work_minutes":
#                 int(
#                     record.get(
#                         "total_work_minutes",
#                         0,
#                     )
#                     or 0
#                 ),

#             "total_break_minutes":
#                 int(
#                     record.get(
#                         "total_break_minutes",
#                         0,
#                     )
#                     or 0
#                 ),

#             "free_break_minutes":
#                 int(
#                     record.get(
#                         "free_break_minutes",
#                         45,
#                     )
#                     or 0
#                 ),

#             "excess_break_minutes":
#                 int(
#                     record.get(
#                         "excess_break_minutes",
#                         0,
#                     )
#                     or 0
#                 ),

#             "effective_work_minutes":
#                 int(
#                     record.get(
#                         "effective_work_minutes",
#                         0,
#                     )
#                     or 0
#                 ),

#             "required_work_minutes":
#                 int(
#                     record.get(
#                         "required_work_minutes",
#                         585,
#                     )
#                     or 0
#                 ),

#             "remaining_work_minutes":
#                 int(
#                     record.get(
#                         "remaining_work_minutes",
#                         0,
#                     )
#                     or 0
#                 ),
#         }



# from datetime import datetime
# from typing import Optional

# from app.core.database import get_database
# from app.core.time import now_utc, local_date
# from app.core.config import settings
# from app.services.policy_service import PolicyService


# class AttendanceService:

#     # ============================================================
#     # MAIN ATTENDANCE PROCESS
#     # ============================================================

#     @staticmethod
#     async def process_attendance(
#         user_id: str,
#         user: dict,
#         similarity: float,
#         force: bool = False,
#     ):
#         """
#         Toggle attendance:

#             OUT -> IN
#             IN  -> OUT

#         Multiple sessions are supported:

#             IN -> OUT
#             IN -> OUT
#             IN -> OUT

#         All calculations are performed from the raw sessions.
#         """

#         db = get_database()
#         now = now_utc()
#         date = local_date()

#         col = db.attendance

#         # --------------------------------------------------------
#         # Get employee policy
#         # --------------------------------------------------------

#         policy = await PolicyService.get_for_user(user_id)

#         required_work_minutes = int(
#             policy.get(
#                 "required_work_minutes",
#                 585,
#             )
#         )

#         free_break_minutes = int(
#             policy.get(
#                 "daily_break_minutes",
#                 45,
#             )
#         )

#         # --------------------------------------------------------
#         # Find today's attendance
#         # --------------------------------------------------------

#         doc = await col.find_one(
#             {
#                 "user_id": user_id,
#                 "date": date,
#             }
#         )

#         # --------------------------------------------------------
#         # Cooldown
#         # --------------------------------------------------------

#         if doc and not force:

#             last_action_at = doc.get(
#                 "last_action_at"
#             )

#             if last_action_at:

#                 if last_action_at.tzinfo is None:
#                     last_action_at = last_action_at.replace(
#                         tzinfo=now.tzinfo
#                     )

#                 elapsed_seconds = (
#                     now - last_action_at
#                 ).total_seconds()

#                 if (
#                     elapsed_seconds
#                     < settings.ATTENDANCE_TOGGLE_COOLDOWN_SECONDS
#                 ):
#                     return AttendanceService._response(
#                         doc,
#                         "cooldown",
#                     )

#         # --------------------------------------------------------
#         # Create today's attendance record
#         # --------------------------------------------------------

#         if not doc:

#             now_values = {
#                 "user_id": user_id,
#                 "date": date,

#                 "sessions": [],

#                 "current_state": "OUT",

#                 # Raw work
#                 "total_work_minutes": 0,

#                 # Break calculation
#                 "total_break_minutes": 0,
#                 "free_break_minutes": free_break_minutes,
#                 "excess_break_minutes": 0,

#                 # Effective work
#                 "effective_work_minutes": 0,

#                 # Policy
#                 "required_work_minutes": required_work_minutes,
#                 "remaining_work_minutes": required_work_minutes,

#                 "status": "present",

#                 "last_action": None,
#                 "last_action_at": None,
#                 "last_similarity": None,

#                 "created_at": now,
#                 "updated_at": now,
#             }

#             insert_result = await col.insert_one(
#                 now_values
#             )

#             doc = await col.find_one(
#                 {
#                     "_id": insert_result.inserted_id
#                 }
#             )

#         # --------------------------------------------------------
#         # Current state
#         # --------------------------------------------------------

#         state = doc.get(
#             "current_state",
#             "OUT",
#         )

#         # ========================================================
#         # CHECK IN
#         # ========================================================

#         if state == "OUT":

#             session = {
#                 "in": now,
#                 "out": None,
#             }

#             await col.update_one(
#                 {
#                     "_id": doc["_id"]
#                 },
#                 {
#                     "$push": {
#                         "sessions": session
#                     },

#                     "$set": {
#                         "current_state": "IN",

#                         "last_action": "check_in",
#                         "last_action_at": now,
#                         "last_similarity": similarity,

#                         "status": "present",

#                         "updated_at": now,
#                     },
#                 },
#             )

#             # Get updated record
#             updated_doc = await col.find_one(
#                 {
#                     "_id": doc["_id"]
#                 }
#             )

#             return {
#                 "action": "check_in",

#                 "current_state": "IN",

#                 "status": "present",

#                 "check_in": now,

#                 "check_out": None,

#                 "attendance_id": str(
#                     doc["_id"]
#                 ),

#                 "total_work_minutes": int(
#                     updated_doc.get(
#                         "total_work_minutes",
#                         0,
#                     )
#                 ),

#                 "effective_work_minutes": int(
#                     updated_doc.get(
#                         "effective_work_minutes",
#                         0,
#                     )
#                 ),

#                 "remaining_work_minutes": int(
#                     updated_doc.get(
#                         "remaining_work_minutes",
#                         required_work_minutes,
#                     )
#                 ),
#             }

#         # ========================================================
#         # CHECK OUT
#         # ========================================================

#         sessions = doc.get(
#             "sessions",
#             []
#         )

#         if not sessions:

#             return AttendanceService._response(
#                 doc,
#                 "invalid_state",
#             )

#         last_session = sessions[-1]

#         # --------------------------------------------------------
#         # Validate current session
#         # --------------------------------------------------------

#         if last_session.get("out") is not None:

#             return AttendanceService._response(
#                 doc,
#                 "invalid_state",
#             )

#         in_time = last_session.get(
#             "in"
#         )

#         if not in_time:

#             return AttendanceService._response(
#                 doc,
#                 "invalid_state",
#             )

#         # --------------------------------------------------------
#         # Timezone normalization
#         # --------------------------------------------------------

#         if in_time.tzinfo is None:

#             in_time = in_time.replace(
#                 tzinfo=now.tzinfo
#             )

#         # --------------------------------------------------------
#         # Close current session
#         # --------------------------------------------------------

#         await col.update_one(
#             {
#                 "_id": doc["_id"]
#             },
#             {
#                 "$set": {
#                     "sessions.$[session].out": now,

#                     "current_state": "OUT",

#                     "last_action": "check_out",
#                     "last_action_at": now,
#                     "last_similarity": similarity,

#                     "status": "present",

#                     "updated_at": now,
#                 },
#             },
#             array_filters=[
#                 {
#                     "session.out": None
#                 }
#             ],
#         )

#         # --------------------------------------------------------
#         # Get updated record
#         # --------------------------------------------------------

#         updated_doc = await col.find_one(
#             {
#                 "_id": doc["_id"]
#             }
#         )

#         # --------------------------------------------------------
#         # Recalculate entire day
#         # --------------------------------------------------------

#         calculations = (
#             AttendanceService.calculate_day(
#                 updated_doc.get(
#                     "sessions",
#                     []
#                 ),
#                 free_break_minutes,
#                 required_work_minutes,
#             )
#         )

#         # --------------------------------------------------------
#         # Save calculated values
#         # --------------------------------------------------------

#         await col.update_one(
#             {
#                 "_id": doc["_id"]
#             },
#             {
#                 "$set": {
#                     "total_work_minutes":
#                         calculations[
#                             "total_work_minutes"
#                         ],

#                     "total_break_minutes":
#                         calculations[
#                             "total_break_minutes"
#                         ],

#                     "free_break_minutes":
#                         calculations[
#                             "free_break_minutes"
#                         ],

#                     "excess_break_minutes":
#                         calculations[
#                             "excess_break_minutes"
#                         ],

#                     "effective_work_minutes":
#                         calculations[
#                             "effective_work_minutes"
#                         ],

#                     "required_work_minutes":
#                         calculations[
#                             "required_work_minutes"
#                         ],

#                     "remaining_work_minutes":
#                         calculations[
#                             "remaining_work_minutes"
#                         ],

#                     "updated_at": now,
#                 }
#             },
#         )

#         return {
#             "action": "check_out",

#             "current_state": "OUT",

#             "status": "present",

#             "check_in": in_time,

#             "check_out": now,

#             "attendance_id": str(
#                 doc["_id"]
#             ),

#             "total_work_minutes":
#                 calculations[
#                     "total_work_minutes"
#                 ],

#             "total_break_minutes":
#                 calculations[
#                     "total_break_minutes"
#                 ],

#             "free_break_minutes":
#                 calculations[
#                     "free_break_minutes"
#                 ],

#             "excess_break_minutes":
#                 calculations[
#                     "excess_break_minutes"
#                 ],

#             "effective_work_minutes":
#                 calculations[
#                     "effective_work_minutes"
#                 ],

#             "required_work_minutes":
#                 calculations[
#                     "required_work_minutes"
#                 ],

#             "remaining_work_minutes":
#                 calculations[
#                     "remaining_work_minutes"
#                 ],

#             "is_work_complete":
#                 calculations[
#                     "is_work_complete"
#                 ],
#         }

#     # ============================================================
#     # DAILY CALCULATION
#     # ============================================================

#     @staticmethod
#     def calculate_day(
#         sessions: list,
#         free_break_minutes: int,
#         required_work_minutes: int,
#     ) -> dict:
#         """
#         Calculate the complete attendance day.

#         Example:

#             Session 1:
#                 09:00 -> 12:00 = 180 min

#             Session 2:
#                 12:30 -> 15:00 = 150 min

#             Session 3:
#                 16:00 -> 18:00 = 120 min

#             Total work:
#                 180 + 150 + 120 = 450

#             Break:
#                 30 + 60 = 90

#             Free break:
#                 45

#             Excess:
#                 90 - 45 = 45

#             Effective work:
#                 450 - 45 = 405
#         """

#         total_work_minutes = 0
#         total_break_minutes = 0

#         normalized_sessions = []

#         # --------------------------------------------------------
#         # Normalize sessions
#         # --------------------------------------------------------

#         for session in sessions:

#             in_time = session.get("in")
#             out_time = session.get("out")

#             if not in_time:
#                 continue

#             if in_time.tzinfo is None:
#                 in_time = in_time.replace(
#                     tzinfo=datetime.now().astimezone().tzinfo
#                 )

#             if out_time and out_time.tzinfo is None:
#                 out_time = out_time.replace(
#                     tzinfo=in_time.tzinfo
#                 )

#             normalized_sessions.append(
#                 {
#                     "in": in_time,
#                     "out": out_time,
#                 }
#             )

#         # --------------------------------------------------------
#         # Calculate work
#         # --------------------------------------------------------

#         for session in normalized_sessions:

#             in_time = session["in"]
#             out_time = session["out"]

#             # Current open session is not yet
#             # included in completed work.
#             if not out_time:
#                 continue

#             seconds = (
#                 out_time - in_time
#             ).total_seconds()

#             minutes = max(
#                 0,
#                 int(seconds // 60)
#             )

#             total_work_minutes += minutes

#         # --------------------------------------------------------
#         # Calculate breaks
#         # --------------------------------------------------------
#         #
#         # Break is:
#         #
#         # previous OUT
#         #       ↓
#         # next IN
#         #
#         # Do NOT count current unfinished
#         # IN session as a break.
#         # --------------------------------------------------------

#         for index in range(
#             len(normalized_sessions) - 1
#         ):

#             current = normalized_sessions[index]
#             next_session = normalized_sessions[
#                 index + 1
#             ]

#             current_out = current.get(
#                 "out"
#             )

#             next_in = next_session.get(
#                 "in"
#             )

#             if not current_out or not next_in:
#                 continue

#             seconds = (
#                 next_in - current_out
#             ).total_seconds()

#             break_minutes = max(
#                 0,
#                 int(seconds // 60)
#             )

#             total_break_minutes += (
#                 break_minutes
#             )

#         # --------------------------------------------------------
#         # Free break
#         # --------------------------------------------------------

#         free_break_minutes = max(
#             0,
#             int(free_break_minutes or 0)
#         )

#         # --------------------------------------------------------
#         # Excess break
#         # --------------------------------------------------------

#         excess_break_minutes = max(
#             0,
#             total_break_minutes
#             - free_break_minutes
#         )

#         # --------------------------------------------------------
#         # Effective work
#         # --------------------------------------------------------

#         effective_work_minutes = max(
#             0,
#             total_work_minutes
#             - excess_break_minutes
#         )

#         # --------------------------------------------------------
#         # Required work
#         # --------------------------------------------------------

#         required_work_minutes = max(
#             0,
#             int(required_work_minutes or 0)
#         )

#         # --------------------------------------------------------
#         # Remaining work
#         # --------------------------------------------------------

#         remaining_work_minutes = max(
#             0,
#             required_work_minutes
#             - effective_work_minutes
#         )

#         # --------------------------------------------------------
#         # Complete?
#         # --------------------------------------------------------

#         is_work_complete = (
#             effective_work_minutes
#             >= required_work_minutes
#         )

#         return {
#             "total_work_minutes":
#                 total_work_minutes,

#             "total_break_minutes":
#                 total_break_minutes,

#             "free_break_minutes":
#                 free_break_minutes,

#             "excess_break_minutes":
#                 excess_break_minutes,

#             "effective_work_minutes":
#                 effective_work_minutes,

#             "required_work_minutes":
#                 required_work_minutes,

#             "remaining_work_minutes":
#                 remaining_work_minutes,

#             "is_work_complete":
#                 is_work_complete,
#         }

#     # ============================================================
#     # RESPONSE
#     # ============================================================

#     @staticmethod
#     def _response(
#         doc: dict,
#         action: str,
#     ):

#         sessions = doc.get(
#             "sessions",
#             []
#         )

#         last_session = (
#             sessions[-1]
#             if sessions
#             else {}
#         )

#         return {
#             "action": action,

#             "current_state":
#                 doc.get(
#                     "current_state",
#                     "OUT",
#                 ),

#             "status":
#                 doc.get(
#                     "status",
#                     "present",
#                 ),

#             "check_in":
#                 last_session.get(
#                     "in"
#                 ),

#             "check_out":
#                 last_session.get(
#                     "out"
#                 ),

#             "attendance_id":
#                 str(doc["_id"]),

#             "total_work_minutes":
#                 int(
#                     doc.get(
#                         "total_work_minutes",
#                         0,
#                     )
#                 ),

#             "total_break_minutes":
#                 int(
#                     doc.get(
#                         "total_break_minutes",
#                         0,
#                     )
#                 ),

#             "free_break_minutes":
#                 int(
#                     doc.get(
#                         "free_break_minutes",
#                         45,
#                     )
#                 ),

#             "excess_break_minutes":
#                 int(
#                     doc.get(
#                         "excess_break_minutes",
#                         0,
#                     )
#                 ),

#             "effective_work_minutes":
#                 int(
#                     doc.get(
#                         "effective_work_minutes",
#                         0,
#                     )
#                 ),

#             "required_work_minutes":
#                 int(
#                     doc.get(
#                         "required_work_minutes",
#                         585,
#                     )
#                 ),

#             "remaining_work_minutes":
#                 int(
#                     doc.get(
#                         "remaining_work_minutes",
#                         0,
#                     )
#                 ),
#         }



















# from datetime import timedelta
# from app.core.database import get_database
# from app.core.time import now_utc, now_local, local_date
# from app.core.config import settings

# class AttendanceService:
#     @staticmethod
#     async def process_attendance(user_id: str, user: dict, similarity: float, force: bool=False):
#         db = get_database(); now = now_utc(); date = local_date()
#         col = db.attendance
#         doc = await col.find_one({"user_id": user_id, "date": date})
#         if doc and not force:
#             last = doc.get("last_action_at")
#             if last:
#                 if last.tzinfo is None: last = last.replace(tzinfo=now.tzinfo)
#                 if (now-last).total_seconds() < settings.ATTENDANCE_TOGGLE_COOLDOWN_SECONDS:
#                     return AttendanceService._response(doc, "cooldown")
#         if not doc:
#             doc = {"user_id": user_id, "date": date, "sessions": [], "current_state": "OUT", "total_work_minutes": 0, "created_at": now, "updated_at": now}
#             await col.insert_one(doc); doc = await col.find_one({"_id": doc.get("_id")}) if doc.get("_id") else doc
#         state = doc.get("current_state", "OUT")
#         if state == "OUT":
#             session = {"in": now, "out": None}
#             result = await col.update_one({"_id": doc["_id"]}, {"$push":{"sessions":session}, "$set":{"current_state":"IN","last_action":"check_in","last_action_at":now,"last_similarity":similarity,"updated_at":now}})
#             return {"action":"check_in","current_state":"IN","status":"present","check_in":now,"check_out":None,"attendance_id":str(doc["_id"])}
#         sessions = doc.get("sessions", [])
#         if not sessions or sessions[-1].get("out") is not None:
#             return AttendanceService._response(doc, "invalid_state")
#         in_time = sessions[-1]["in"]
#         if in_time.tzinfo is None: in_time = in_time.replace(tzinfo=now.tzinfo)
#         await col.update_one({"_id":doc["_id"]},{"$set":{"sessions.$[s].out":now,"current_state":"OUT","last_action":"check_out","last_action_at":now,"last_similarity":similarity,"updated_at":now}, "$inc":{"total_work_minutes":max(0,int((now-in_time).total_seconds()//60))}}, array_filters=[{"s.out":None}])
#         return {"action":"check_out","current_state":"OUT","status":"present","check_in":in_time,"check_out":now,"attendance_id":str(doc["_id"])}

#     @staticmethod
#     def _response(doc, action):
#         sessions=doc.get("sessions",[]); last=sessions[-1] if sessions else {}
#         return {"action":action,"current_state":doc.get("current_state","OUT"),"status":"present","check_in":last.get("in"),"check_out":last.get("out"),"attendance_id":str(doc["_id"])}
