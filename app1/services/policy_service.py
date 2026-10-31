from datetime import datetime, timezone

from bson import ObjectId

from app.core.database import get_database


DEFAULT_POLICY = {
    "name": "Standard",

    "start_time": "09:45",

    # Male/default policy
    "required_work_minutes": 585,

    # Daily free OUT/break allowance
    "daily_break_minutes": 45,

    "carry_forward": True,

    "monthly_expiry": True,

    "is_active": True,
}


class PolicyService:

    # ============================================================
    # GET USER POLICY
    # ============================================================

    @staticmethod
    async def get_for_user(user_id: str):

        db = get_database()

        user = None

        # --------------------------------------------------------
        # Find user
        # --------------------------------------------------------

        if ObjectId.is_valid(
            str(user_id)
        ):

            user = await db.users.find_one(
                {
                    "_id": ObjectId(
                        str(user_id)
                    )
                }
            )

        # --------------------------------------------------------
        # User assigned policy
        # --------------------------------------------------------

        policy_id = (
            user.get("policy_id")
            if user
            else None
        )

        if policy_id:

            if ObjectId.is_valid(
                str(policy_id)
            ):

                policy = (
                    await db.policies.find_one(
                        {
                            "_id": ObjectId(
                                str(policy_id)
                            ),

                            "is_active": True,
                        }
                    )
                )

                if policy:
                    return policy

        # --------------------------------------------------------
        # Standard policy
        # --------------------------------------------------------

        policy = await db.policies.find_one(
            {
                "name": "Standard",
                "is_active": True,
            }
        )

        return (
            policy
            or DEFAULT_POLICY
        )

    # ============================================================
    # ENSURE MONTHLY WALLET
    # ============================================================

    @staticmethod
    async def ensure_wallet(
        user_id: str,
        month: str,
    ):

        db = get_database()

        existing = (
            await db.break_wallets.find_one(
                {
                    "user_id": user_id,
                    "month": month,
                }
            )
        )

        if existing:
            return existing

        now = datetime.now(
            timezone.utc
        )

        doc = {
            "user_id": user_id,

            "month": month,

            "opening_balance": 0,

            "earned_minutes": 0,

            "used_minutes": 0,

            "closing_balance": 0,

            "created_at": now,

            "updated_at": now,
        }

        try:

            await db.break_wallets.insert_one(
                doc
            )

        except Exception:
            # Another request may have created
            # the wallet simultaneously.
            pass

        return await db.break_wallets.find_one(
            {
                "user_id": user_id,
                "month": month,
            }
        )

    # ============================================================
    # DAILY BREAK
    # ============================================================

    @staticmethod
    async def add_daily_break(
        user_id: str,
        month: str,
        policy: dict,
    ):

        db = get_database()

        daily_minutes = int(
            policy.get(
                "daily_break_minutes",
                45,
            )
        )

        wallet = (
            await PolicyService.ensure_wallet(
                user_id,
                month,
            )
        )

        if not wallet:
            return None

        return wallet






















# from calendar import monthrange
# from datetime import datetime, timezone
# from app.core.database import get_database
# from app.core.time import local_date

# DEFAULT_POLICY = {"name":"Standard","start_time":"09:45","required_work_minutes":585,"daily_break_minutes":45,"carry_forward":True,"monthly_expiry":True}

# class PolicyService:
#     @staticmethod
#     async def get_for_user(user_id: str):
#         db=get_database(); user=await db.users.find_one({"_id":__import__('bson').ObjectId(user_id)})
#         pid=user.get("policy_id") if user else None
#         if pid:
#             p=await db.policies.find_one({"_id":__import__('bson').ObjectId(pid)})
#             if p:return p
#         p=await db.policies.find_one({"name":"Standard"})
#         return p or DEFAULT_POLICY

#     @staticmethod
#     async def ensure_wallet(user_id: str, month: str):
#         db=get_database(); existing=await db.break_wallets.find_one({"user_id":user_id,"month":month})
#         if existing:return existing
#         doc={"user_id":user_id,"month":month,"opening_balance":0,"earned_minutes":0,"used_minutes":0,"closing_balance":0,"created_at":datetime.now(timezone.utc),"updated_at":datetime.now(timezone.utc)}
#         try:
#             await db.break_wallets.insert_one(doc)
#         except Exception: pass
#         return await db.break_wallets.find_one({"user_id":user_id,"month":month})
